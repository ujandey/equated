"""
Services — Math Intent Detector

Detects whether user input has genuine mathematical intent before
engaging the expensive parser + verification pipeline.

If is_math_like() returns False:
  → skip parser, skip verification
  → return verified=False, overall_confidence=LOW, method="none"

This prevents:
  - Wasting LLM calls on greetings ("hello", "thanks")
  - False-positive verification on prose questions
  - Returning misleading confidence scores for non-math queries
"""

import re
import structlog

logger = structlog.get_logger("equated.services.math_intent")

# ── Positive signals: mathematical content ──────────────────
MATH_SYMBOL_PATTERN = re.compile(
    r"[+\-*/=^∫∑∏∂∇√∞≈≠≤≥±×÷]"
)

MATH_FUNCTION_PATTERN = re.compile(
    r"\b(sin|cos|tan|cot|sec|csc|arcsin|arccos|arctan|"
    r"sinh|cosh|tanh|"
    r"log|ln|exp|sqrt|abs|"
    r"lim|limit|"
    r"det|trace|rank|"
    r"gcd|lcm|mod|floor|ceil)\b",
    re.IGNORECASE,
)

MATH_KEYWORD_PATTERN = re.compile(
    r"\b(solve|integrate|differentiate|derive|derivative|integral|"
    r"simplify|expand|factor|evaluate|calculate|compute|"
    r"equation|inequality|polynomial|quadratic|cubic|"
    r"matrix|determinant|eigenvalue|eigenvector|"
    r"probability|permutation|combination|"
    r"limit|series|convergence|divergence|"
    r"prove|proof|theorem|lemma|"
    r"vector|scalar|magnitude|"
    r"graph|plot|function|domain|range|"
    r"area|volume|perimeter|circumference|"
    r"velocity|acceleration|force|momentum|"
    r"molarity|stoichiometry|oxidation|reduction|"
    r"enthalpy|entropy|gibbs)\b",
    re.IGNORECASE,
)

# Numbers followed by variables (e.g., "2x", "3y^2")
ALGEBRAIC_TERM_PATTERN = re.compile(
    r"\d+\s*[a-zA-Z]|\b[a-zA-Z]\s*[+\-*/^=]\s*\d"
)

# Equation-like patterns (e.g., "x^2 + 3x = 5")
EQUATION_PATTERN = re.compile(
    r"[a-zA-Z]\s*[+\-*/^]\s*\d|"  # variable op number
    r"\d\s*[+\-*/^]\s*[a-zA-Z]|"  # number op variable
    r"=\s*\d|"                     # = something
    r"\d\s*=",                     # something =
    re.IGNORECASE,
)

# Code patterns (should be sent to AI, but not math parser)
CODE_PATTERN = re.compile(
    r"\b(def |import |class |function |const |let |var |print\(|console\.log)\b"
)

# ── Negative signals: definitely NOT math ──────────────────
NON_MATH_PATTERN = re.compile(
    r"^(hi|hello|hey|thanks?|thank you|bye|goodbye|good morning|"
    r"good evening|how are you|what\'s up|sup|yo|ok|okay|sure|"
    r"yes|no|please|sorry|help|who are you|what are you)\b",
    re.IGNORECASE,
)


def is_math_like(text: str) -> bool:
    """
    Determine if the input text has genuine mathematical intent.

    Returns True if the text contains mathematical symbols, equations,
    math function names, or STEM keywords. Returns False for greetings,
    pure prose, and ambiguous text without math content.

    This is a fast heuristic check (no AI calls) designed to be
    conservative: when in doubt, return True (prefer false positives
    over false negatives for filtering).
    """
    if not text or len(text.strip()) < 2:
        return False

    stripped = text.strip()

    # ── Quick negative: pure greetings/pleasantries ──
    # Only reject if the greeting isn't followed by math content
    if NON_MATH_PATTERN.match(stripped) and len(stripped) < 50:
        remainder = stripped[NON_MATH_PATTERN.match(stripped).end():]
        has_math_in_remainder = (
            MATH_SYMBOL_PATTERN.search(remainder)
            or ALGEBRAIC_TERM_PATTERN.search(remainder)
            or EQUATION_PATTERN.search(remainder)
            or MATH_FUNCTION_PATTERN.search(remainder)
            or MATH_KEYWORD_PATTERN.search(remainder)
        )
        if not has_math_in_remainder:
            logger.debug("math_intent_negative", reason="greeting_pattern", input_preview=stripped[:60])
            return False

    # ── Quick positive: math symbols present ──
    if MATH_SYMBOL_PATTERN.search(stripped):
        logger.debug("math_intent_positive", reason="math_symbols")
        return True

    # ── Quick positive: algebraic terms ──
    if ALGEBRAIC_TERM_PATTERN.search(stripped):
        logger.debug("math_intent_positive", reason="algebraic_terms")
        return True

    # ── Quick positive: equations ──
    if EQUATION_PATTERN.search(stripped):
        logger.debug("math_intent_positive", reason="equation_pattern")
        return True

    # ── Positive: math functions ──
    if MATH_FUNCTION_PATTERN.search(stripped):
        logger.debug("math_intent_positive", reason="math_functions")
        return True

    # ── Positive: STEM keywords ──
    if MATH_KEYWORD_PATTERN.search(stripped):
        logger.debug("math_intent_positive", reason="stem_keywords")
        return True

    # ── Positive: code (route to AI, not math parser specifically) ──
    if CODE_PATTERN.search(stripped):
        logger.debug("math_intent_positive", reason="code_content")
        return True

    # ── Numeric density check ──
    # If >20% of characters are digits, likely math
    digit_ratio = sum(1 for c in stripped if c.isdigit()) / max(len(stripped), 1)
    if digit_ratio > 0.2:
        logger.debug("math_intent_positive", reason="high_digit_ratio", ratio=round(digit_ratio, 2))
        return True

    # ── Default: not clearly math ──
    logger.debug("math_intent_negative", reason="no_math_signals", input_preview=stripped[:80])
    return False
