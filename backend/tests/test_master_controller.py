from types import SimpleNamespace

import pytest

from services.master_controller import master_controller
from services.master_controller.query_splitter import query_splitter
from services.topic_blocks import AnchorMatch, TopicRoutingDecision


def _routing(block_id: str, decision_type: str = "new_topic", anchor_kind: str | None = None) -> TopicRoutingDecision:
    return TopicRoutingDecision(
        block_id=block_id,
        decision_type=decision_type,
        reason="test",
        is_new_block=decision_type == "new_topic",
        scores={},
        thresholds={},
        anchor=AnchorMatch(kind=anchor_kind, text=None, confidence=0.9 if anchor_kind else 0.0),
        subject="physics",
    )


@pytest.mark.asyncio
async def test_validation_gate_blocks_ambiguous_derivative(monkeypatch):
    async def _session(**_kwargs):
        return "test-session"

    async def _route(**_kwargs):
        return _routing("block-1")

    async def _student(*_args, **_kwargs):
        return None

    async def _no_update(**_kwargs):
        return None

    monkeypatch.setattr(master_controller, "_ensure_session", _session)
    monkeypatch.setattr(master_controller, "_select_context", _route)
    monkeypatch.setattr(master_controller, "_load_student_state", _student)
    monkeypatch.setattr(master_controller, "_update_state", _no_update)

    solve_calls = []
    monkeypatch.setattr("services.master_controller.controller.symbolic_solver.solve_expression", lambda *_args, **_kwargs: solve_calls.append(True))

    result = await master_controller.handle_query(
        user_id="test-user",
        session_id="test-session",
        source="chat",
        query="Solve derivative",
    )

    assert result.trace.validation_passed is False
    assert result.response.clarification_request is not None
    assert "provide" in result.response.clarification_request.lower()
    assert solve_calls == []


@pytest.mark.asyncio
async def test_unicode_normalization_solves_quadratic(monkeypatch):
    async def _session(**_kwargs):
        return "test-session"

    async def _route(**_kwargs):
        return _routing("block-1")

    async def _student(*_args, **_kwargs):
        return None

    async def _no_update(**_kwargs):
        return None

    async def _structured_explanation(**_kwargs):
        return (
            SimpleNamespace(
                final_answer="x = -2, 2",
                steps=[{"step": 1, "explanation": "Factor the equation."}],
                concept_used="Quadratic equation",
                quick_summary="Roots are -2 and 2.",
                problem_interpretation="Solve x^2 - 4 = 0",
                alternative_method=None,
                common_mistakes=None,
            ),
            "intermediate",
        )

    monkeypatch.setattr(master_controller, "_ensure_session", _session)
    monkeypatch.setattr(master_controller, "_select_context", _route)
    monkeypatch.setattr(master_controller, "_load_student_state", _student)
    monkeypatch.setattr(master_controller, "_update_state", _no_update)
    monkeypatch.setattr("services.master_controller.controller.route_pedagogy", lambda *_args, **_kwargs: {"strategy": "step_by_step"})
    monkeypatch.setattr("services.master_controller.controller.classifier.classify", lambda *_args, **_kwargs: SimpleNamespace(subject=SimpleNamespace(value="math")))
    monkeypatch.setattr("services.master_controller.controller.adaptive_explainer.generate_structured_explanation", _structured_explanation)

    captured = {}

    original_extract = __import__("services.master_controller.controller", fromlist=["validation_gates_service"]).validation_gates_service.run_validation_gates

    def _capture_validation(intent, query):
        captured["normalized_query"] = query
        return original_extract(intent, query)

    monkeypatch.setattr("services.master_controller.controller.validation_gates_service.run_validation_gates", _capture_validation)

    result = await master_controller.handle_query(
        user_id="test-user",
        session_id="test-session",
        source="chat",
        query="Solve x² - 4 = 0",
    )

    assert captured["normalized_query"] == "Solve x^2 - 4 = 0"
    assert "-2" in result.response.final_answer and "2" in result.response.final_answer
    assert result.trace.tool_used == "sympy"


