"""
Services — SymPy Subprocess Sandbox

Executes SymPy operations in an isolated subprocess with OS-level resource limits.

Security properties:
  - Process boundary: SymPy cannot consume parent process memory
  - Memory limit: resource.setrlimit (Unix) or Process.join timeout (Windows)
  - CPU timeout: signal.alarm (Unix) or Process.join timeout (Windows)
  - IPC hardening: Pydantic validates both input and output JSON
  - Size caps: MAX input/output JSON sizes enforced
  - Recursion limit: 1000 (set inside subprocess)

Design constraints (from adversarial review):
  - R1-8: True subprocess, not threading
  - R2-3: Pydantic schemas both directions + size caps
  - R3-4: signal.alarm guarded for main thread only
  - compute_seconds is MEASURED wall-clock time (billing authority, not heuristic)
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import structlog
from pydantic import BaseModel, field_validator

from config.settings import settings
from core.contracts import SandboxResult

logger = structlog.get_logger("equated.services.sympy_sandbox")

# Path to the sandbox worker script
_WORKER_PATH = str(Path(__file__).parent / "_sandbox_worker.py")


# ── IPC Schemas (Pydantic — Flaw R2-3) ─────────────

class SandboxRequest(BaseModel):
    """Strictly validated input to sandbox subprocess."""

    operation: str
    expression: str
    variable: str = "x"
    extra: dict[str, str] = {}
    timeout_s: int = 10
    memory_mb: int = 256

    @field_validator("operation")
    @classmethod
    def validate_operation(cls, v: str) -> str:
        allowed = {"solve", "differentiate", "integrate", "simplify", "evaluate", "limit"}
        if v not in allowed:
            raise ValueError(f"Unknown operation: {v}")
        return v

    @field_validator("expression")
    @classmethod
    def validate_expression_length(cls, v: str) -> str:
        if len(v) > 2000:
            raise ValueError(f"Expression too long: {len(v)} chars (max 2000)")
        return v

    @field_validator("variable")
    @classmethod
    def validate_variable(cls, v: str) -> str:
        if len(v) > 2 or not v.isalpha():
            raise ValueError(f"Invalid variable: '{v}' (must be 1-2 letters)")
        return v


# Post-parse structure limits (Flaw R4-2: prevents small JSON → huge Python objects)
_MAX_STEPS = 50
_MAX_RESULT_LEN = 10240  # 10KB per string field


class SandboxResponse(BaseModel):
    """Strictly validated output from sandbox subprocess."""

    success: bool
    result: str = ""
    latex_result: str = ""
    steps: list[str] = []
    error: str | None = None
    node_count: int = 0
    peak_memory_kb: int = 0
    killed_reason: str | None = None

    @field_validator("steps")
    @classmethod
    def cap_steps(cls, v: list[str]) -> list[str]:
        return [s[:_MAX_RESULT_LEN] for s in v[:_MAX_STEPS]]

    @field_validator("result", "latex_result")
    @classmethod
    def cap_result_length(cls, v: str) -> str:
        return v[:_MAX_RESULT_LEN] if v else v

    @field_validator("error")
    @classmethod
    def cap_error_length(cls, v: str | None) -> str | None:
        return v[:2000] if v else v


class SympySandbox:
    """
    Executes SymPy in an isolated subprocess.

    Two modes:
      - ENABLED (production): true subprocess with resource limits
      - DISABLED (dev fallback): direct execution with threading.Timer soft guard

    Returns SandboxResult (frozen contract) with measured compute_seconds.
    """

    def __init__(self):
        self._semaphore = None

    def _get_semaphore(self):
        import asyncio
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(settings.MAX_SANDBOX_PROCESSES)
        return self._semaphore

    async def execute_guarded(
        self,
        operation: str,
        expression: str,
        variable: str = "x",
        extra: dict | None = None,
    ) -> SandboxResult:
        """
        Execute a SymPy operation in a sandboxed subprocess.

        Returns SandboxResult with measured compute_seconds.
        On any failure (timeout, OOM, protocol violation), returns
        killed=True with appropriate kill_reason.
        """
        extra = extra or {}
        # Ensure extra values are strings for Pydantic validation
        str_extra = {k: str(v) for k, v in extra.items()}

        # Validate input via Pydantic
        try:
            request = SandboxRequest(
                operation=operation,
                expression=expression,
                variable=variable,
                extra=str_extra,
                timeout_s=settings.SYMPY_SUBPROCESS_TIMEOUT_S,
                memory_mb=settings.SYMPY_SUBPROCESS_MEMORY_MB,
            )
        except Exception as e:
            logger.warning("sandbox_input_validation_failed", error=str(e)[:200])
            return SandboxResult(
                success=False,
                result_text="",
                latex_result="",
                steps=(),
                error=f"Input validation failed: {e}",
                compute_seconds=0.0,
                node_count=0,
                peak_memory_kb=0,
                killed=False,
                kill_reason=None,
            )

        request_json = request.model_dump_json()

        # Size gate
        if len(request_json) > settings.SANDBOX_MAX_INPUT_JSON_KB * 1024:
            return SandboxResult(
                success=False,
                result_text="",
                latex_result="",
                steps=(),
                error=f"Input JSON exceeds {settings.SANDBOX_MAX_INPUT_JSON_KB}KB limit",
                compute_seconds=0.0,
                node_count=0,
                peak_memory_kb=0,
                killed=True,
                kill_reason="input_too_large",
            )

        if not settings.SYMPY_SUBPROCESS_ENABLED:
            return await self._execute_direct(request)

        return await self._execute_subprocess(request, request_json)

    async def _execute_subprocess(
        self, request: SandboxRequest, request_json: str
    ) -> SandboxResult:
        """Run SymPy in a subprocess with OS-level isolation."""
        
        async with self._get_semaphore():
            start = time.perf_counter()

            try:
                proc = subprocess.Popen(
                    [sys.executable, _WORKER_PATH],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )

            try:
                stdout, stderr = proc.communicate(
                    input=request_json.encode("utf-8"),
                    timeout=settings.SYMPY_SUBPROCESS_TIMEOUT_S + 2,  # Grace period
                )
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
                compute_seconds = time.perf_counter() - start
                logger.warning(
                    "sandbox_timeout",
                    operation=request.operation,
                    expression=request.expression[:100],
                    timeout_s=settings.SYMPY_SUBPROCESS_TIMEOUT_S,
                )
                return SandboxResult(
                    success=False,
                    result_text="",
                    latex_result="",
                    steps=(),
                    error="Computation timed out — expression too complex",
                    compute_seconds=compute_seconds,
                    node_count=0,
                    peak_memory_kb=0,
                    killed=True,
                    kill_reason="timeout",
                )

        except Exception as e:
            compute_seconds = time.perf_counter() - start
            logger.error("sandbox_process_error", error=str(e)[:200])
            return SandboxResult(
                success=False,
                result_text="",
                latex_result="",
                steps=(),
                error=f"Sandbox process error: {e}",
                compute_seconds=compute_seconds,
                node_count=0,
                peak_memory_kb=0,
                killed=True,
                kill_reason="process_error",
            )

        compute_seconds = time.perf_counter() - start

        # Process exited with error
        if proc.returncode != 0:
            error_msg = stderr.decode("utf-8", errors="replace")[:500] if stderr else "Process crashed"
            kill_reason = "memory" if "MemoryError" in error_msg else "crash"
            logger.warning(
                "sandbox_crash",
                operation=request.operation,
                returncode=proc.returncode,
                error=error_msg[:200],
            )
            return SandboxResult(
                success=False,
                result_text="",
                latex_result="",
                steps=(),
                error=error_msg,
                compute_seconds=compute_seconds,
                node_count=0,
                peak_memory_kb=0,
                killed=True,
                kill_reason=kill_reason,
            )

        # Output size gate
        stdout_data = stdout.decode("utf-8", errors="replace")
        if len(stdout_data) > settings.SANDBOX_MAX_OUTPUT_JSON_KB * 1024:
            logger.warning(
                "sandbox_output_too_large",
                size_kb=len(stdout_data) // 1024,
                limit_kb=settings.SANDBOX_MAX_OUTPUT_JSON_KB,
            )
            return SandboxResult(
                success=False,
                result_text="",
                latex_result="",
                steps=(),
                error="Output exceeds size limit",
                compute_seconds=compute_seconds,
                node_count=0,
                peak_memory_kb=0,
                killed=True,
                kill_reason="output_too_large",
            )

        # Validate output via Pydantic
        try:
            response = SandboxResponse.model_validate_json(stdout_data)
        except Exception as e:
            logger.warning(
                "sandbox_output_validation_failed",
                error=str(e)[:200],
                raw_output=stdout_data[:200],
            )
            return SandboxResult(
                success=False,
                result_text="",
                latex_result="",
                steps=(),
                error="Protocol violation: invalid output from sandbox",
                compute_seconds=compute_seconds,
                node_count=0,
                peak_memory_kb=0,
                killed=True,
                kill_reason="protocol_violation",
            )

        return SandboxResult(
            success=response.success,
            result_text=response.result,
            latex_result=response.latex_result,
            steps=tuple(response.steps),
            error=response.error,
            compute_seconds=compute_seconds,
            node_count=response.node_count,
            peak_memory_kb=response.peak_memory_kb,
            killed=response.killed_reason is not None,
            kill_reason=response.killed_reason,
        )

    async def _execute_direct(self, request: SandboxRequest) -> SandboxResult:
        """
        Dev fallback: execute directly in-process with threading.Timer.

        WARNING: No memory isolation. Only use in development.
        """
        import asyncio
        import threading

        logger.debug("sandbox_direct_mode", operation=request.operation)

        result_holder: dict = {}
        error_holder: dict = {}
        timed_out = threading.Event()

        def _run():
            try:
                from services._sandbox_worker import _execute

                result_holder["data"] = _execute(
                    request.operation,
                    request.expression,
                    request.variable,
                    request.extra,
                )
            except Exception as e:
                error_holder["error"] = str(e)

        start = time.perf_counter()
        thread = threading.Thread(target=_run, daemon=True)
        thread.start()
        thread.join(timeout=settings.SYMPY_SUBPROCESS_TIMEOUT_S)
        compute_seconds = time.perf_counter() - start

        if thread.is_alive():
            return SandboxResult(
                success=False,
                result_text="",
                latex_result="",
                steps=(),
                error="Computation timed out (dev mode)",
                compute_seconds=compute_seconds,
                node_count=0,
                peak_memory_kb=0,
                killed=True,
                kill_reason="timeout",
            )

        if error_holder:
            return SandboxResult(
                success=False,
                result_text="",
                latex_result="",
                steps=(),
                error=error_holder["error"],
                compute_seconds=compute_seconds,
                node_count=0,
                peak_memory_kb=0,
                killed=False,
                kill_reason=None,
            )

        data = result_holder.get("data", {})
        return SandboxResult(
            success=data.get("success", False),
            result_text=data.get("result", ""),
            latex_result=data.get("latex_result", ""),
            steps=tuple(data.get("steps", [])),
            error=data.get("error"),
            compute_seconds=compute_seconds,
            node_count=data.get("node_count", 0),
            peak_memory_kb=data.get("peak_memory_kb", 0),
            killed=data.get("killed_reason") is not None,
            kill_reason=data.get("killed_reason"),
        )


# Singleton
sympy_sandbox = SympySandbox()
