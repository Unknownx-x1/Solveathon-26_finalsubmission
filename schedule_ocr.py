import io
import re
from datetime import datetime


def _missing_dependency_error(package_name: str) -> dict:
    return {
        "success": False,
        "error": f"Missing dependency: {package_name}. Install the OCR requirements to enable schedule upload."
    }


def _safe_imports():
    """
    Import heavier OCR dependencies lazily so the app can still run
    even if OCR extras aren't installed.
    """
    try:
        import easyocr  # type: ignore
    except Exception:
        easyocr = None
    try:
        import cv2  # type: ignore
    except Exception:
        cv2 = None
    try:
        import numpy as np  # type: ignore
    except Exception:
        np = None
    try:
        from PIL import Image  # type: ignore
    except Exception:
        Image = None
    try:
        from pdf2image import convert_from_bytes  # type: ignore
    except Exception:
        convert_from_bytes = None

    return easyocr, cv2, np, Image, convert_from_bytes


_ocr_reader = None


def _get_ocr_reader(easyocr):
    global _ocr_reader
    if _ocr_reader is None:
        _ocr_reader = easyocr.Reader(["en"])
    return _ocr_reader


def _readtext_multi_pass(reader, image_np):
    passes = [
        {
            "image": image_np,
            "kwargs": {
                "detail": 1,
                "paragraph": False,
                "text_threshold": 0.5,
                "low_text": 0.25,
                "link_threshold": 0.35,
            },
        },
        {
            "image": image_np,
            "kwargs": {
                "detail": 1,
                "paragraph": False,
                "text_threshold": 0.35,
                "low_text": 0.15,
                "link_threshold": 0.2,
            },
        },
    ]

    collected = []
    for p in passes:
        try:
            results = reader.readtext(p["image"], **p["kwargs"])
            collected.extend(results)
        except Exception:
            continue
    return collected


def _preprocess_for_schedule(cv2, np, image_bgr):
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    denoised = cv2.fastNlMeansDenoising(gray, None, 12, 7, 21)
    binary = cv2.adaptiveThreshold(
        denoised, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 12
    )
    kernel = np.ones((2, 2), np.uint8)
    cleaned = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel)
    return cleaned


def _extract_text_from_image(easyocr, cv2, np, pil_image):
    reader = _get_ocr_reader(easyocr)
    image_np = cv2.cvtColor(np.array(pil_image), cv2.COLOR_RGB2BGR)

    preprocessed = _preprocess_for_schedule(cv2, np, image_np)
    results = _readtext_multi_pass(reader, image_np)
    results.extend(_readtext_multi_pass(reader, preprocessed))

    full_text = "\n".join([text for (_, text, _) in results])
    return full_text, results


