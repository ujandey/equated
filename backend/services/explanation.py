"""
Services — Explanation Generator

Converts raw AI output into Equated's structured pedagogical format.
Ensures consistent response structure across all model providers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class StructuredExplanation:
    """Equated's standard explanation format."""
    problem_interpretation: str
    concept_used: str
    steps: list[dict]              # [{"step": 1, "rule": "...", "explanation": "..."}]
    final_answer: str
    quick_summary: str
    alternative_method: str | None = None
    common_mistakes: str | None = None
    latex_expressions: list[str] | None = None


class ExplanationGenerator:
    """
    Transforms raw model output into structured explanations.

    Applies:
      - Section parsing (identify Problem Interpretation, Steps, etc.)
      - LaTeX extraction (collect all math expressions)
      - Format normalization (consistent headings, numbering)
    """

    SECTION_MARKERS = {
        "problem_interpretation": ["problem interpretation", "understanding the problem", "given"],
        "concept_used": ["concept used", "concept:", "formula used", "theorem", "method used", "key concept"],
        "final_answer": ["final answer", "answer:", "result:", "solution:"],
        "quick_summary": ["quick summary", "summary:", "recap:", "in short", "in summary"],
        "alternative_method": ["alternative method", "other method", "another approach"],
        "common_mistakes": ["common mistake", "pitfall", "watch out"],
    }

    def generate(self, raw_output: str, problem: str) -> StructuredExplanation:
        """Parse raw model output into structured format."""
        sections = self._parse_sections(raw_output)
        steps = self._extract_steps(raw_output)
        latex_exprs = self._extract_latex(raw_output)

        return StructuredExplanation(
            problem_interpretation=sections.get("problem_interpretation", problem),
            concept_used=sections.get("concept_used", ""),
            steps=steps,
            final_answer=sections.get("final_answer", ""),
            quick_summary=sections.get("quick_summary", ""),
            alternative_method=sections.get("alternative_method"),
            common_mistakes=sections.get("common_mistakes"),
            latex_expressions=latex_exprs if latex_exprs else None,
        )

    def _parse_sections(self, text: str) -> dict[str, str]:
        """
        Extract named sections from the output.

        Only matches lines that look like headers (start with ##/# or are short bold lines),
        not arbitrary lines that happen to contain a keyword.
        """
        sections: dict[str, str] = {}
        lines = text.split("\n")
        current_section: str | None = None
        current_content: list[str] = []

        _header_re = re.compile(r"^(#{1,4})\s+(.+)$")
        _bold_re = re.compile(r"^\*\*(.+?)\*\*\s*$")

        for line in lines:
            stripped = line.strip()
            if not stripped:
                if current_section:
                    current_content.append(line)
                continue

            # Check if this line is a header (## Header or **Header**)
            header_match = _header_re.match(stripped) or _bold_re.match(stripped)
            if header_match:
                header_text = header_match.group(1) if _header_re.match(stripped) else header_match.group(1)
                # For ## headers, group(2) is the actual text; for ** it's group(1)
                m = _header_re.match(stripped)
                header_text = m.group(2) if m else _bold_re.match(stripped).group(1)
                header_lower = header_text.lower().strip()

                matched_key: str | None = None
                for section_key, markers in self.SECTION_MARKERS.items():
                    if any(marker in header_lower for marker in markers):
                        matched_key = section_key
                        break

                if matched_key:
                    if current_section:
                        sections[current_section] = "\n".join(current_content).strip()
                    current_section = matched_key
                    current_content = []
                    continue
                # It's a header but doesn't match a known section — treat as content
                if current_section:
                    current_content.append(line)
            else:
                if current_section:
                    current_content.append(line)

        if current_section:
            sections[current_section] = "\n".join(current_content).strip()

        return sections

    def _extract_steps(self, text: str) -> list[dict]:
        """
        Extract numbered steps from the output.

        Deduplicates by step number (last definition wins, since LLMs often
        re-mention earlier steps in summaries). Filters out trivially short matches.
        """
        seen: dict[int, dict] = {}
        # Match "Step N:" / "**Step N:**" / "Step N —" etc., capture the rest of the line
        pattern = re.compile(
            r"\*{0,2}Step\s*(\d+)[:\s*→—\-]+\*{0,2}\s*(.+?)(?=\n|$)",
            re.IGNORECASE,
        )
        for match in pattern.finditer(text):
            step_num = int(match.group(1))
            content = match.group(2).strip().rstrip("*").strip()
            # Skip malformed matches that are just punctuation/symbols
            if len(content) < 4:
                continue
            seen[step_num] = {"step": step_num, "rule": "", "explanation": content}

        if not seen:
            return [{"step": 1, "rule": "", "explanation": text.strip()[:500]}]
        return sorted(seen.values(), key=lambda s: s["step"])

    def _extract_latex(self, text: str) -> list[str]:
        """Extract LaTeX expressions ($..$ and $$..$$)."""
        block = re.findall(r"\$\$(.*?)\$\$", text, re.DOTALL)
        inline = re.findall(r"(?<!\$)\$(.*?)\$(?!\$)", text)
        return block + inline


# Singleton
explanation_generator = ExplanationGenerator()
