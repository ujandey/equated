import re
from services.symbolic_solver import symbolic_solver
from services.master_controller.intent_classifier import QueryIntent
from services.master_controller.query_splitter import query_splitter

_INCOMPLETE_DERIVATIVE_RE = re.compile(r"d\^?2?[a-z]/d[a-z]\^?2?$", re.IGNORECASE)

class ValidationGates:
    """Handles fast rejection of invalid or ambiguous queries."""

    @staticmethod
    def run_validation_gates(intent: QueryIntent, query: str) -> str | None:
        split_decision = query_splitter.analyze(query)
        if split_decision.should_clarify:
            return split_decision.clarification_message
        if intent == "unclear":
            return "Please clarify whether you want me to solve, explain, or check a specific problem."
        if intent == "solve" and ValidationGates.requires_function_clarification(query):
            return "Please provide the function"
        if intent == "solve":
            extracted = symbolic_solver.extract_expression(query)
            if extracted.needs_clarification or not extracted.expression:
                return extracted.clarification_message or "Please provide the full mathematical expression."
        return None

    @staticmethod
    def requires_function_clarification(query: str) -> bool:
        lowered = query.lower().replace(" ", "")
        if "d^2" in lowered and _INCOMPLETE_DERIVATIVE_RE.search(lowered):
            return True
        return False

validation_gates_service = ValidationGates()