@pytest.mark.asyncio
async def test_follow_up_context_reuses_same_block(monkeypatch):
    async def _session(**_kwargs):
        return "test-session"

    async def _student(*_args, **_kwargs):
        return None

    async def _no_update(**_kwargs):
        return None

    async def _structured_explanation(**_kwargs):
        return (
            SimpleNamespace(
                final_answer="Gauss's law formula: ΦE = Qenc/ε0",
                steps=[],
                concept_used="Electrostatics",
                quick_summary="Flux equals enclosed charge over permittivity.",
                problem_interpretation="Explain Gauss law",
                alternative_method=None,
                common_mistakes=None,
            ),
            "intermediate",
        )

    monkeypatch.setattr(master_controller, "_ensure_session", _session)
    monkeypatch.setattr(master_controller, "_load_student_state", _student)
    monkeypatch.setattr(master_controller, "_update_state", _no_update)
    monkeypatch.setattr("services.master_controller.controller.route_pedagogy", lambda *_args, **_kwargs: {"strategy": "conceptual"})
    monkeypatch.setattr("services.master_controller.controller.classifier.classify", lambda *_args, **_kwargs: SimpleNamespace(subject=SimpleNamespace(value="physics")))
    monkeypatch.setattr("services.master_controller.controller.model_router.route", lambda *_args, **_kwargs: SimpleNamespace())
    async def _fallback(*_args, **_kwargs):
        return SimpleNamespace(content="Gauss law formula is ΦE = Qenc/ε0", model="mock-model")

    monkeypatch.setattr("services.master_controller.controller.controller_fallback_handler.generate_with_fallback", _fallback)
    monkeypatch.setattr("services.master_controller.controller.adaptive_explainer.generate_structured_explanation", _structured_explanation)

    routing_calls = iter(
        [
            _routing("block-gauss", "new_topic"),
            _routing("block-gauss", "follow_up", anchor_kind="continuation"),
        ]
    )
    async def _route(**_kwargs):
        return next(routing_calls)

    monkeypatch.setattr(master_controller, "_select_context", _route)

    first = await master_controller.handle_query(
        user_id="test-user",
        session_id="test-session",
        source="chat",
        query="Explain Gauss law",
    )
    second = await master_controller.handle_query(
        user_id="test-user",
        session_id="test-session",
        source="chat",
        query="Now give formula",
    )

    assert first.block_id == "block-gauss"
    assert second.block_id == "block-gauss"
    assert "Qenc" in second.response.final_answer


@pytest.mark.asyncio
async def test_symbolic_first_enforcement_never_uses_llm_math(monkeypatch):
    async def _session(**_kwargs):
        return "test-session"

    async def _route(**_kwargs):
        return _routing("block-1")

    async def _student(*_args, **_kwargs):
        return None

    async def _no_update(**_kwargs):
        return None

    async def _structured_explanation(**_kwargs):
        return (
            SimpleNamespace(
                final_answer="x = 2",
                steps=[{"step": 1, "explanation": "Subtract 3 then divide by 2."}],
                concept_used="Linear equations",
                quick_summary="x = 2",
                problem_interpretation="Solve 2*x + 3 = 7",
                alternative_method=None,
                common_mistakes=None,
            ),
            "intermediate",
        )

    monkeypatch.setattr(master_controller, "_ensure_session", _session)
    monkeypatch.setattr(master_controller, "_select_context", _route)
    monkeypatch.setattr(master_controller, "_load_student_state", _student)
    monkeypatch.setattr(master_controller, "_update_state", _no_update)
    monkeypatch.setattr("services.master_controller.controller.route_pedagogy", lambda *_args, **_kwargs: {"strategy": "step_by_step"})
    monkeypatch.setattr("services.master_controller.controller.classifier.classify", lambda *_args, **_kwargs: SimpleNamespace(subject=SimpleNamespace(value="math")))
    monkeypatch.setattr("services.master_controller.controller.adaptive_explainer.generate_structured_explanation", _structured_explanation)

    fallback_calls = []

    async def _fallback(*_args, **_kwargs):
        fallback_calls.append(True)
        return SimpleNamespace(content="hallucinated math", model="mock")

    monkeypatch.setattr("services.master_controller.controller.controller_fallback_handler.generate_with_fallback", _fallback)

    result = await master_controller.handle_query(
        user_id="test-user",
        session_id="test-session",
        source="chat",
        query="Solve 2*x + 3 = 7",
    )

    assert result.trace.tool_used == "sympy"
    assert result.response.verified is True
    assert fallback_calls == []


