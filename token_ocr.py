import os
import os
import re
import uuid

import cv2
import easyocr
import numpy as np
from PIL import Image


_OCR_READER = None
_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}
_PRIMARY_CONFIDENCE = 0.5


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
    height, width = image_np.shape[:2]
    max_side = max(height, width)
    if max_side > 1800:
        scale = 1800.0 / max_side
        image_np = cv2.resize(
            image_np,
            None,
            fx=scale,
            fy=scale,
            interpolation=cv2.INTER_AREA,
        )
    gray = cv2.cvtColor(image_np, cv2.COLOR_RGB2GRAY)
    gray = cv2.GaussianBlur(gray, (3, 3), 0)
    enlarged = cv2.resize(gray, None, fx=1.8, fy=1.8, interpolation=cv2.INTER_CUBIC)
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
    return {
        "base": image_np,
        "gray": enlarged,
        "threshold": threshold,
        "inverted": inverted,
        "adaptive": adaptive,
    }


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


def _select_best_candidate(candidates):
    if not candidates:
        return None, []

    filtered = candidates
    digit_only_candidates = [item for item in filtered if item["is_digits_only"]]
    if digit_only_candidates:
        filtered = digit_only_candidates

    preferred_length_candidates = [item for item in filtered if item["length"] in (3, 4)]
    if preferred_length_candidates:
        filtered = preferred_length_candidates

    ranked = sorted(
        filtered,
        key=lambda item: (
            item["confidence"],
            item["area"],
            item["length"],
            -item["index"],
        ),
    )
    return ranked[-1], filtered


def extract_token_number(image_path):
    processed_images = _preprocess_image(image_path)
    reader = _get_reader()

    passes = [
        processed_images["base"],
        processed_images["threshold"],
        processed_images["gray"],
        processed_images["inverted"],
        processed_images["adaptive"],
    ]
    all_results = []
    best_candidate = None
    chosen_candidates = []

    for index, image in enumerate(passes):
        results = reader.readtext(image, detail=1, allowlist="0123456789")
        all_results.extend(results)
        best_candidate, chosen_candidates = _select_best_candidate(_extract_candidates(all_results))
        if not best_candidate:
            continue
        if best_candidate["confidence"] >= _PRIMARY_CONFIDENCE and best_candidate["length"] in (3, 4):
            break

    if not best_candidate:
        raise ValueError("No numeric token detected in the image.")

    return best_candidate["value"], {
        "rawText": " ".join([item[1] for item in all_results]),
        "matchedText": best_candidate["text"],
        "confidence": round(best_candidate["confidence"], 4),
        "candidates": [item["value"] for item in chosen_candidates],
    }