def _extract_schedule_from_ocr_results(np, results):
    if not results:
        return []

    dash_chars = r"\-–—−"
    range_regex = re.compile(rf"(\d{{2,4}})\s*[{dash_chars}]\s*(\d{{2,4}})")
    date_regex = re.compile(r"^\s*([1-9]|[12]\d|3[01])\s*$")
    combined_regex = re.compile(
        rf"^\s*([1-9]|[12]\d|3[01])\s+(\d{{2,4}})\s*[{dash_chars}]\s*(\d{{2,4}})\s*$"
    )

    rows = []
    for bbox, text, conf in results:
        if text is None:
            continue
        t = str(text).strip()
        if not t:
            continue

        xs = [p[0] for p in bbox]
        ys = [p[1] for p in bbox]
        x_center = float(sum(xs)) / len(xs)
        y_center = float(sum(ys)) / len(ys)
        height = max(ys) - min(ys)

        rows.append(
            {
                "text": t,
                "conf": float(conf) if conf is not None else 0.0,
                "x": x_center,
                "y": y_center,
                "h": max(float(height), 1.0),
            }
        )

    if not rows:
        return []

    median_h = float(np.median([r["h"] for r in rows]))
    row_tol = max(12.0, median_h * 1.2)

    date_tokens = []
    range_tokens = []
    direct_entries = []

    for r in rows:
        text = r["text"]
        lower = text.lower()
        if "date" in lower or "room" in lower or "schedule" in lower or "block" in lower:
            continue

        m_combined = combined_regex.search(text)
        if m_combined:
            d = int(m_combined.group(1))
            rs = int(m_combined.group(2))
            re_ = int(m_combined.group(3))
            if rs <= re_:
                direct_entries.append({"date": d, "room_start": rs, "room_end": re_})
            continue

        m_date = date_regex.search(text)
        if m_date:
            date_tokens.append({**r, "date": int(m_date.group(1))})
            continue

        m_range = range_regex.search(text.replace(".", "").replace(",", ""))
        if m_range:
            rs = int(m_range.group(1))
            re_ = int(m_range.group(2))
            if rs <= re_:
                range_tokens.append({**r, "room_start": rs, "room_end": re_})

    entries = []
    seen_dates = set()

    for e in direct_entries:
        if e["date"] not in seen_dates:
            entries.append(e)
            seen_dates.add(e["date"])

    for d in sorted(date_tokens, key=lambda x: x["date"]):
        if d["date"] in seen_dates:
            continue
        candidates = []
        for rg in range_tokens:
            y_dist = abs(rg["y"] - d["y"])
            if y_dist <= row_tol and rg["x"] > d["x"]:
                score = y_dist + max(0.0, (d["x"] - rg["x"]) * 0.001)
                candidates.append((score, rg))
        if not candidates:
            continue
        candidates.sort(key=lambda x: x[0])
        best = candidates[0][1]
        entries.append(
            {"date": d["date"], "room_start": best["room_start"], "room_end": best["room_end"]}
        )
        seen_dates.add(d["date"])

    entries.sort(key=lambda x: x["date"])
    return entries


def _extract_month_from_text(text: str) -> str:
    months = [
        "january",
        "february",
        "march",
        "april",
        "may",
        "june",
        "july",
        "august",
        "september",
        "october",
        "november",
        "december",
    ]

    text_lower = (text or "").lower()
    found_month = None
    for month in months:
        if month in text_lower:
            found_month = month.capitalize()
            break

    year_match = re.search(r"\b(20\d{2}|19\d{2})\b", text or "")
    year = int(year_match.group(1)) if year_match else datetime.now().year

    if found_month:
        return f"{found_month} {year}"
    return datetime.now().strftime("%B %Y")


def _month_days_from_label(month_label: str):
    now = datetime.now()
    month_match = re.search(
        r"(January|February|March|April|May|June|July|August|September|October|November|December)",
        month_label or "",
        re.IGNORECASE,
    )
    year_match = re.search(r"(\d{4})", month_label or "")
    year = int(year_match.group(1)) if year_match else now.year
    if month_match:
        month_name = month_match.group(1).capitalize()
        month_num = datetime.strptime(month_name, "%B").month
    else:
        month_num = now.month
    next_month = datetime(year + (1 if month_num == 12 else 0), 1 if month_num == 12 else month_num + 1, 1)
    days_in_month = int((next_month - datetime(year, month_num, 1)).days)
    return year, month_num, days_in_month


