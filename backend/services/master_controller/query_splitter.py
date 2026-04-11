from __future__ import annotations

import re
from dataclasses import dataclass, field

from services.math_intent_detector import is_math_like
from services.master_controller.teaching_policy import teaching_policy_engine


_CLAUSE_SPLIT_RE = re.compile(r"(?:\s*,\s*then\s+|\s+and\s+|\s+also\s+|\s+then\s+)", re.IGNORECASE)
_SOLVE_RE = re.compile(r"\b(solve|find|compute|calculate|differentiate|derive|integrate|evaluate|simplify|limit)\b", re.IGNORECASE)
_EXPLAIN_RE = re.compile(r"\b(explain|describe|teach|what is|why|how|intuition|overview|summarize|justify)\b", re.IGNORECASE)
_CHECK_RE = re.compile(r"\b(check|verify|confirm|validate|proofread)\b", re.IGNORECASE)
_QUERY_RE = re.compile(r"\b(compare|contrast|relate|connect)\b", re.IGNORECASE)
_EXECUTION_MODIFIER_RE = re.compile(r"\b(step by step|show all steps|show the steps|each step|in detail|detailed|briefly|brief explanation|concise|short answer)\b", re.IGNORECASE)
_DETAILED_RE = re.compile(r"\b(in detail|detailed|show all steps|show the steps|each step)\b", re.IGNORECASE)
_STEP_BY_STEP_RE = re.compile(r"\b(step by step)\b", re.IGNORECASE)
_BRIEF_RE = re.compile(r"\b(briefly|brief explanation|concise|short answer)\b", re.IGNORECASE)
_SUPPORTING_REFERENCE_RE = re.compile(r"\b(the method|this method|the result|that result|the steps|each step|why it works|how it works|briefly|brief explanation|explain the method|use that result)\b", re.IGNORECASE)
_DEPENDENCY_REFERENCE_RE = re.compile(r"\b(this|that|it|the result|that result|use that|using that|method|steps)\b", re.IGNORECASE)
_EXPLICIT_CONCEPT_TOPIC_RE = re.compile(r"\b(theorem|law|principle|concept|definition|lemma|corollary|rule)\b", re.IGNORECASE)
_TOPIC_NOUN_RE = re.compile(r"\b([a-z][a-z0-9'-]{2,}(?:\s+[a-z][a-z0-9'-]{2,}){0,3})\b", re.IGNORECASE)
_MATH_ENTITY_RE = re.compile(r"(?:[xyz]\^\d+|(?<![a-z])[xyz](?![a-z])|[0-9]+|[=+\-*/()])", re.IGNORECASE)
_GENERIC_MATH_TOPIC_RE = re.compile(r"\b(integration|integral|derivative|differentiation|equation|algebra|calculus|roots?|factorization|factoring|quadratic)\b", re.IGNORECASE)
_STOPWORDS = {
    "and",
    "also",
    "then",
    "briefly",
    "please",
    "can",
    "you",
    "the",
    "a",
    "an",
    "that",
    "this",
    "it",
    "result",
    "method",
    "steps",
    "something",
}


@dataclass(frozen=True)
class ClauseIntent:
    raw_clause: str
    action: str
    intent_type: str
    math_like: bool
    depends_on_previous: bool
    topic_hint: str = ""
    math_entities: frozenset[str] = frozenset()
    modifiers: tuple[str, ...] = ()


@dataclass(frozen=True)
class QueryPlanStep:
    step_type: str
    input_text: str
    mode: str
    directives: tuple[str, ...] = ()
    depends_on: int | None = None
    source: str = "policy"
    reason: str = ""