@pytest.mark.asyncio
async def test_multi_intent_query_requires_clarification(monkeypatch):
    async def _session(**_kwargs):
        return "test-session"

    async def _route(**_kwargs):
        return _routing("block-1")

    async def _student(*_args, **_kwargs):
        return None

    async def _no_update(**_kwargs):
        return None

    monkeypatch.setattr(master_controller, "_ensure_session", _session)
    monkeypatch.setattr(master_controller, "_select_context", _route)
    monkeypatch.setattr(master_controller, "_load_student_state", _student)
    monkeypatch.setattr(master_controller, "_update_state", _no_update)

    result = await master_controller.handle_query(
        user_id="test-user",
        session_id="test-session",
        source="chat",
        query="Solve x^2 - 4 = 0 and explain stokes theorem",
    )

    assert result.trace.validation_passed is False
    clarification = (result.response.clarification_request or "").lower()
    assert "separate tasks" in clarification
    assert "stokes theorem" in clarification
    assert result.trace.strategy == "query_splitter"
    assert result.block_id is None


@pytest.mark.asyncio
async def test_two_solve_commands_require_clarification(monkeypatch):
    async def _session(**_kwargs):
        return "test-session"

    async def _route(**_kwargs):
        return _routing("block-1")

    async def _student(*_args, **_kwargs):
        return None

    async def _no_update(**_kwargs):
        return None

    monkeypatch.setattr(master_controller, "_ensure_session", _session)
    monkeypatch.setattr(master_controller, "_select_context", _route)
    monkeypatch.setattr(master_controller, "_load_student_state", _student)
    monkeypatch.setattr(master_controller, "_update_state", _no_update)

    result = await master_controller.handle_query(
        user_id="test-user",
        session_id="test-session",
        source="chat",
        query="Solve x^2 - 4 = 0 and calculate 3x + 1 when x = 2",
    )

    assert result.trace.validation_passed is False
    assert "separate tasks" in (result.response.clarification_request or "").lower()


@pytest.mark.asyncio
async def test_solve_and_explain_method_stays_in_single_flow(monkeypatch):
    async def _session(**_kwargs):
        return "test-session"

    async def _route(**_kwargs):
        return _routing("block-1")

    async def _student(*_args, **_kwargs):
        return None

    async def _no_update(**_kwargs):
        return None

    async def _structured_explanation(**_kwargs):
        return (
            SimpleNamespace(
                final_answer="x = -2, 2",
                steps=[{"step": 1, "explanation": "Factor into (x - 2)(x + 2) = 0."}],
                concept_used="Difference of squares",
                quick_summary="Solve by factoring, then read off the roots.",
                problem_interpretation="Solve x^2 - 4 = 0 and briefly explain the method",
                alternative_method=None,
                common_mistakes=None,
            ),
            "intermediate",
        )

    monkeypatch.setattr(master_controller, "_ensure_session", _session)
    monkeypatch.setattr(master_controller, "_select_context", _route)
    monkeypatch.setattr(master_controller, "_load_student_state", _student)
    monkeypatch.setattr(master_controller, "_update_state", _no_update)
    monkeypatch.setattr("services.master_controller.controller.route_pedagogy", lambda *_args, **_kwargs: {"strategy": "step_by_step"})
    monkeypatch.setattr("services.master_controller.controller.classifier.classify", lambda *_args, **_kwargs: SimpleNamespace(subject=SimpleNamespace(value="math")))
    monkeypatch.setattr("services.master_controller.controller.adaptive_explainer.generate_structured_explanation", _structured_explanation)

    result = await master_controller.handle_query(
        user_id="test-user",
        session_id="test-session",
        source="chat",
        query="Solve x^2 - 4 = 0 and briefly explain the method",
    )

    assert result.trace.validation_passed is True
    assert result.trace.tool_used == "sympy"
    assert "x = -2, 2" in result.response.final_answer


