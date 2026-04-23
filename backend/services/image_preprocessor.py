"""
Services — Image Preprocessor

OpenCV preprocessing pipeline that normalises images before any OCR engine
touches them. Handles EXIF rotation, resizing, and per-route enhancement.
"""

from __future__ import annotations

import io

import cv2
import numpy as np


class ImagePreprocessError(Exception):
    """Raised when image preprocessing fails cleanly."""


# EXIF orientation tag id → clockwise rotation degrees
_EXIF_ORIENTATION_TAG = 0x0112
_EXIF_ROTATION = {3: 180, 6: 270, 8: 90}


def _exif_rotation_degrees(image_bytes: bytes) -> int:
    try:
        from PIL import Image  # local import — Pillow is lighter than cv2 for EXIF

        with Image.open(io.BytesIO(image_bytes)) as pil_img:
            exif = pil_img._getexif()  # type: ignore[attr-defined]
            if not exif:
                return 0
            return _EXIF_ROTATION.get(exif.get(_EXIF_ORIENTATION_TAG, 1), 0)
    except Exception:
        return 0


def _resize_max(img: np.ndarray, max_side: int) -> np.ndarray:
    h, w = img.shape[:2]
    if max(h, w) <= max_side:
        return img
    scale = max_side / max(h, w)
    return cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)


def preprocess_image(image_bytes: bytes, route_hint: str = "printed") -> bytes:
    """
    Preprocess raw image bytes for OCR.

    Args:
        image_bytes: Raw image file bytes (JPEG, PNG, WebP, HEIC, …).
        route_hint: ``"handwritten"`` applies adaptive thresholding + denoise;
                    ``"printed"`` applies grayscale only.

    Returns:
        Preprocessed image as PNG bytes.

    Raises:
        ImagePreprocessError: On any failure so callers get a clean error.
    """
    try:
        arr = np.frombuffer(image_bytes, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)

        if img is None:
            # cv2 can't handle HEIC/AVIF — fall back to Pillow
            from PIL import Image as PilImage

            pil_img = PilImage.open(io.BytesIO(image_bytes)).convert("RGB")
            img = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)

        if img is None:
            raise ImagePreprocessError("Could not decode image — unsupported or corrupt format.")

        # Auto-rotate from EXIF orientation
        degrees = _exif_rotation_degrees(image_bytes)
        if degrees == 90:
            img = cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE)
        elif degrees == 180:
            img = cv2.rotate(img, cv2.ROTATE_180)
        elif degrees == 270:
            img = cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)

        img = _resize_max(img, 2048)

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        if route_hint == "handwritten":
            gray = cv2.adaptiveThreshold(
                gray,
                255,
                cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY,
                blockSize=11,
                C=2,
            )
            gray = cv2.fastNlMeansDenoising(gray, h=10)

        _, buf = cv2.imencode(".png", gray)
        return buf.tobytes()

    except ImagePreprocessError:
        raise
    except Exception as exc:
        raise ImagePreprocessError(f"Image preprocessing failed: {exc}") from exc
