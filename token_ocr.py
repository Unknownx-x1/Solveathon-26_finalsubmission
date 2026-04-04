import os
import re
import uuid

import cv2
import easyocr
import numpy as np
from PIL import Image


_OCR_READER = None
_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}


def allowed_image(filename):
    _, ext = os.path.splitext((filename or "").lower())
    return ext in _IMAGE_EXTENSIONS


def save_temp_upload(file_storage, upload_dir):
    os.makedirs(upload_dir, exist_ok=True)
    _, ext = os.path.splitext((file_storage.filename or "").lower())
    ext = ext or ".png"
    temp_name = f"ocr_{uuid.uuid4().hex}{ext}"
    temp_path = os.path.join(upload_dir, temp_name)
    file_storage.save(temp_path)
    return temp_path


def cleanup_file(path):
    if path and os.path.exists(path):
        os.remove(path)


def _get_reader():
    global _OCR_READER
    if _OCR_READER is None:
        try:
            _OCR_READER = easyocr.Reader(["en"], gpu=False)
        except Exception as error:
            raise RuntimeError(f"OCR engine initialization failed: {error}")
    return _OCR_READER


def _preprocess_image(image_path):
    image = Image.open(image_path).convert("RGB")
    image_np = np.array(image)
    gray = cv2.cvtColor(image_np, cv2.COLOR_RGB2GRAY)
    gray = cv2.GaussianBlur(gray, (3, 3), 0)
    enlarged = cv2.resize(gray, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
    _, threshold = cv2.threshold(enlarged, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    inverted = cv2.bitwise_not(threshold)
    adaptive = cv2.adaptiveThreshold(
        enlarged,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        31,
        11,
    )
    return [image_np, enlarged, threshold, inverted, adaptive]


def _extract_candidates(results):
    candidates = []
    for index, result in enumerate(results):
        bbox, text, confidence = result
        matches = re.findall(r"\d+", text or "")
        if not matches:
            continue

        xs = [point[0] for point in bbox]
        ys = [point[1] for point in bbox]
        area = max(xs) - min(xs)
        area *= max(ys) - min(ys)

        for match in matches:
            candidates.append({
                "value": int(match),
                "text": text,
                "confidence": float(confidence or 0),
                "area": float(area),
                "index": index,
                "length": len(match),
                "is_digits_only": bool(re.fullmatch(r"\d+", (text or "").strip())),
            })
    return candidates


def extract_token_number(image_path):
    processed_images = _preprocess_image(image_path)
    reader = _get_reader()

    all_results = []
    for image in processed_images:
        all_results.extend(reader.readtext(image, detail=1, allowlist="0123456789"))
    candidates = _extract_candidates(all_results)

    if not candidates:
        raise ValueError("No numeric token detected in the image.")

    digit_only_candidates = [item for item in candidates if item["is_digits_only"]]
    if digit_only_candidates:
        candidates = digit_only_candidates

    three_digit_candidates = [item for item in candidates if item["length"] == 3]
    if three_digit_candidates:
        candidates = three_digit_candidates

    # Prefer confident OCR first, then prominent text, then later detections as a tie-breaker.
    ranked = sorted(
        candidates,
        key=lambda item: (
            item["confidence"],
            item["area"],
            item["length"],
            item["index"],
        ),
    )
    best_candidate = ranked[-1]
    return best_candidate["value"], {
        "rawText": " ".join([item[1] for item in all_results]),
        "matchedText": best_candidate["text"],
        "confidence": round(best_candidate["confidence"], 4),
        "candidates": [item["value"] for item in candidates],
    }
