"""
Services — Explanation Generator

Converts raw AI output into Equated's structured pedagogical format.
Ensures consistent response structure across all model providers.
"""

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
        "concept_used": ["concept", "formula", "theorem", "law", "rule"],
        "final_answer": ["final answer", "answer", "result", "solution"],
        "quick_summary": ["summary", "recap", "in short"],
        "alternative_method": ["alternative", "other method", "another approach"],
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
        """Extract named sections from the output."""
        sections = {}
        lines = text.split("\n")
        current_section = None
        current_content = []

        for line in lines:
            line_lower = line.lower().strip()
            matched = False
            for section_key, markers in self.SECTION_MARKERS.items():
                if any(marker in line_lower for marker in markers):
                    if current_section:
                        sections[current_section] = "\n".join(current_content).strip()
                    current_section = section_key
                    current_content = []
                    matched = True
                    break
            if not matched and current_section:
                current_content.append(line)

        if current_section:
            sections[current_section] = "\n".join(current_content).strip()

        return sections

    def _extract_steps(self, text: str) -> list[dict]:
        """Extract numbered steps from the output."""
        import re
        steps = []
        pattern = r"(?:Step\s*(\d+)|(\d+)[\.\)])\s*[→:—-]*\s*(.*)"
        for match in re.finditer(pattern, text, re.IGNORECASE):
            step_num = match.group(1) or match.group(2)
            content = match.group(3).strip()
            steps.append({
                "step": int(step_num),
                "rule": "",
                "explanation": content,
            })
        return steps if steps else [{"step": 1, "rule": "", "explanation": text.strip()}]

    def _extract_latex(self, text: str) -> list[str]:
        """Extract LaTeX expressions ($..$ and $$..$$)."""
        import re
        block = re.findall(r"\$\$(.*?)\$\$", text, re.DOTALL)
        inline = re.findall(r"(?<!\$)\$(.*?)\$(?!\$)", text)
        return block + inline


# Singleton
explanation_generator = ExplanationGenerator()