@pytest.mark.asyncio
async def test_sequential_dependency_query_is_allowed(monkeypatch):
    async def _session(**_kwargs):
        return "test-session"

    async def _route(**_kwargs):
        return _routing("block-1")

    async def _student(*_args, **_kwargs):
        return None

    async def _no_update(**_kwargs):
        return None

    async def _structured_explanation(**_kwargs):
        return (
            SimpleNamespace(
                final_answer="x = -2, 2",
                steps=[{"step": 1, "explanation": "Use the roots to interpret the follow-up explanation."}],
                concept_used="Quadratic roots",
                quick_summary="The explanation can build on the solved roots.",
                problem_interpretation="Solve x^2 - 4 = 0, then use that result to explain something",
                alternative_method=None,
                common_mistakes=None,
            ),
            "intermediate",
        )

    monkeypatch.setattr(master_controller, "_ensure_session", _session)
    monkeypatch.setattr(master_controller, "_select_context", _route)
    monkeypatch.setattr(master_controller, "_load_student_state", _student)
    monkeypatch.setattr(master_controller, "_update_state", _no_update)
    monkeypatch.setattr("services.master_controller.controller.route_pedagogy", lambda *_args, **_kwargs: {"strategy": "step_by_step"})
    monkeypatch.setattr("services.master_controller.controller.classifier.classify", lambda *_args, **_kwargs: SimpleNamespace(subject=SimpleNamespace(value="math")))
    monkeypatch.setattr("services.master_controller.controller.adaptive_explainer.generate_structured_explanation", _structured_explanation)

    result = await master_controller.handle_query(
        user_id="test-user",
        session_id="test-session",
        source="chat",
        query="Solve x^2 - 4 = 0, then use that result to explain something",
    )

    assert result.trace.validation_passed is True
    assert result.trace.tool_used == "sympy"


@pytest.mark.asyncio
async def test_generic_math_topic_after_solve_requires_clarification(monkeypatch):
    async def _session(**_kwargs):
        return "test-session"

    async def _route(**_kwargs):
        return _routing("block-1")

    async def _student(*_args, **_kwargs):
        return None

    async def _no_update(**_kwargs):
        return None

    monkeypatch.setattr(master_controller, "_ensure_session", _session)
    monkeypatch.setattr(master_controller, "_select_context", _route)
    monkeypatch.setattr(master_controller, "_load_student_state", _student)
    monkeypatch.setattr(master_controller, "_update_state", _no_update)

    result = await master_controller.handle_query(
        user_id="test-user",
        session_id="test-session",
        source="chat",
        query="Solve x^2 - 4 = 0 and explain integration",
    )

    assert result.trace.validation_passed is False
    clarification = (result.response.clarification_request or "").lower()
    assert "separate tasks" in clarification
    assert "integration" in clarification


@pytest.mark.asyncio
async def test_expression_bound_explanation_is_allowed(monkeypatch):
    async def _session(**_kwargs):
        return "test-session"

    async def _route(**_kwargs):
        return _routing("block-1")

    async def _student(*_args, **_kwargs):
        return None

    async def _no_update(**_kwargs):
        return None

    async def _structured_explanation(**_kwargs):
        return (
            SimpleNamespace(
                final_answer="x = -2, 2",
                steps=[{"step": 1, "explanation": "Because the discriminant is positive, the quadratic has real roots."}],
                concept_used="Quadratic discriminant",
                quick_summary="The same expression has real roots because its discriminant is positive.",
                problem_interpretation="Solve x^2 - 4 = 0 and explain why x^2 - 4 = 0 has real roots",
                alternative_method=None,
                common_mistakes=None,
            ),
            "intermediate",
        )

    monkeypatch.setattr(master_controller, "_ensure_session", _session)
    monkeypatch.setattr(master_controller, "_select_context", _route)
    monkeypatch.setattr(master_controller, "_load_student_state", _student)
    monkeypatch.setattr(master_controller, "_update_state", _no_update)
    monkeypatch.setattr("services.master_controller.controller.route_pedagogy", lambda *_args, **_kwargs: {"strategy": "step_by_step"})
    monkeypatch.setattr("services.master_controller.controller.classifier.classify", lambda *_args, **_kwargs: SimpleNamespace(subject=SimpleNamespace(value="math")))
    monkeypatch.setattr("services.master_controller.controller.adaptive_explainer.generate_structured_explanation", _structured_explanation)

    result = await master_controller.handle_query(
        user_id="test-user",
        session_id="test-session",
        source="chat",
        query="Solve x^2 - 4 = 0 and explain why x^2 - 4 = 0 has real roots",
    )

    assert result.trace.validation_passed is True
    assert result.trace.tool_used == "sympy"
    assert "real roots" in result.response.simple_explanation.lower()


