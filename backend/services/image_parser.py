"""
Services — Multi-Engine Image Parser

Orchestrates Gemini Vision, pix2tex, and Tesseract OCR to extract STEM
questions from uploaded images.

Engine routing:
  handwritten / mixed / has_diagrams → Gemini (full) → Gemini (retry)
  printed_latex                       → pix2tex       → Gemini (full)
  printed_text                        → Tesseract     → Gemini (full)

If both engines return confidence < 0.70 a LowConfidenceError is raised
with the best partial result attached so the frontend can offer a fallback.
"""

from __future__ import annotations

import asyncio
import io
import json
import os
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import structlog

from config.settings import settings
from core.exceptions import AIServiceError
from services.image_preprocessor import ImagePreprocessError, preprocess_image

logger = structlog.get_logger("equated.services.image_parser")

_CONFIDENCE_THRESHOLD = 0.70


# ── Data structures ───────────────────────────────────────────────────────────


@dataclass
class ParseResult:
    questions: list[str]
    latex_versions: list[str]
    engine_used: str
    confidence: float
    subject_hints: list[str]
    raw_output: str
    question_count: int = field(init=False)

    def __post_init__(self) -> None:
        self.question_count = len(self.questions)


@dataclass
class _TriageResult:
    type: str           # "handwritten" | "printed_latex" | "printed_text" | "mixed"
    question_count: int
    has_diagrams: bool
    confidence: float


class LowConfidenceError(Exception):
    """Raised when no engine exceeds the confidence threshold."""

    def __init__(self, message: str, partial_result: ParseResult) -> None:
        super().__init__(message)
        self.message = message
        self.partial_result = partial_result


class NoQuestionsError(Exception):
    """Raised when the image contains no detectable STEM questions."""


# ── Helpers ───────────────────────────────────────────────────────────────────

_LATEX_PLAIN_PATTERNS: list[tuple[str, str]] = [
    (r"\\frac\{([^}]+)\}\{([^}]+)\}", r"\1 divided by \2"),
    (r"\\int_\{([^}]+)\}\^\{([^}]+)\}", r"integral from \1 to \2 of"),
    (r"\\int", "integral of"),
    (r"\\frac\{d\}\{d([^}]+)\}", r"differentiate with respect to \1"),
    (r"\\frac\{d([^}]+)\}\{d([^}]+)\}", r"derivative of \1 with respect to \2"),
    (r"\\sum_\{([^}]+)\}\^\{([^}]+)\}", r"sum from \1 to \2"),
    (r"\\lim_\{([^}]+)\}", r"limit as \1"),
    (r"\\sqrt\{([^}]+)\}", r"square root of \1"),
    (r"\\sin", "sin"),
    (r"\\cos", "cos"),
    (r"\\tan", "tan"),
    (r"\\ln", "ln"),
    (r"\\log", "log"),
    (r"\\infty", "infinity"),
    (r"\\cdot", "times"),
    (r"\\times", "times"),
    (r"\\pm", "plus or minus"),
    (r"\^2", " squared"),
    (r"\^3", " cubed"),
    (r"\^\{([^}]+)\}", r" to the power \1"),
    (r"[{}]", ""),
    (r"\\", " "),
]


def latex_to_plain(latex: str) -> str:
    """Convert common LaTeX patterns to human-readable English."""
    result = latex
    for pattern, replacement in _LATEX_PLAIN_PATTERNS:
        result = re.sub(pattern, replacement, result)
    return re.sub(r"\s+", " ", result).strip()


def _resize_thumbnail(image_bytes: bytes, max_side: int = 512) -> bytes:
    """Downscale image for cheap Gemini triage calls."""
    try:
        import cv2
        import numpy as np

        arr = np.frombuffer(image_bytes, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            return image_bytes
        h, w = img.shape[:2]
        if max(h, w) <= max_side:
            return image_bytes
        scale = max_side / max(h, w)
        img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
        _, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 75])
        return buf.tobytes()
    except Exception:
        return image_bytes


