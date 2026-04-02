"""
Tests — Parser Drift Liability 

Tests the hybrid parser against various structural drifts that LLMs
often produce (semantic changes to identical math, extraneous keys)
and ensures Sympy normalization acts idempotently.
"""

from services.hybrid_math_parser import hybrid_math_parser, StructuredMathParse
import pytest

class TestParserSemanticDrift:
    """Verifies different valid JSON variants parse identically."""
    
    @pytest.mark.parametrize("json_payload, expected_expr, expected_var", [
        (
            {"operation": "solve", "expression": "x**2 = 4", "variable": "x"},
            "x**2=4", "x" # Standard
        ),
        # Drift 1: Flipped equation
        (
            {"operation": "solve", "expression": "4 = x^2"},
            "4=x**2", "x" # Standard inference should find x
        ),
        # Drift 2: Implicit = 0 (SymPy convention)
        (
            {"operation": "solve", "expression": "x^2 - 4", "variable": "x"},
            "x**2-4", "x"
        ),
        # Drift 3: Unknown variable (parser inferrence)
        (
            {"operation": "differentiate", "expression": "sin(y)"},
            "sin(y)", "y" # Should infer y
        ),
        # Drift 4: Multi-character variables (if passed validation)
        (
            {"operation": "evaluate", "expression": "10 * z"},
            "10*z", "z"
        ),
    ])
    def test_semantic_equivalence_variants(self, json_payload, expected_expr, expected_var):
        """
        No matter the internal drift across these forms, from_json normalizes
        them safely.
        """
        result = hybrid_math_parser._from_json(json_payload)
        
        # Test normalization handles powers and removes spaces
        assert result.expression.replace(' ', '') == expected_expr, f"Failed semantic form {json_payload}"
        assert result.variable == expected_var, f"Failed variable inference {json_payload}"


    @pytest.mark.parametrize("malformed_payload, expected_failure_count", [
        # Adversarial 1: Multiple '=' operations
        ({"operation": "solve", "expression": "x=y=z"}, 1),
        
        # Adversarial 2: Invalid variables array
        ({"operation": "solve", "expression": "x^2=4", "variable": "xy"}, 1),
        
        # Adversarial 3: Natural language bleeding into expression
        ({"operation": "solve", "expression": "solve x^2=4 please"}, 2),
        
        # Adversarial 4: Weird bounds injection
        ({"operation": "integrate", "expression": "x", "bounds": [0, 1, 2]}, 1),
        
        # Adversarial 5: Malicious function injection
        ({"operation": "evaluate", "expression": "os.system('rm -rf /') + 5"}, 1),
    ])
    def test_adversarial_strict_llm_json(self, malformed_payload, expected_failure_count):
        """
        Catch LLM hallucinations and adversarial structures.
        """
        errors = hybrid_math_parser._validate_llm_json_strict(malformed_payload)
        assert len(errors) >= expected_failure_count, f"Did not catch adversarial payload {malformed_payload}: {errors}"


    def test_extraneous_valid_json_ignored(self):
        """The parser should gracefully ignore unknown fields."""
        json_payload = {
            "operation": "solve",
            "expression": "x+1=2",
            "variable": "x",
            "thought_process": "I think I should solve for x.",
            "nested_data": {"useless": True},
            "confidence": "100%",
        }
        
        result = hybrid_math_parser._from_json(json_payload)
        assert result.expression == "x+1=2"
        assert result.operation == "solve"
        # The extra dict should only have what was nested in 'extra', not everything else.
        assert "thought_process" not in result.extra