@dataclass(frozen=True)
class QueryExecutionPlan:
    steps: tuple[QueryPlanStep, ...] = ()
    conflicts: tuple[str, ...] = ()

    @property
    def solve_step(self) -> QueryPlanStep | None:
        return next((step for step in self.steps if step.step_type == "solve"), None)

    @property
    def explain_step(self) -> QueryPlanStep | None:
        return next((step for step in self.steps if step.step_type == "explain"), None)

    def to_trace(self, *, input_text: str, clause_intents: tuple[ClauseIntent, ...]) -> dict[str, object]:
        detected_intents = [
            {
                "type": clause.intent_type.upper(),
                "clause": clause.raw_clause,
            }
            for clause in clause_intents
            if clause.action != "unknown"
        ]
        bindings = []
        modifiers = []
        policy_resolution = []
        execution_plan = []

        for index, step in enumerate(self.steps):
            execution_plan.append(
                {
                    "step_id": index,
                    "type": step.step_type,
                    "input": step.input_text,
                    "mode": step.mode,
                    "depends_on": step.depends_on,
                    "decision_reason": step.reason,
                }
            )
            policy_resolution.append(
                {
                    "step": index,
                    "mode": step.mode,
                    "source": step.source,
                    "decision_reason": step.reason,
                }
            )
            for directive in step.directives:
                modifiers.append(
                    {
                        "target": index,
                        "type": directive,
                    }
                )
            if step.depends_on is not None:
                bindings.append(
                    {
                        "from": step.depends_on,
                        "to": index,
                        "type": "derived_dependency",
                    }
                )

        return {
            "input": input_text,
            "detected_intents": detected_intents,
            "bindings": bindings,
            "modifiers": modifiers,
            "policy_resolution": policy_resolution,
            "execution_plan": execution_plan,
            "conflicts": list(self.conflicts),
        }

    def to_safe_debug(self) -> dict[str, object]:
        return {
            "plan": [
                f"Step {index + 1}: {step.step_type} ({step.mode})"
                for index, step in enumerate(self.steps)
            ]
        }

    def build_execution_echo(self) -> dict[str, object]:
        executed_steps = [
            {
                "step_id": index,
                "type": step.step_type,
                "planned_mode": step.mode,
                "executed_mode": step.mode,
                "matched_plan": True,
            }
            for index, step in enumerate(self.steps)
        ]
        return {
            "executed_steps": executed_steps,
            "matched_plan": all(step["matched_plan"] for step in executed_steps),
        }


@dataclass(frozen=True)
class QuerySplitDecision:
    should_clarify: bool
    clauses: tuple[str, ...] = ()
    intents: tuple[str, ...] = ()
    clause_intents: tuple[ClauseIntent, ...] = ()
    execution_plan_obj: QueryExecutionPlan = field(default_factory=QueryExecutionPlan)

    @property
    def primary_clause(self) -> ClauseIntent | None:
        return next((clause for clause in self.clause_intents if clause.intent_type == "primary"), None)

    @property
    def execution_plan(self) -> dict[str, bool]:
        solve_step = self.execution_plan_obj.solve_step
        explain_step = self.execution_plan_obj.explain_step
        return {
            "detailed_steps": bool(solve_step and solve_step.mode == "scaffolded"),
            "brief": bool(solve_step and solve_step.mode == "minimal"),
            "explain_brief": bool(explain_step and explain_step.mode == "minimal"),
            "explain_detailed": bool(explain_step and explain_step.mode == "scaffolded"),
        }

    @property
    def query_execution_plan(self) -> QueryExecutionPlan:
        return self.execution_plan_obj

    @property
    def qep_trace(self) -> dict[str, object]:
        return self.execution_plan_obj.to_trace(input_text=" ".join(self.clauses).strip(), clause_intents=self.clause_intents)

    @property
    def clarification_message(self) -> str | None:
        if not self.should_clarify:
            return None
        if self.execution_plan_obj.conflicts:
            return self.execution_plan_obj.conflicts[0]
        if len(self.clauses) >= 2:
            first = self.clauses[0]
            second = self.clauses[1]
            return (
                "I found separate tasks in your message. Do you want me to:\n"
                f"1. {first}\n"
                f"2. {second}\n"
                "or should I handle them separately?"
            )
        return "I found separate tasks in your message. Please tell me which one to handle first."