def _strip_json_fence(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
    text = re.sub(r"```$", "", text).strip()
    return text


# ── Abstract base ─────────────────────────────────────────────────────────────


class BaseImageParser(ABC):
    @classmethod
    @abstractmethod
    def is_available(cls) -> bool:
        ...

    @abstractmethod
    async def parse(self, image_bytes: bytes, preprocessed_bytes: bytes) -> ParseResult:
        ...


# ── Gemini Vision parser ──────────────────────────────────────────────────────

_TRIAGE_PROMPT = (
    'Analyze this image and return ONLY a valid JSON object with exactly these fields:\n'
    '{\n'
    '  "type": "handwritten" | "printed_latex" | "printed_text" | "mixed",\n'
    '  "question_count": <integer>,\n'
    '  "has_diagrams": <boolean>,\n'
    '  "confidence": <float 0-1>\n'
    '}\n'
    'Return nothing except the JSON. No explanation, no markdown, no backticks.'
)

_EXTRACTION_PROMPT = (
    'You are a precision math OCR engine for a STEM tutoring platform. '
    'Your job is to extract every math and science question from this image with zero errors.\n\n'
    'RULES:\n'
    '1. Return ONLY a valid JSON object. No explanation. No markdown. No backticks.\n'
    '2. Write all mathematical expressions in LaTeX notation.\n'
    '3. Number questions sequentially starting from 1.\n'
    '4. Treat each sub-part (a, b, c) as a separate question with id like "1a", "1b".\n'
    '5. If a diagram accompanies a question, describe it in plain English after the equation text.\n'
    '6. Never hallucinate. If you cannot read part of the expression, use [UNCLEAR] as a placeholder.\n'
    '7. subject_hint must be one of: "algebra", "calculus", "trigonometry", "statistics", '
    '"physics", "chemistry", "linear_algebra", "differential_equations"\n\n'
    'OUTPUT FORMAT:\n'
    '{\n'
    '  "questions": [\n'
    '    {\n'
    '      "id": "1",\n'
    '      "text": "Solve x squared minus 5x plus 6 equals 0",\n'
    '      "latex": "x^2 - 5x + 6 = 0",\n'
    '      "subject_hint": "algebra",\n'
    '      "has_diagram": false,\n'
    '      "diagram_description": null\n'
    '    }\n'
    '  ],\n'
    '  "overall_confidence": 0.97\n'
    '}'
)

_EXTRACTION_PROMPT_RETRY = (
    'You are a precision math OCR engine. Some parts of this image were unclear in a previous pass — '
    'focus especially on reconstructing equations that appear smudged or partially obscured. '
    'Apply extra scrutiny to any handwritten notation.\n\n'
    'RULES:\n'
    '1. Return ONLY a valid JSON object. No explanation. No markdown. No backticks.\n'
    '2. Write all mathematical expressions in LaTeX notation.\n'
    '3. Number questions sequentially starting from 1.\n'
    '4. Treat each sub-part (a, b, c) as a separate question with id like "1a", "1b".\n'
    '5. If a portion is truly unreadable, use [UNCLEAR] as a placeholder.\n'
    '6. subject_hint must be one of: "algebra", "calculus", "trigonometry", "statistics", '
    '"physics", "chemistry", "linear_algebra", "differential_equations"\n\n'
    'OUTPUT FORMAT:\n'
    '{\n'
    '  "questions": [\n'
    '    {\n'
    '      "id": "1",\n'
    '      "text": "Solve x squared minus 5x plus 6 equals 0",\n'
    '      "latex": "x^2 - 5x + 6 = 0",\n'
    '      "subject_hint": "algebra",\n'
    '      "has_diagram": false,\n'
    '      "diagram_description": null\n'
    '    }\n'
    '  ],\n'
    '  "overall_confidence": 0.97\n'
    '}'
)


class GeminiVisionParser(BaseImageParser):
    _model = None

    @classmethod
    def is_available(cls) -> bool:
        return bool(settings.GEMINI_API_KEY or os.getenv("GOOGLE_API_KEY"))

    def _get_model(self):
        if not self.is_available():
            raise RuntimeError("Gemini vision is not configured.")
        if GeminiVisionParser._model is None:
            import google.generativeai as genai

            api_key = settings.GEMINI_API_KEY or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
            genai.configure(api_key=api_key)
            GeminiVisionParser._model = genai.GenerativeModel("gemini-1.5-pro")
        return GeminiVisionParser._model

    async def triage(self, thumbnail_bytes: bytes) -> _TriageResult:
        def _sync() -> _TriageResult:
            model = self._get_model()
            response = model.generate_content(
                [{"mime_type": "image/jpeg", "data": thumbnail_bytes}, _TRIAGE_PROMPT]
            )
            data = json.loads(_strip_json_fence(response.text))
            return _TriageResult(
                type=data.get("type", "printed_text"),
                question_count=int(data.get("question_count", 1)),
                has_diagrams=bool(data.get("has_diagrams", False)),
                confidence=float(data.get("confidence", 0.5)),
            )

        return await asyncio.to_thread(_sync)

    async def parse(self, image_bytes: bytes, preprocessed_bytes: bytes) -> ParseResult:
        return await self._extract(preprocessed_bytes, _EXTRACTION_PROMPT)

    async def parse_retry(self, image_bytes: bytes, preprocessed_bytes: bytes) -> ParseResult:
        return await self._extract(preprocessed_bytes, _EXTRACTION_PROMPT_RETRY)

    async def _extract(self, image_bytes: bytes, prompt: str) -> ParseResult:
        def _sync() -> dict:
            model = self._get_model()
            response = model.generate_content(
                [{"mime_type": "image/png", "data": image_bytes}, prompt]
            )
            return json.loads(_strip_json_fence(response.text))

        data = await asyncio.to_thread(_sync)

        questions_raw = data.get("questions", [])
        overall_confidence = float(data.get("overall_confidence", 0.5))

        unclear_hits = sum(
            q.get("text", "").count("[UNCLEAR]") + q.get("latex", "").count("[UNCLEAR]")
            for q in questions_raw
        )
        confidence = max(0.0, overall_confidence - 0.1 * unclear_hits)

        return ParseResult(
            questions=[q.get("text", "") for q in questions_raw],
            latex_versions=[q.get("latex", "") for q in questions_raw],
            engine_used="gemini",
            confidence=confidence,
            subject_hints=[q.get("subject_hint", "algebra") for q in questions_raw],
            raw_output=json.dumps(data),
        )


# ── pix2tex parser ────────────────────────────────────────────────────────────


class Pix2texParser(BaseImageParser):
    _model = None

    @classmethod
    def is_available(cls) -> bool:
        try:
            from pix2tex.cli import LatexOCR  # noqa: F401
        except Exception:
            return False
        return True

    def _get_model(self):
        if Pix2texParser._model is None:
            from pix2tex.cli import LatexOCR

            Pix2texParser._model = LatexOCR()
        return Pix2texParser._model

    async def parse(self, image_bytes: bytes, preprocessed_bytes: bytes) -> ParseResult:
        def _sync() -> str:
            from PIL import Image

            model = self._get_model()
            pil_img = Image.open(io.BytesIO(preprocessed_bytes)).convert("RGB")
            return model(pil_img)

        latex = await asyncio.to_thread(_sync)
        plain = latex_to_plain(latex)

        return ParseResult(
            questions=[plain],
            latex_versions=[latex],
            engine_used="pix2tex",
            confidence=0.75,
            subject_hints=["algebra"],
            raw_output=latex,
        )


# ── Tesseract parser ──────────────────────────────────────────────────────────


class TesseractParser(BaseImageParser):
    @classmethod
    def is_available(cls) -> bool:
        try:
            import pytesseract

            pytesseract.get_tesseract_version()
        except Exception:
            return False
        return True

    async def parse(self, image_bytes: bytes, preprocessed_bytes: bytes) -> ParseResult:
        def _sync() -> tuple[str, float]:
            import pytesseract
            from PIL import Image

            pil_img = Image.open(io.BytesIO(preprocessed_bytes))
            data = pytesseract.image_to_data(
                pil_img,
                config="--psm 6",
                output_type=pytesseract.Output.DICT,
            )

            valid_confs = [
                int(c)
                for c in data["conf"]
                if str(c).lstrip("-").isdigit() and int(c) >= 0
            ]
            avg_conf = sum(valid_confs) / len(valid_confs) if valid_confs else 0.0

            lines: dict[int, list[str]] = {}
            for i, word in enumerate(data["text"]):
                if not str(word).strip():
                    continue
                lines.setdefault(data["line_num"][i], []).append(str(word))

            text_lines = [
                " ".join(ws)
                for ws in lines.values()
                if len(" ".join(ws)) >= 3
            ]
            return "\n".join(text_lines), avg_conf

        full_text, avg_conf = await asyncio.to_thread(_sync)

        confidence = (avg_conf / 100.0) if avg_conf >= 60 else 0.4
        questions = [ln for ln in full_text.splitlines() if ln.strip()] or [full_text]

        return ParseResult(
            questions=questions,
            latex_versions=[""] * len(questions),
            engine_used="tesseract",
            confidence=confidence,
            subject_hints=["algebra"] * len(questions),
            raw_output=full_text,
        )


# ── Singleton instances ───────────────────────────────────────────────────────

_gemini = GeminiVisionParser()
_pix2tex = Pix2texParser()
_tesseract = TesseractParser()


def parser_capabilities() -> dict[str, bool]:
    return {
        "gemini": GeminiVisionParser.is_available(),
        "pix2tex": Pix2texParser.is_available(),
        "tesseract": TesseractParser.is_available(),
    }


def _available_local_parsers() -> list[BaseImageParser]:
    parsers: list[BaseImageParser] = []
    if TesseractParser.is_available():
        parsers.append(_tesseract)
    if Pix2texParser.is_available():
        parsers.append(_pix2tex)
    return parsers


def _fallback_local_triage() -> _TriageResult:
    return _TriageResult(type="printed_text", question_count=1, has_diagrams=False, confidence=0.3)


# ── Orchestrator ──────────────────────────────────────────────────────────────


async def route_and_parse(image_bytes: bytes) -> ParseResult:
    """
    Triage the image, route to the best OCR engine, and fall back to Gemini
    if the primary engine scores below the confidence threshold.

    Raises:
        LowConfidenceError: Both engines scored < 0.70; partial result attached.
        NoQuestionsError: No STEM questions detected.
        ImagePreprocessError: Preprocessing failed entirely.
    """
    capabilities = parser_capabilities()
    if not any(capabilities.values()):
        raise AIServiceError(
            "Image parsing is unavailable. Configure Gemini or install local OCR dependencies.",
            provider="image_ocr",
        )

    thumbnail_bytes = _resize_thumbnail(image_bytes, max_side=512)

    if capabilities["gemini"]:
        try:
            triage = await _gemini.triage(thumbnail_bytes)
        except Exception as exc:
            logger.error("triage_failed_defaulting_to_fallback", error=str(exc))
            triage = _TriageResult(type="mixed", question_count=1, has_diagrams=False, confidence=0.5)
    else:
        triage = _fallback_local_triage()

    route_hint = "handwritten" if triage.type in {"handwritten", "mixed"} else "printed"
    preprocessed_bytes = preprocess_image(image_bytes, route_hint=route_hint)

    use_gemini_retry = False
    if capabilities["gemini"] and (triage.type in {"handwritten", "mixed"} or triage.has_diagrams):
        primary: BaseImageParser = _gemini
        fallback: BaseImageParser | None = None
        use_gemini_retry = True
    elif triage.type == "printed_latex" and capabilities["pix2tex"]:
        primary = _pix2tex
        fallback = _gemini if capabilities["gemini"] else _tesseract if capabilities["tesseract"] else None
    else:
        local_parsers = _available_local_parsers()
        if not local_parsers:
            primary = _gemini
            fallback = None
        else:
            primary = local_parsers[0]
            fallback = None
            if capabilities["gemini"]:
                fallback = _gemini
            elif len(local_parsers) > 1:
                fallback = local_parsers[1]

    # Run primary engine
    result: ParseResult | None = None
    try:
        result = await primary.parse(image_bytes, preprocessed_bytes)
    except Exception as exc:
        logger.warning("primary_engine_failed", engine=type(primary).__name__, error=str(exc))

    # Fallback if primary failed or confidence is low
    if result is None or result.confidence < _CONFIDENCE_THRESHOLD:
        partial = result
        try:
            if use_gemini_retry:
                result = await _gemini.parse_retry(image_bytes, preprocessed_bytes)
            elif fallback is not None:
                result = await fallback.parse(image_bytes, preprocessed_bytes)
        except Exception as exc:
            logger.warning("fallback_engine_failed", error=str(exc))
            result = None

        if result is None or result.confidence < _CONFIDENCE_THRESHOLD:
            low_result = result or partial or ParseResult(
                questions=[], latex_versions=[], engine_used="none",
                confidence=0.0, subject_hints=[], raw_output="",
            )
            raise LowConfidenceError(
                message="Could not read this image clearly.",
                partial_result=low_result,
            )

    if result.question_count == 0:
        raise NoQuestionsError("No math questions detected in this image.")

    logger.info(
        "image_parsed",
        engine=result.engine_used,
        confidence=result.confidence,
        question_count=result.question_count,
    )
    return result
