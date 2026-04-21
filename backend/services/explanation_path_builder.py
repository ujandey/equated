"""
Services — Explanation Path Builder

Given a verified SymPy result and a StudentProfile, constructs a fully-scripted
ExplanationScript.  The centrepiece is `llm_prompt`: a complete instruction string
that the controller passes directly to the LLM.

The LLM is told exactly what to explain, what to skip, what tone to use, and
what common errors to flag.  It must narrate the provided solution steps —
it must NOT invent steps.

No external AI API calls.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from services.concept_graph import ConceptGraph
from services.diagnosis_engine import StudentProfile

_TONE_HEADER: dict[str, str] = {
    "encouraging": (
        "You are Equated, a warm and patient AI tutor. "
        "Use a supportive, encouraging tone throughout. "
        "Celebrate small correct steps. "
        "Never make the student feel bad about their mistakes."
    ),
    "efficient": (
        "You are Equated, a concise AI tutor. "
        "Be clear and direct. Avoid padding or repetition. "
        "State each step once."
    ),
    "challenging": (
        "You are Equated, a rigorous AI tutor for advanced students. "
        "Use precise mathematical language. "
        "Do not over-explain basics — focus on the non-trivial parts."
    ),
}


@dataclass
class Segment:
    """One pedagogical unit within an explanation script."""

    type: Literal["remind", "skip", "teach", "flag_error"]
    concept: str
    instruction: str
    max_sentences: int


@dataclass
class ExplanationScript:
    """
    Full teaching script produced by ExplanationPathBuilder.

    Attributes
    ----------
    segments:
        Ordered list of pedagogical instructions for the LLM.
    tone:
        The affective register the LLM should adopt.
    llm_prompt:
        The complete prompt string to send to the LLM.
    """

    segments: list[Segment] = field(default_factory=list)
    tone: Literal["encouraging", "efficient", "challenging"] = "efficient"
    llm_prompt: str = ""


class ExplanationPathBuilder:
    """
    Builds a complete ExplanationScript from a verified solution and student state.

    Segment rules
    -------------
    - Strong prerequisite  → "skip"   (LLM told not to explain it)
    - Weak prerequisite    → "remind" (1-2 sentence recap)
    - Unseen prerequisite  → "teach"  (introduce from scratch)
    - Target topic         → "teach"  (narrate all verified steps)
    - Procedural confusion → "flag_error" for known arithmetic/sign traps
    - Conceptual confusion → "flag_error" clarifying the correct method
    """

    def build(
        self,
        problem: str,
        sympy_result: Any,
        student_profile: StudentProfile,
        concept_graph: ConceptGraph,
    ) -> ExplanationScript:
        """
        Build a complete ExplanationScript.

        Parameters
        ----------
        problem:
            Original problem statement.
        sympy_result:
            SymbolicSolution from symbolic_solver (used for verified steps).
        student_profile:
            Diagnosis output for the current user/topic.
        concept_graph:
            Loaded ConceptGraph instance.
        """
        topic = self._extract_topic(problem, sympy_result, concept_graph)
        # All prereqs (including strong) in topological order — skip segments
        # must appear in the prompt so the LLM knows not to re-explain them.
        all_prereqs = concept_graph.get_prerequisites(topic)
        all_concepts = all_prereqs + ([topic] if topic in concept_graph.nodes else [topic])
        ordered_concepts = concept_graph.topological_sort(all_concepts)
        common_errors = concept_graph.get_common_errors(topic)
        tone = self._select_tone(student_profile)

        segments = self._build_segments(
            topic=topic,
            ordered_concepts=ordered_concepts,
            student_profile=student_profile,
            common_errors=common_errors,
        )

        llm_prompt = self._build_llm_prompt(
            problem=problem,
            sympy_result=sympy_result,
            segments=segments,
            tone=tone,
            student_profile=student_profile,
        )

        return ExplanationScript(segments=segments, tone=tone, llm_prompt=llm_prompt)

    # ------------------------------------------------------------------ #
    # Topic inference                                                      #
    # ------------------------------------------------------------------ #

    def _extract_topic(
        self,
        problem: str,
        sympy_result: Any,
        concept_graph: ConceptGraph,
    ) -> str:
        """
        Infer the concept graph topic id from the SymPy operation or problem text.

        Attempts:
        1. Map operation names to known concept graph node ids.
        2. Keyword scan of the problem string against node labels.
        3. Fallback to a normalised slug of the first 60 chars.
        """
        op_map: dict[str, str] = {
            "solve": "linear_equations",
            "solve_quadratic": "quadratics",
            "differentiate": "derivatives",
            "integrate": "integrals",
            "limit": "limits",
            "factor": "factoring",
            "simplify": "polynomials",
            "expand": "polynomials",
        }
        try:
            operation = sympy_result.request.operation.lower()
            if operation in op_map and op_map[operation] in concept_graph.nodes:
                return op_map[operation]
        except AttributeError:
            pass

        # Keyword scan against node labels
        lower_problem = problem.lower()
        for node_id, node in concept_graph.nodes.items():
            label_words = node.get("label", "").lower().split()
            if any(word in lower_problem for word in label_words if len(word) > 4):
                return node_id

        return problem.strip()[:60].lower().replace(" ", "_")

    # ------------------------------------------------------------------ #
    # Tone selection                                                       #
    # ------------------------------------------------------------------ #

    def _select_tone(
        self, profile: StudentProfile
    ) -> Literal["encouraging", "efficient", "challenging"]:
        """
        encouraging: low confidence or ≥ 3 weak topics.
        challenging:  strong topics dominate (strong > 2× weak) and confidence > 0.7.
        efficient:    default.
        """
        if profile.confidence < 0.4 or len(profile.weak) >= 3:
            return "encouraging"
        if len(profile.strong) > len(profile.weak) * 2 and profile.confidence > 0.7:
            return "challenging"
        return "efficient"

    # ------------------------------------------------------------------ #
    # Segment construction                                                 #
    # ------------------------------------------------------------------ #

    def _build_segments(
        self,
        topic: str,
        ordered_concepts: list[str],
        student_profile: StudentProfile,
        common_errors: list[str],
    ) -> list[Segment]:
        strong_set = set(student_profile.strong)
        weak_set = set(student_profile.weak)
        unseen_set = set(student_profile.unseen)
        segments: list[Segment] = []

        for concept in ordered_concepts:
            if concept == topic:
                segments.append(
                    Segment(
                        type="teach",
                        concept=concept,
                        instruction=(
                            f"Teach the core concept of '{concept}'. "
                            "Narrate every verified step provided below. "
                            "Do NOT invent additional steps."
                        ),
                        max_sentences=6,
                    )
                )
            elif concept in strong_set:
                segments.append(
                    Segment(
                        type="skip",
                        concept=concept,
                        instruction=f"Student already knows '{concept}'. Do NOT explain it.",
                        max_sentences=0,
                    )
                )
            elif concept in weak_set:
                segments.append(
                    Segment(
                        type="remind",
                        concept=concept,
                        instruction=f"Briefly remind the student about '{concept}' in 1–2 sentences.",
                        max_sentences=2,
                    )
                )
            elif concept in unseen_set:
                segments.append(
                    Segment(
                        type="teach",
                        concept=concept,
                        instruction=f"Introduce '{concept}' clearly before using it.",
                        max_sentences=3,
                    )
                )
            else:
                # Seen but neither strongly known nor weak — partial mastery.
                segments.append(
                    Segment(
                        type="remind",
                        concept=concept,
                        instruction=(
                            f"Briefly mention '{concept}' — "
                            "student has some familiarity but may need a quick refresh."
                        ),
                        max_sentences=2,
                    )
                )

        # Append error-flag segments at the end.
        if student_profile.confusion_type == "procedural" and common_errors:
            for err in common_errors[:2]:
                segments.append(
                    Segment(
                        type="flag_error",
                        concept=topic,
                        instruction=f"Warn: common computational trap — {err}",
                        max_sentences=1,
                    )
                )
        elif student_profile.confusion_type == "conceptual":
            segments.append(
                Segment(
                    type="flag_error",
                    concept=topic,
                    instruction=(
                        "Clarify the correct method — "
                        "the student may be applying the wrong approach. "
                        "Explain WHY the correct approach works."
                    ),
                    max_sentences=2,
                )
            )

        return segments

    # ------------------------------------------------------------------ #
    # LLM prompt construction                                             #
    # ------------------------------------------------------------------ #

    def _build_llm_prompt(
        self,
        problem: str,
        sympy_result: Any,
        segments: list[Segment],
        tone: Literal["encouraging", "efficient", "challenging"],
        student_profile: StudentProfile,
    ) -> str:
        """
        Build the complete prompt string to hand to the LLM.

        The LLM receives a script — it narrates the verified solution following
        the segment instructions precisely.  It must not invent steps.
        """
        lines: list[str] = []

        lines.append(_TONE_HEADER[tone])
        lines.append("")

        lines.append("═══ HARD CONSTRAINTS (follow exactly) ═══")
        lines.append(
            "1. Do NOT invent, modify, or reorder the mathematical steps. "
            "Narrate ONLY the steps listed under VERIFIED SOLUTION below."
        )
        lines.append("2. TEACH segments: explain fully using the provided steps.")
        lines.append("3. SKIP segments: do NOT mention or explain the concept.")
        lines.append("4. REMIND segments: use AT MOST the specified sentence limit.")
        lines.append(
            "5. FLAG_ERROR segments: insert the warning near the relevant step, once."
        )
        lines.append("")

        lines.append(f"PROBLEM: {problem.strip()}")
        lines.append("")

        lines.append("VERIFIED SOLUTION (narrate these — do not alter):")
        steps_extracted = False
        try:
            math_result = sympy_result.math_result
            if math_result and math_result.steps:
                for i, step in enumerate(math_result.steps, 1):
                    lines.append(f"  Step {i}: {step}")
                steps_extracted = True
            if math_result and math_result.result:
                lines.append(f"  Final answer: {math_result.result}")
        except AttributeError:
            pass
        if not steps_extracted:
            lines.append(
                "  (Detailed steps unavailable — narrate the conceptual approach only.)"
            )
        lines.append("")

        lines.append("EXPLANATION SCRIPT (execute in order):")
        for seg in segments:
            tag = seg.type.upper()
            limit_note = (
                f" (max {seg.max_sentences} sentence{'s' if seg.max_sentences != 1 else ''})"
                if seg.max_sentences > 0
                else ""
            )
            lines.append(f"  [{tag}] {seg.concept}{limit_note}: {seg.instruction}")
        lines.append("")

        if student_profile.weak:
            lines.append(
                "STUDENT WEAK AREAS: "
                + ", ".join(student_profile.weak[:5])
                + " — go carefully on these."
            )
        if student_profile.confusion_type != "unknown":
            lines.append(
                f"DETECTED CONFUSION TYPE: {student_profile.confusion_type} "
                "— adjust emphasis accordingly."
            )
        lines.append("")

        lines.append(f"TONE: {tone.upper()}")
        lines.append(
            "Write the complete explanation now, following the script above precisely."
        )

        return "\n".join(lines)


explanation_path_builder = ExplanationPathBuilder()
