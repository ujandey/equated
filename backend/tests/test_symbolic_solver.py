from services.symbolic_solver import symbolic_solver


def test_detect_math_problem():
    assert symbolic_solver.detect_math_problem("solve x^2 - 5x + 6 = 0") is True
    assert symbolic_solver.detect_math_problem("hello there") is False


def test_extract_expression_returns_clarification_for_missing_expression():
    extracted = symbolic_solver.extract_expression("differentiate")

    assert extracted.needs_clarification is True
    assert "differentiate" in (extracted.clarification_message or "").lower()


def test_extract_expression_uses_deterministic_alias_free_parse():
    extracted = symbolic_solver.extract_expression("solve x^2 - 5x + 6 = 0")

    assert extracted.needs_clarification is False
    assert extracted.operation == "solve"
    assert extracted.expression == "x**2 - 5*x + 6 = 0"


def test_solve_expression_solves_equation_with_sympy():
    solution = symbolic_solver.solve_expression("solve x^2 - 5x + 6 = 0")

    assert solution.success is True
    assert solution.verified is True
    assert solution.math_result is not None
    assert solution.math_result.result == "[2, 3]"


def test_verify_solution_rejects_wrong_equation_answer():
    extracted = symbolic_solver.extract_expression("solve x^2 - 5x + 6 = 0")

    assert symbolic_solver.verify_solution(extracted, "[4]") is False


def test_build_explanation_messages_locks_result():
    solution = symbolic_solver.solve_expression("differentiate x^3 + 2*x")
    messages = symbolic_solver.build_explanation_messages("differentiate x^3 + 2*x", solution)

    assert messages[0]["role"] == "system"
    assert "must explain only the provided verified result" in messages[0]["content"].lower()
    assert "Verified result: 3*x**2 + 2" in messages[1]["content"]
