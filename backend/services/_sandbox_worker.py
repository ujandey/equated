"""
Services — Sandbox Worker (Subprocess Entry Point)

Minimal script that runs INSIDE the sandboxed subprocess.
Reads a JSON operation from stdin, executes via SymPy, writes JSON result to stdout.

Security:
  - Sets sys.setrecursionlimit(1000) to prevent stack overflow
  - Sets signal.alarm() for hard timeout (Unix only, main thread guarded)
  - Sets resource.setrlimit() for memory cap (Unix only)
  - Never imports anything outside stdlib + sympy
  - All I/O is validated JSON with size caps
"""

from __future__ import annotations

import json
import sys
import threading
import time
import traceback


def _apply_os_limits(timeout_s: int, memory_mb: int) -> None:
    """Apply OS-level resource limits. Best-effort on each platform."""

    # Recursion limit — always works
    sys.setrecursionlimit(1000)

    # Unix: hard timeout via SIGALRM (only in main thread — R3-4 fix)
    try:
        import signal

        if (
            hasattr(signal, "SIGALRM")
            and threading.current_thread() is threading.main_thread()
        ):

            def _timeout_handler(signum, frame):
                raise SystemExit("Sandbox timeout (SIGALRM)")

            signal.signal(signal.SIGALRM, _timeout_handler)
            signal.alarm(timeout_s)
    except Exception:
        pass

    # Unix: memory limit via resource module
    try:
        import resource

        memory_bytes = memory_mb * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
    except Exception:
        pass  # Windows — no rlimit support, parent process handles timeout


def _execute(operation: str, expression: str, variable: str, extra: dict) -> dict:
    """
    Execute a single SymPy operation and return the result dict.

    Imports are deferred to here so the worker process only loads SymPy
    when it actually needs to execute.
    """
    from sympy import latex, symbols
    from sympy.parsing.sympy_parser import (
        parse_expr,
        standard_transformations,
        implicit_multiplication_application,
        convert_xor,
    )
    from sympy import simplify, factor, diff, integrate, limit, solve, Matrix

    transformations = standard_transformations + (
        implicit_multiplication_application,
        convert_xor,
    )

    node_count = 0

    def _parse(expr_str: str):
        nonlocal node_count
        parsed = parse_expr(expr_str, transformations=transformations)
        node_count += parsed.count_ops() + len(parsed.free_symbols) + 1
        return parsed

    def _normalize(expr_str: str) -> str:
        e = expr_str.strip().rstrip("?.")
        e = e.replace("^", "**")
        return e

    expression = _normalize(expression)
    var = symbols(variable) if variable else symbols("x")

    if operation == "solve":
        if "=" in expression:
            lhs, rhs = expression.split("=", 1)
            expr = _parse(lhs) - _parse(rhs)
        else:
            expr = _parse(expression)
        result = solve(expr, var)
        return {
            "success": True,
            "result": str(result),
            "latex_result": ", ".join(latex(s) for s in result),
            "steps": [f"Equation: {expression}", f"Solving for {variable}", f"Solutions: {result}"],
            "node_count": node_count,
        }

    elif operation == "differentiate":
        expr = _parse(expression)
        result = diff(expr, var)
        return {
            "success": True,
            "result": str(result),
            "latex_result": latex(result),
            "steps": [f"Expression: {expr}", f"d/d{variable}", f"Result: {result}"],
            "node_count": node_count,
        }

    elif operation == "integrate":
        expr = _parse(expression)
        bounds = extra.get("bounds")
        if bounds and len(bounds) == 2:
            result = integrate(expr, (var, bounds[0], bounds[1]))
            steps = [f"Expression: {expr}", f"Bounds: [{bounds[0]}, {bounds[1]}]", f"Result: {result}"]
        else:
            result = integrate(expr, var)
            steps = [f"Expression: {expr}", f"∫ d{variable}", f"Result: {result} + C"]
        return {
            "success": True,
            "result": str(result) + (" + C" if not bounds else ""),
            "latex_result": latex(result) + (" + C" if not bounds else ""),
            "steps": steps,
            "node_count": node_count,
        }

    elif operation == "simplify":
        expr = _parse(expression)
        result = factor(simplify(expr))
        return {
            "success": True,
            "result": str(result),
            "latex_result": latex(result),
            "steps": [f"Input: {expression}", f"Simplified: {result}"],
            "node_count": node_count,
        }

    elif operation == "evaluate":
        expr = _parse(expression)
        result = expr.evalf() if expr.free_symbols == set() else simplify(expr)
        return {
            "success": True,
            "result": str(result),
            "latex_result": latex(result),
            "steps": [f"Expression: {expr}", f"Evaluated: {result}"],
            "node_count": node_count,
        }

    elif operation == "limit":
        expr = _parse(expression)
        to_value = _parse(str(extra.get("to", "0")))
        result = limit(expr, var, to_value)
        return {
            "success": True,
            "result": str(result),
            "latex_result": latex(result),
            "steps": [f"Expression: {expr}", f"limit as {variable} → {to_value}", f"Result: {result}"],
            "node_count": node_count,
        }

    else:
        return {"success": False, "error": f"Unknown operation: {operation}", "node_count": 0}


def run() -> None:
    """
    Main entry point for the sandbox subprocess.

    Protocol:
      stdin  → JSON matching SandboxRequest schema
      stdout → JSON matching SandboxResponse schema
      stderr → ignored (crash diagnostics only)
    """
    # Read input from stdin
    raw_input = sys.stdin.read()

    # Size gate (SANDBOX_MAX_INPUT_JSON_KB enforced by parent, but double-check)
    if len(raw_input) > 64 * 1024:
        json.dump({"success": False, "error": "Input too large", "node_count": 0}, sys.stdout)
        return

    try:
        request = json.loads(raw_input)
    except json.JSONDecodeError as e:
        json.dump({"success": False, "error": f"Invalid JSON: {e}", "node_count": 0}, sys.stdout)
        return

    # Extract fields with defaults
    operation = request.get("operation", "")
    expression = request.get("expression", "")
    variable = request.get("variable", "x")
    extra = request.get("extra", {})

    # Apply OS-level limits
    timeout_s = request.get("timeout_s", 10)
    memory_mb = request.get("memory_mb", 256)
    _apply_os_limits(timeout_s, memory_mb)

    # Execute
    try:
        result = _execute(operation, expression, variable, extra)
        result.setdefault("peak_memory_kb", 0)
        json.dump(result, sys.stdout)
    except MemoryError:
        json.dump({"success": False, "error": "Memory limit exceeded", "node_count": 0, "killed_reason": "memory"}, sys.stdout)
    except SystemExit as e:
        json.dump({"success": False, "error": str(e), "node_count": 0, "killed_reason": "timeout"}, sys.stdout)
    except RecursionError:
        json.dump({"success": False, "error": "Maximum recursion depth exceeded", "node_count": 0, "killed_reason": "recursion"}, sys.stdout)
    except Exception as e:
        json.dump({"success": False, "error": str(e)[:500], "node_count": 0}, sys.stdout)


if __name__ == "__main__":
    run()
