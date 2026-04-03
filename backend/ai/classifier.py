"""
AI — Problem Classifier

Classifies incoming problems by subject category and complexity level.
This determines which model the router selects, directly impacting
cost, quality, and latency.

Categories:
  MATH      → DeepSeek R1 (reasoning specialist)
  CODING    → Mistral Codestral (code specialist)
  REASONING → OpenAI GPT-4o (general reasoning)
  PHYSICS   → DeepSeek R1
  CHEMISTRY → DeepSeek R1
  GENERAL   → Gemini Flash (cheapest)
  IMAGE     → OpenAI GPT-4o (vision)

Complexity levels:
  LOW    → use cheaper/faster models
  MEDIUM → standard model
  HIGH   → use premium model tier
"""

import re
from enum import Enum
from dataclasses import dataclass
import structlog

logger = structlog.get_logger("equated.ai.classifier")


class SubjectCategory(str, Enum):
    MATH = "math"
    PHYSICS = "physics"
    CHEMISTRY = "chemistry"
    CODING = "coding"
    REASONING = "reasoning"
    GENERAL = "general"
    IMAGE = "image"


class ComplexityLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass
class Classification:
    """Result of classifying a problem."""
    subject: SubjectCategory
    complexity: ComplexityLevel
    confidence: float = 0.9
    tokens_est: int = 0          # Estimated output tokens needed
    needs_steps: bool = True     # Whether to show step-by-step


# ── Keyword Patterns ────────────────────────────────

MATH_PATTERNS = [
    r"\b(solve|equation|integral|derivative|differentiate|integrate|factor|simplify|expand)\b",
    r"\b(matrix|determinant|eigenvalue|eigenvector|polynomial|quadratic|cubic)\b",
    r"\b(limit|series|convergence|divergence|taylor|maclaurin|fourier)\b",
    r"\b(probability|permutation|combination|binomial|poisson|normal distribution)\b",
    r"\b(algebra|calculus|geometry|trigonometry|logarithm|exponential)\b",
    r"\b(x\s*[\+\-\*\/\^=]|y\s*=|f\(x\)|g\(x\))\b",
    r"[\d]+\s*[\+\-\*\/\^]\s*[\d]+",
    r"\b(prove|proof|theorem|lemma|corollary)\b",
    r"\b(sqrt|sin|cos|tan|log|ln|exp)\b",
]

PHYSICS_PATTERNS = [
    r"\b(force|velocity|acceleration|momentum|kinetic|potential)\b",
    r"\b(gravity|friction|torque|angular|circular motion)\b",
    r"\b(electric|magnetic|field|charge|voltage|current|resistance)\b",
    r"\b(wave|frequency|wavelength|amplitude|photon|quantum)\b",
    r"\b(thermodynamics|entropy|heat|temperature|pressure)\b",
    r"\b(gauss'?s?\s+law|faraday'?s?\s+law|ampere'?s?\s+law|coulomb'?s?\s+law|ohm'?s?\s+law|lorentz force|maxwell'?s?\s+equations?)\b",
    r"\b(newton|joule|watt|pascal|hertz|coulomb|tesla)\b",
    r"\b(m/s|m/s²|kg|N|J|W|Pa|Hz|C|T|Ω)\b",
]

CHEMISTRY_PATTERNS = [
    r"\b(molecule|atom|ion|electron|proton|neutron)\b",
    r"\b(bond|covalent|ionic|metallic|hydrogen bond)\b",
    r"\b(reaction|oxidation|reduction|acid|base|pH|pKa)\b",
    r"\b(mole|molarity|concentration|dilution|stoichiometry)\b",
    r"\b(organic|inorganic|polymer|compound|element)\b",
    r"\b(H₂O|CO₂|NaCl|HCl|NaOH|H₂SO₄)\b",
]

CODING_PATTERNS = [
    r"\b(code|program|function|algorithm|implement|debug|refactor)\b",
    r"\b(python|javascript|typescript|java|cpp|rust|golang|ruby)\b",
    r"\b(array|linked list|tree|graph|hash|stack|queue|heap)\b",
    r"\b(sort|search|traverse|recursion|dynamic programming)\b",
    r"\b(api|database|sql|query|regex|parse|compile)\b",
    r"\b(class|method|variable|loop|conditional|exception)\b",
    r"\b(big\s*o|time complexity|space complexity)\b",
    r"```\w*\n",  # Code blocks
    r"\b(def |import |from |print\(|console\.log|System\.out)\b",
]