def _normalize_schedule_entries(entries, days_in_month: int):
    """
    Normalize noisy OCR schedule rows by enforcing a repeating 6-workday + 1-holiday pattern
    when a strong pattern is detected. Returns (normalized_entries, holiday_days).
    """
    easyocr, cv2, np, Image, convert_from_bytes = _safe_imports()
    if np is None:
        return entries, []

    clean = []
    seen = set()
    for e in sorted(entries, key=lambda x: x["date"]):
        d = int(e["date"])
        rs = int(e["room_start"])
        re_ = int(e["room_end"])
        if d < 1 or d > days_in_month or rs > re_:
            continue
        key = (d, rs, re_)
        if key in seen:
            continue
        seen.add(key)
        clean.append({"date": d, "room_start": rs, "room_end": re_})

    if len(clean) < 10:
        return clean, []

    freq = {}
    for e in clean:
        key = (e["room_start"], e["room_end"])
        freq[key] = freq.get(key, 0) + 1
    canonical = sorted(freq.keys(), key=lambda k: (-freq[k], k[0], k[1]))[:6]
    canonical = sorted(canonical, key=lambda k: (k[0], k[1]))
    if len(canonical) < 6:
        return clean, []

    by_day = {}
    for e in clean:
        by_day.setdefault(e["date"], []).append((e["room_start"], e["room_end"]))

    def score_offset(off: int) -> float:
        score = 0.0
        for day in range(1, days_in_month + 1):
            pos = (day + off) % 7
            day_ranges = by_day.get(day, [])
            if pos == 6:
                score += 1.0 if not day_ranges else -2.0
            else:
                expected = canonical[pos]
                if not day_ranges:
                    score -= 0.5
                elif expected in day_ranges:
                    score += 2.0
                else:
                    score -= 1.0
        return score

    best_offset = max(range(7), key=score_offset)
    best_score = score_offset(best_offset)
    if best_score < days_in_month * 0.6:
        return clean, []

    normalized = []
    holiday_days = []
    for day in range(1, days_in_month + 1):
        pos = (day + best_offset) % 7
        if pos == 6:
            holiday_days.append(day)
            continue
        rs, re_ = canonical[pos]
        normalized.append({"date": day, "room_start": rs, "room_end": re_})

    return normalized, holiday_days


def process_schedule_image(file_bytes: bytes, filename: str):
    easyocr, cv2, np, Image, convert_from_bytes = _safe_imports()
    if Image is None:
        return _missing_dependency_error("Pillow")
    if easyocr is None:
        return _missing_dependency_error("easyocr")
    if cv2 is None:
        return _missing_dependency_error("opencv-python")
    if np is None:
        return _missing_dependency_error("numpy")

    try:
        image = Image.open(io.BytesIO(file_bytes))
        if image.mode != "RGB":
            image = image.convert("RGB")
        text, results = _extract_text_from_image(easyocr, cv2, np, image)
        month = _extract_month_from_text(text)
        _, _, days_in_month = _month_days_from_label(month)

        schedules = _extract_schedule_from_ocr_results(np, results)
        schedules, holiday_days = _normalize_schedule_entries(schedules, days_in_month)

        return {
            "month": month,
            "schedules": schedules,
            "holidays": holiday_days,
            "raw_text": text,
            "success": True,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def _process_image_object(pil_image):
    easyocr, cv2, np, Image, convert_from_bytes = _safe_imports()
    if easyocr is None or cv2 is None or np is None:
        return {"success": False, "error": "Missing OCR dependencies"}

    try:
        text, results = _extract_text_from_image(easyocr, cv2, np, pil_image)
        month = _extract_month_from_text(text)
        _, _, days_in_month = _month_days_from_label(month)
        schedules = _extract_schedule_from_ocr_results(np, results)
        schedules, holiday_days = _normalize_schedule_entries(schedules, days_in_month)
        return {"month": month, "schedules": schedules, "holidays": holiday_days, "raw_text": text}
    except Exception as e:
        return {"success": False, "error": str(e)}


def process_schedule_pdf(file_bytes: bytes):
    easyocr, cv2, np, Image, convert_from_bytes = _safe_imports()
    if convert_from_bytes is None:
        return _missing_dependency_error("pdf2image")
    if Image is None:
        return _missing_dependency_error("Pillow")

    try:
        images = convert_from_bytes(file_bytes, first_page=1, last_page=1)
        if not images:
            return {"success": False, "error": "No pages found in PDF"}
        result = _process_image_object(images[0])
        if result.get("success") is False:
            return result
        result["success"] = True
        return result
    except Exception as e:
        return {"success": False, "error": str(e)}