@pytest.mark.asyncio
async def test_execution_modifier_requests_detailed_steps(monkeypatch):
    async def _session(**_kwargs):
        return "test-session"

    async def _route(**_kwargs):
        return _routing("block-1")

    async def _student(*_args, **_kwargs):
        return None

    async def _no_update(**_kwargs):
        return None

    captured: dict[str, object] = {}

    async def _structured_explanation(**kwargs):
        captured.update(kwargs)
        return (
            SimpleNamespace(
                final_answer="x = -2, 2",
                steps=[
                    {"step": 1, "explanation": "Rewrite as (x - 2)(x + 2) = 0."},
                    {"step": 2, "explanation": "Set each factor equal to zero."},
                ],
                concept_used="Difference of squares",
                quick_summary="Detailed factorization gives the two roots.",
                problem_interpretation=kwargs["problem"],
                alternative_method=None,
                common_mistakes=None,
            ),
            "intermediate",
        )

    monkeypatch.setattr(master_controller, "_ensure_session", _session)
    monkeypatch.setattr(master_controller, "_select_context", _route)
    monkeypatch.setattr(master_controller, "_load_student_state", _student)
    monkeypatch.setattr(master_controller, "_update_state", _no_update)
    monkeypatch.setattr("services.master_controller.controller.route_pedagogy", lambda *_args, **_kwargs: {"strategy": "analogy", "reason": "default", "confidence": 0.6})
    monkeypatch.setattr("services.master_controller.controller.classifier.classify", lambda *_args, **_kwargs: SimpleNamespace(subject=SimpleNamespace(value="math")))
    monkeypatch.setattr("services.master_controller.controller.adaptive_explainer.generate_structured_explanation", _structured_explanation)

    result = await master_controller.handle_query(
        user_id="test-user",
        session_id="test-session",
        source="chat",
        query="Solve x^2 - 4 = 0 and explain each step in detail",
    )

    assert result.trace.validation_passed is True
    assert result.trace.tool_used == "sympy"
    assert result.trace.strategy == "scaffolded"
    assert captured["problem"] == "Solve x^2 - 4 = 0 and explain each step in detail"
    assert any("each algebraic step in detail" in directive.lower() for directive in captured["teaching_directives"])
    assert result.qep_trace["execution_plan"][0]["mode"] == "guided"
    assert result.qep_trace["execution_plan"][1]["mode"] == "scaffolded"


@pytest.mark.asyncio
async def test_conflicting_solve_modifiers_require_clarification(monkeypatch):
    async def _session(**_kwargs):
        return "test-session"

    async def _route(**_kwargs):
        return _routing("block-1")

    async def _student(*_args, **_kwargs):
        return None

    async def _no_update(**_kwargs):
        return None

    monkeypatch.setattr(master_controller, "_ensure_session", _session)
    monkeypatch.setattr(master_controller, "_select_context", _route)
    monkeypatch.setattr(master_controller, "_load_student_state", _student)
    monkeypatch.setattr(master_controller, "_update_state", _no_update)

    result = await master_controller.handle_query(
        user_id="test-user",
        session_id="test-session",
        source="chat",
        query="Solve x^2 - 4 = 0 step by step but briefly",
    )

    assert result.trace.validation_passed is False
    assert "conflicting style instructions" in (result.response.clarification_request or "").lower()