REASONING_PATTERNS = [
    r"\b(why|explain|analyze|compare|contrast|evaluate|assess)\b",
    r"\b(argument|logic|fallacy|premise|conclusion|deduce|infer)\b",
    r"\b(critical thinking|reasoning|hypothesis|evidence)\b",
    r"\b(essay|write about|discuss|elaborate|opinion)\b",
]

# ── Complexity Indicators ───────────────────────────

HIGH_COMPLEXITY_MARKERS = [
    r"\bprove\b",
    r"\bderive\b",
    r"\beigenvalue\b",
    r"\bfourier\b",
    r"\bdifferential equation\b",
    r"\bpartial derivative\b",
    r"\bmultivariable\b",
    r"\btensor\b",
    r"\blaplace\b",
    r"\bstochastic\b",
    r"\bdynamic programming\b",
    r"\bNP[-\s]?(hard|complete)\b",
    r"\brecurrence relation\b",
    r"\bquantum\b",
]

LOW_COMPLEXITY_MARKERS = [
    r"\b\d+\s*[\+\-\*\/]\s*\d+\b",      # Simple arithmetic
    r"\bwhat is\b",
    r"\bdefine\b",
    r"\bhello\b",
    r"\bthanks?\b",
    r"\bhi\b",
]


class ProblemClassifier:
    """
    Classifies problems by subject and complexity using keyword matching.
    Optimized for speed (no AI call) so it can run before every model request.
    """

    def classify(self, text: str, has_image: bool = False) -> Classification:
        """Classify a problem from its text."""
        if has_image:
            return Classification(
                subject=SubjectCategory.IMAGE,
                complexity=ComplexityLevel.MEDIUM,
                tokens_est=2000,
                needs_steps=True,
            )

        text_lower = text.lower()

        # Count category matches
        scores = {
            SubjectCategory.MATH:      self._count_matches(text_lower, MATH_PATTERNS),
            SubjectCategory.PHYSICS:   self._count_matches(text_lower, PHYSICS_PATTERNS),
            SubjectCategory.CHEMISTRY: self._count_matches(text_lower, CHEMISTRY_PATTERNS),
            SubjectCategory.CODING:    self._count_matches(text_lower, CODING_PATTERNS),
            SubjectCategory.REASONING: self._count_matches(text_lower, REASONING_PATTERNS),
        }

        # Pick highest scoring category
        max_score = max(scores.values())
        if max_score == 0:
            subject = SubjectCategory.GENERAL
            confidence = 0.5
        else:
            subject = max(scores, key=lambda k: scores[k])
            total = sum(scores.values())
            confidence = float(f"{max_score / total:.2f}") if total > 0 else 0.5

        # Determine complexity
        complexity = self._assess_complexity(text_lower)

        # Estimate tokens needed
        tokens_est = self._estimate_tokens(subject, complexity)

        logger.debug(
            "classified",
            subject=subject.value,
            complexity=complexity.value,
            confidence=confidence,
            scores={k.value: v for k, v in scores.items()},
        )

        return Classification(
            subject=subject,
            complexity=complexity,
            confidence=confidence,
            tokens_est=tokens_est,
            needs_steps=(subject != SubjectCategory.GENERAL),
        )

    def _count_matches(self, text: str, patterns: list[str]) -> int:
        count = 0
        for pattern in patterns:
            count += len(re.findall(pattern, text, re.IGNORECASE))
        return count

    def _assess_complexity(self, text: str) -> ComplexityLevel:
        high_markers = sum(1 for p in HIGH_COMPLEXITY_MARKERS if re.search(p, text, re.IGNORECASE))
        low_markers = sum(1 for p in LOW_COMPLEXITY_MARKERS if re.search(p, text, re.IGNORECASE))

        if high_markers >= 2:
            return ComplexityLevel.HIGH
        if high_markers >= 1 and len(text) > 200:
            return ComplexityLevel.HIGH
        if low_markers >= 2 and len(text) < 100:
            return ComplexityLevel.LOW
        return ComplexityLevel.MEDIUM

    def _estimate_tokens(self, subject: SubjectCategory, complexity: ComplexityLevel) -> int:
        base = {
            SubjectCategory.MATH: 2000,
            SubjectCategory.PHYSICS: 2000,
            SubjectCategory.CHEMISTRY: 1800,
            SubjectCategory.CODING: 2500,
            SubjectCategory.REASONING: 1500,
            SubjectCategory.GENERAL: 800,
            SubjectCategory.IMAGE: 2000,
        }
        multiplier = {
            ComplexityLevel.LOW: 0.5,
            ComplexityLevel.MEDIUM: 1.0,
            ComplexityLevel.HIGH: 2.0,
        }
        return int(base.get(subject, 1000) * multiplier.get(complexity, 1.0))


# Singleton
classifier = ProblemClassifier()
