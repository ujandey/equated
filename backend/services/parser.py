"""
Services — Problem Parser

Text/LaTeX normalisation helpers. Image parsing has been moved to
image_parser.py and image_preprocessor.py which provide the full
multi-engine OCR pipeline.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class InputType(str, Enum):
    TEXT = "text"
    IMAGE = "image"
    LATEX = "latex"
    DOCUMENT = "document"


@dataclass
class ParsedProblem:
    """Normalised problem ready for the AI pipeline."""
    original_input: str
    normalized_text: str
    input_type: InputType
    subject_tag: str | None
    latex_expressions: list[str]
    confidence: float


class ProblemParser:
    """
    Text and LaTeX problem parser.

    Image parsing is handled by services.image_parser.route_and_parse().
    """

    def parse(self, text: str = "", input_type: str = "text") -> ParsedProblem:
        if input_type == "latex" or self._contains_latex(text):
            return self._parse_latex(text)
        return self._parse_text(text)

    def _parse_text(self, text: str) -> ParsedProblem:
        cleaned = self._clean(text)
        return ParsedProblem(
            original_input=text,
            normalized_text=cleaned,
            input_type=InputType.TEXT,
            subject_tag=self._detect_subject(cleaned),
            latex_expressions=self._extract_latex(text),
            confidence=0.95,
        )

    def _parse_latex(self, text: str) -> ParsedProblem:
        return ParsedProblem(
            original_input=text,
            normalized_text=text,
            input_type=InputType.LATEX,
            subject_tag="math",
            latex_expressions=self._extract_latex(text),
            confidence=0.9,
        )

    def _clean(self, text: str) -> str:
        return re.sub(r"\s+", " ", text).strip()

    def _contains_latex(self, text: str) -> bool:
        return "$$" in text or "\\frac" in text or "\\int" in text

    def _extract_latex(self, text: str) -> list[str]:
        blocks = re.findall(r"\$\$(.*?)\$\$", text, re.DOTALL)
        inline = re.findall(r"(?<!\$)\$(.*?)\$(?!\$)", text)
        return blocks + inline

    def _detect_subject(self, text: str) -> str | None:
        text_lower = text.lower()
        subjects: dict[str, list[str]] = {
            "math": ["solve", "equation", "integral", "derivative", "matrix"],
            "physics": ["force", "velocity", "energy", "circuit", "wave"],
            "chemistry": ["reaction", "mole", "element", "bond", "pH"],
        }
        for subject, keywords in subjects.items():
            if any(kw in text_lower for kw in keywords):
                return subject
        return None


problem_parser = ProblemParser()
