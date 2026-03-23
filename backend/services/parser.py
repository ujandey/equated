"""
Services — Problem Parser

Normalizes all input formats before routing:
  - Plain text → cleaned text + subject tag
  - Image → OCR (Tesseract) → text
  - LaTeX → parsed expression
  - Document → text extraction
"""

from dataclasses import dataclass
from enum import Enum


class InputType(str, Enum):
    TEXT = "text"
    IMAGE = "image"
    LATEX = "latex"
    DOCUMENT = "document"


@dataclass
class ParsedProblem:
    """Normalized problem ready for the AI pipeline."""
    original_input: str
    normalized_text: str
    input_type: InputType
    subject_tag: str | None
    latex_expressions: list[str]
    confidence: float


class ProblemParser:
    """
    Multi-format problem parser.

    Pipeline:
      1. Detect input type
      2. Extract text (OCR if image)
      3. Parse LaTeX expressions
      4. Normalize and clean
      5. Tag subject area
    """

    def parse(self, text: str = "", image_bytes: bytes | None = None, input_type: str = "text") -> ParsedProblem:
        """Parse any input format into a normalized problem."""
        if input_type == "image" and image_bytes:
            return self._parse_image(image_bytes)
        elif input_type == "latex" or self._contains_latex(text):
            return self._parse_latex(text)
        else:
            return self._parse_text(text)

    def _parse_text(self, text: str) -> ParsedProblem:
        """Parse plain text input."""
        cleaned = self._clean_text(text)
        return ParsedProblem(
            original_input=text,
            normalized_text=cleaned,
            input_type=InputType.TEXT,
            subject_tag=self._detect_subject(cleaned),
            latex_expressions=self._extract_latex(text),
            confidence=0.95,
        )

    def _parse_image(self, image_bytes: bytes) -> ParsedProblem:
        """Parse image input using OCR."""
        try:
            from PIL import Image
            import pytesseract
            import io

            image = Image.open(io.BytesIO(image_bytes))
            text = pytesseract.image_to_string(image)

            # Also try pix2tex for math expressions
            latex_text = self._try_pix2tex(image_bytes)

            combined = text
            latex_exprs = []
            if latex_text:
                combined += f"\n[LaTeX detected: {latex_text}]"
                latex_exprs.append(latex_text)

            return ParsedProblem(
                original_input="[image]",
                normalized_text=self._clean_text(combined),
                input_type=InputType.IMAGE,
                subject_tag=self._detect_subject(combined),
                latex_expressions=latex_exprs,
                confidence=0.75,
            )
        except Exception as e:
            return ParsedProblem(
                original_input="[image]",
                normalized_text=f"[OCR failed: {e}]",
                input_type=InputType.IMAGE,
                subject_tag=None,
                latex_expressions=[],
                confidence=0.0,
            )

    def _parse_latex(self, text: str) -> ParsedProblem:
        """Parse LaTeX input."""
        latex_exprs = self._extract_latex(text)
        return ParsedProblem(
            original_input=text,
            normalized_text=text,
            input_type=InputType.LATEX,
            subject_tag="math",
            latex_expressions=latex_exprs,
            confidence=0.9,
        )

    def __init__(self):
        self._latex_ocr_model = None

    def _get_pix2tex_model(self):
        if self._latex_ocr_model is None:
            try:
                from pix2tex.cli import LatexOCR
                self._latex_ocr_model = LatexOCR()
            except ImportError:
                pass
        return self._latex_ocr_model

    def _try_pix2tex(self, image_bytes: bytes) -> str | None:
        """Attempt to convert image to LaTeX using pix2tex."""
        try:
            from PIL import Image
            import io

            model = self._get_pix2tex_model()
            if not model:
                return None
                
            image = Image.open(io.BytesIO(image_bytes))
            return model(image)
        except Exception:
            return None

    def _clean_text(self, text: str) -> str:
        """Remove noise and normalize whitespace."""
        import re
        text = re.sub(r"\s+", " ", text)
        text = text.strip()
        return text

    def _contains_latex(self, text: str) -> bool:
        """Detect LaTeX in text."""
        return "$$" in text or "\\frac" in text or "\\int" in text

    def _extract_latex(self, text: str) -> list[str]:
        """Extract LaTeX expressions from text."""
        import re
        block = re.findall(r"\$\$(.*?)\$\$", text, re.DOTALL)
        inline = re.findall(r"(?<!\$)\$(.*?)\$(?!\$)", text)
        return block + inline

    def _detect_subject(self, text: str) -> str | None:
        """Simple keyword-based subject detection."""
        text_lower = text.lower()
        subjects = {
            "math": ["solve", "equation", "integral", "derivative", "matrix"],
            "physics": ["force", "velocity", "energy", "circuit", "wave"],
            "chemistry": ["reaction", "mole", "element", "bond", "pH"],
        }
        for subject, keywords in subjects.items():
            if any(kw in text_lower for kw in keywords):
                return subject
        return None


# Singleton
problem_parser = ProblemParser()