class QuerySplitter:
    """Detects whether compound prompts are compatible and builds an execution plan."""

    _ACTION_TO_INTENT_TYPE = {
        "solve": "primary",
        "check": "primary",
        "explain": "supporting",
        "compare": "supporting",
        "unknown": "unknown",
    }

    @classmethod
    def analyze(cls, query: str) -> QuerySplitDecision:
        text = " ".join((query or "").split())
        if not text:
            return QuerySplitDecision(should_clarify=False)

        clauses = tuple(part.strip(" ,.;:") for part in _CLAUSE_SPLIT_RE.split(text) if part.strip(" ,.;:"))
        clause_intents = tuple(cls._classify_clause(clause) for clause in clauses)
        execution_plan = cls._build_execution_plan(clause_intents)

        if execution_plan.conflicts:
            return QuerySplitDecision(
                should_clarify=True,
                clauses=clauses,
                intents=tuple(clause.action for clause in clause_intents),
                clause_intents=clause_intents,
                execution_plan_obj=execution_plan,
            )

        if len(clauses) < 2:
            return QuerySplitDecision(
                should_clarify=False,
                clauses=clauses,
                intents=tuple(clause.action for clause in clause_intents),
                clause_intents=clause_intents,
                execution_plan_obj=execution_plan,
            )

        actionable = [clause for clause in clause_intents if clause.action != "unknown"]
        actionable_without_primary = [clause for clause in actionable if clause.intent_type != "execution_modifier"]
        if len(actionable_without_primary) < 2:
            return QuerySplitDecision(
                should_clarify=False,
                clauses=clauses,
                intents=tuple(clause.action for clause in clause_intents),
                clause_intents=clause_intents,
                execution_plan_obj=execution_plan,
            )

        should_clarify = cls._should_clarify(actionable_without_primary)
        return QuerySplitDecision(
            should_clarify=should_clarify,
            clauses=clauses,
            intents=tuple(clause.action for clause in clause_intents),
            clause_intents=clause_intents,
            execution_plan_obj=execution_plan,
        )

    @classmethod
    def _detect_clause_intent(cls, clause: str) -> str:
        if _SOLVE_RE.search(clause):
            return "solve"
        if _EXPLAIN_RE.search(clause):
            return "explain"
        if _CHECK_RE.search(clause):
            return "check"
        if _QUERY_RE.search(clause):
            return "compare"
        if _EXECUTION_MODIFIER_RE.search(clause):
            return "modify"
        return "unknown"

    @classmethod
    def _classify_clause(cls, clause: str) -> ClauseIntent:
        action = cls._detect_clause_intent(clause)
        intent_type = cls._ACTION_TO_INTENT_TYPE.get(action, "execution_modifier" if action == "modify" else "unknown")
        math_entities = cls._extract_math_entities(clause)
        if action == "explain" and math_entities:
            intent_type = "derived_supporting"
        return ClauseIntent(
            raw_clause=clause,
            action=action,
            intent_type=intent_type,
            math_like=is_math_like(clause),
            depends_on_previous=bool(_SUPPORTING_REFERENCE_RE.search(clause) or _DEPENDENCY_REFERENCE_RE.search(clause)),
            topic_hint=cls._extract_topic_hint(clause),
            math_entities=math_entities,
            modifiers=cls._extract_modifiers(clause),
        )

    @classmethod
    def _should_clarify(cls, clauses: list[ClauseIntent]) -> bool:
        primary_count = sum(1 for clause in clauses if clause.intent_type == "primary")
        if primary_count >= 2:
            return True

        primary_clause = next((clause for clause in clauses if clause.intent_type == "primary"), None)
        supporting_clauses = [clause for clause in clauses if clause.intent_type in {"supporting", "derived_supporting"}]
        if primary_clause and supporting_clauses:
            return any(cls._is_disjoint_supporting_clause(primary_clause, clause) for clause in supporting_clauses)

        distinct_topics = {clause.topic_hint for clause in clauses if clause.topic_hint}
        return len(distinct_topics) > 1 and not all(clause.depends_on_previous for clause in clauses[1:])

    @classmethod
    def _is_disjoint_supporting_clause(cls, primary_clause: ClauseIntent, supporting_clause: ClauseIntent) -> bool:
        if supporting_clause.depends_on_previous:
            return False
        if cls._shares_math_entities(primary_clause, supporting_clause):
            return False
        if supporting_clause.intent_type == "derived_supporting":
            return False
        if supporting_clause.math_like and _GENERIC_MATH_TOPIC_RE.search(supporting_clause.raw_clause):
            return True
        if supporting_clause.math_like and not _EXPLICIT_CONCEPT_TOPIC_RE.search(supporting_clause.raw_clause):
            return False
        if not supporting_clause.topic_hint:
            return False
        if primary_clause.topic_hint and primary_clause.topic_hint == supporting_clause.topic_hint:
            return False
        return True

    @staticmethod
    def _shares_math_entities(primary_clause: ClauseIntent, supporting_clause: ClauseIntent) -> bool:
        primary_entities = {entity for entity in primary_clause.math_entities if entity not in {"(", ")", "+", "-", "*", "/", "="}}
        supporting_entities = {entity for entity in supporting_clause.math_entities if entity not in {"(", ")", "+", "-", "*", "/", "="}}
        return bool(primary_entities & supporting_entities)

    @staticmethod
    def _extract_math_entities(clause: str) -> frozenset[str]:
        if not is_math_like(clause):
            return frozenset()
        return frozenset(token.lower() for token in _MATH_ENTITY_RE.findall(clause))

    @staticmethod
    def _extract_modifiers(clause: str) -> tuple[str, ...]:
        modifiers: list[str] = []
        if _DETAILED_RE.search(clause):
            modifiers.append("detailed")
        if _STEP_BY_STEP_RE.search(clause):
            modifiers.append("step_by_step")
        if _BRIEF_RE.search(clause):
            modifiers.append("brief")
        return tuple(modifiers)

    @classmethod
    def _build_execution_plan(cls, clauses: tuple[ClauseIntent, ...]) -> QueryExecutionPlan:
        steps: list[QueryPlanStep] = []
        conflicts: list[str] = []

        primary_clause = next((clause for clause in clauses if clause.intent_type == "primary"), None)
        if primary_clause:
            mode, conflict = cls._resolve_mode(primary_clause.modifiers, target="solve")
            source = "explicit_modifier" if primary_clause.modifiers else "policy"
            reason = "explicit_modifier_override" if primary_clause.modifiers else ""
            if not primary_clause.modifiers:
                mode = teaching_policy_engine.select_mode(step_type=primary_clause.action, text=primary_clause.raw_clause)
                reason = teaching_policy_engine.select_reason(step_type=primary_clause.action, text=primary_clause.raw_clause)
            if conflict:
                conflicts.append(conflict)
            steps.append(QueryPlanStep(step_type=primary_clause.action, input_text=primary_clause.raw_clause, mode=mode, directives=primary_clause.modifiers, source=source, reason=reason))

        explain_depends_on = 0 if primary_clause else None
        for clause in clauses:
            if clause.intent_type not in {"supporting", "derived_supporting"}:
                continue
            mode, conflict = cls._resolve_mode(clause.modifiers, target="explain")
            source = "explicit_modifier" if clause.modifiers else "policy"
            reason = "explicit_modifier_override" if clause.modifiers else ""
            if not clause.modifiers:
                mode = teaching_policy_engine.select_mode(step_type="explain", text=clause.raw_clause, depends_on_primary=explain_depends_on == 0)
                reason = teaching_policy_engine.select_reason(step_type="explain", text=clause.raw_clause, depends_on_primary=explain_depends_on == 0)
            if conflict:
                conflicts.append(conflict)
            steps.append(QueryPlanStep(step_type="explain", input_text=clause.raw_clause, mode=mode, directives=clause.modifiers, depends_on=explain_depends_on, source=source, reason=reason))

        return QueryExecutionPlan(steps=tuple(steps), conflicts=tuple(conflicts))

    @staticmethod
    def _resolve_mode(modifiers: tuple[str, ...], *, target: str) -> tuple[str, str | None]:
        modifier_set = set(modifiers)
        if "brief" in modifier_set and ("detailed" in modifier_set or "step_by_step" in modifier_set):
            return "guided", f"I found conflicting style instructions for the {target} task: both brief and detailed. Please pick one."
        if "detailed" in modifier_set or "step_by_step" in modifier_set:
            return "scaffolded", None
        if "brief" in modifier_set:
            return "minimal", None
        return "guided", None

    @staticmethod
    def _extract_topic_hint(clause: str) -> str:
        cleaned = clause.lower()
        for token in ("solve", "find", "compute", "calculate", "differentiate", "derive", "integrate", "evaluate", "simplify", "limit", "explain", "describe", "teach", "justify", "check", "verify", "compare", "contrast", "relate", "connect", "use"):
            cleaned = re.sub(rf"\b{token}\b", " ", cleaned)
        cleaned = " ".join(cleaned.split())
        if _EXPLICIT_CONCEPT_TOPIC_RE.search(clause):
            for match in _TOPIC_NOUN_RE.finditer(cleaned):
                phrase = match.group(1).strip()
                words = [word for word in phrase.split() if word not in _STOPWORDS]
                if words:
                    return " ".join(words)
        if is_math_like(clause):
            return "math_expression"
        for match in _TOPIC_NOUN_RE.finditer(cleaned):
            phrase = match.group(1).strip()
            words = [word for word in phrase.split() if word not in _STOPWORDS]
            if words:
                return " ".join(words)
        return ""


query_splitter = QuerySplitter()