@pytest.mark.asyncio
async def test_scoped_modifiers_keep_solve_detailed_and_explanation_brief(monkeypatch):
    async def _session(**_kwargs):
        return "test-session"

    async def _route(**_kwargs):
        return _routing("block-1")

    async def _student(*_args, **_kwargs):
        return None

    async def _no_update(**_kwargs):
        return None

    captured: dict[str, object] = {}

    async def _structured_explanation(**kwargs):
        captured.update(kwargs)
        return (
            SimpleNamespace(
                final_answer="x = -2, 2",
                steps=[
                    {"step": 1, "explanation": "Factor the quadratic carefully."},
                    {"step": 2, "explanation": "Use the factors to identify the roots."},
                ],
                concept_used="Quadratic roots",
                quick_summary="The roots are real because the factors produce two real solutions.",
                problem_interpretation=kwargs["problem"],
                alternative_method=None,
                common_mistakes=None,
            ),
            "intermediate",
        )

    monkeypatch.setattr(master_controller, "_ensure_session", _session)
    monkeypatch.setattr(master_controller, "_select_context", _route)
    monkeypatch.setattr(master_controller, "_load_student_state", _student)
    monkeypatch.setattr(master_controller, "_update_state", _no_update)
    monkeypatch.setattr("services.master_controller.controller.route_pedagogy", lambda *_args, **_kwargs: {"strategy": "analogy", "reason": "default", "confidence": 0.6})
    monkeypatch.setattr("services.master_controller.controller.classifier.classify", lambda *_args, **_kwargs: SimpleNamespace(subject=SimpleNamespace(value="math")))
    monkeypatch.setattr("services.master_controller.controller.adaptive_explainer.generate_structured_explanation", _structured_explanation)

    result = await master_controller.handle_query(
        user_id="test-user",
        session_id="test-session",
        source="chat",
        query="Solve x^2 - 4 = 0 step by step and briefly explain why the roots are real",
    )

    assert result.trace.validation_passed is True
    assert result.trace.tool_used == "sympy"
    assert result.trace.strategy == "scaffolded"
    directives = captured["teaching_directives"]
    assert any("each algebraic step in detail" in directive.lower() for directive in directives)
    assert any("conceptual explanation brief" in directive.lower() for directive in directives)


def test_unmodified_solve_gets_policy_resolved_mode():
    decision = query_splitter.analyze("Solve x^2 - 4 = 0")

    assert decision.should_clarify is False
    assert decision.query_execution_plan.solve_step is not None
    assert decision.query_execution_plan.solve_step.mode in {"minimal", "guided", "scaffolded"}
    assert decision.query_execution_plan.solve_step.mode == "guided"


def test_qep_trace_has_valid_explain_dependencies():
    decision = query_splitter.analyze("Solve x^2 - 4 = 0 and briefly explain why the roots are real")
    trace = decision.query_execution_plan.to_trace(
        input_text="Solve x^2 - 4 = 0 and briefly explain why the roots are real",
        clause_intents=decision.clause_intents,
    )

    explain_steps = [step for step in trace["execution_plan"] if step["type"] == "explain"]
    assert explain_steps
    assert all(step["depends_on"] == 0 for step in explain_steps)


def test_qep_trace_records_policy_resolution_source():
    decision = query_splitter.analyze("Solve x^2 - 4 = 0")
    trace = decision.query_execution_plan.to_trace(
        input_text="Solve x^2 - 4 = 0",
        clause_intents=decision.clause_intents,
    )

    assert trace["policy_resolution"][0]["source"] == "policy"
    assert trace["policy_resolution"][0]["decision_reason"] == "quadratic_equation_default_policy"


def test_qep_trace_records_modifier_override_source():
    decision = query_splitter.analyze("Solve x^2 - 4 = 0 step by step and briefly explain why the roots are real")
    trace = decision.query_execution_plan.to_trace(
        input_text="Solve x^2 - 4 = 0 step by step and briefly explain why the roots are real",
        clause_intents=decision.clause_intents,
    )

    assert trace["policy_resolution"][0]["source"] == "explicit_modifier"
    assert trace["policy_resolution"][1]["source"] == "explicit_modifier"
    assert trace["modifiers"] == [{"target": 0, "type": "step_by_step"}, {"target": 1, "type": "brief"}]


def test_execution_echo_matches_planned_modes():
    decision = query_splitter.analyze("Solve x^2 - 4 = 0 step by step and briefly explain why the roots are real")
    echo = decision.query_execution_plan.build_execution_echo()

    assert echo["matched_plan"] is True
    assert echo["executed_steps"][0]["planned_mode"] == "scaffolded"
    assert echo["executed_steps"][0]["executed_mode"] == "scaffolded"
    assert echo["executed_steps"][1]["planned_mode"] == "minimal"
    assert echo["executed_steps"][1]["matched_plan"] is True
