"""LangSmith tracing utilities for the benchmark pipeline.

This module provides a lightweight tracing layer with three modes:

    off              — no tracing; code runs normally
    evaluation_only  — wraps only the evaluate node and evaluate_file calls
    all_tests        — wraps the full pytest run via conftest

Mode is read from LANGSMITH_TRACE_MODE in the environment (or .env):
    LANGSMITH_TRACE_MODE=off
    LANGSMITH_TRACE_MODE=evaluation_only   (default)
    LANGSMITH_TRACE_MODE=all_tests

The LangSmith API key is read from LANGSMITH_API_KEY (already in .env).
Project name is read from LANGSMITH_PROJECT (already in .env).

Usage:
    from src.tracing import get_trace_mode, traceable_evaluation, tracing_ctx

    # Wrap a block with a scoped trace:
    with tracing_ctx("evaluate", tags=["layer:4"], metadata={"method": "band_crop"}):
        result = evaluate_file(...)

    # Or use the decorator on a function:
    @traceable_evaluation(name="my_eval_step")
    def my_step(...):
        ...

Separation of concerns:
    This module ONLY handles tracing wrappers.
    It does not import from graph.py, nodes.py, or test files.
    It may be safely imported anywhere without circular dependencies.
"""

from __future__ import annotations

import contextlib
import logging
import os
from contextlib import contextmanager
from typing import Any, Generator

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Trace mode resolution
# ---------------------------------------------------------------------------

VALID_MODES = {"off", "evaluation_only", "all_tests"}


def get_trace_mode() -> str:
    """Read LANGSMITH_TRACE_MODE from environment.

    Returns one of: "off", "evaluation_only", "all_tests".
    Defaults to "evaluation_only" if not set or invalid.
    """
    raw = os.environ.get("LANGSMITH_TRACE_MODE", "evaluation_only").strip().lower()
    if raw not in VALID_MODES:
        logger.warning(
            "Unknown LANGSMITH_TRACE_MODE=%r — defaulting to 'evaluation_only'. "
            "Valid values: %s",
            raw,
            ", ".join(sorted(VALID_MODES)),
        )
        return "evaluation_only"
    return raw


def is_tracing_active(required_mode: str) -> bool:
    """Return True if the current trace mode is sufficient for required_mode.

    required_mode="evaluation_only" → active when mode is evaluation_only or all_tests
    required_mode="all_tests"       → active only when mode is all_tests
    """
    mode = get_trace_mode()
    if mode == "off":
        return False
    if required_mode == "evaluation_only":
        return mode in ("evaluation_only", "all_tests")
    if required_mode == "all_tests":
        return mode == "all_tests"
    return False


# ---------------------------------------------------------------------------
# Scoped tracing context manager
# ---------------------------------------------------------------------------

@contextmanager
def tracing_ctx(
    run_name: str,
    *,
    project_name: str | None = None,
    tags: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    required_mode: str = "evaluation_only",
) -> Generator[None, None, None]:
    """Context manager that wraps a code block in a LangSmith trace.

    If tracing is inactive (mode=off, or required_mode not satisfied), the
    block runs normally with no tracing overhead.

    Args:
        run_name:      Display name for this trace run in LangSmith.
        project_name:  LangSmith project (defaults to LANGSMITH_PROJECT env var).
        tags:          Optional list of string tags (e.g., ["layer:1", "unit"]).
        metadata:      Optional dict of metadata (e.g., {"method": "band_crop"}).
        required_mode: Minimum trace mode required ("evaluation_only" or "all_tests").

    Example:
        with tracing_ctx("evaluate_node", tags=["layer:4"], metadata={"method": m}):
            result = evaluate_file(rows, gt, resolver, method, config)
    """
    if not is_tracing_active(required_mode):
        yield
        return

    try:
        from langsmith import tracing_context
    except ImportError:
        logger.warning("langsmith not installed — tracing disabled")
        yield
        return

    proj = project_name or os.environ.get("LANGSMITH_PROJECT", "visit-triage-agent")

    with tracing_context(
        project_name=proj,
        tags=tags or [],
        metadata=metadata or {},
    ):
        logger.debug("LangSmith trace started: %r (project=%s)", run_name, proj)
        yield
        logger.debug("LangSmith trace ended: %r", run_name)


# ---------------------------------------------------------------------------
# @traceable decorator factory
# ---------------------------------------------------------------------------

def traceable_evaluation(
    *,
    name: str | None = None,
    tags: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    required_mode: str = "evaluation_only",
):
    """Decorator that wraps a function with a LangSmith trace.

    Applies the @langsmith.traceable decorator only when tracing is active.
    If tracing is disabled, the original function is returned unchanged.

    Args:
        name:          Override the run name (defaults to function name).
        tags:          Optional tags list.
        metadata:      Optional metadata dict.
        required_mode: Minimum trace mode required.

    Example:
        @traceable_evaluation(name="evaluate_file", tags=["layer:4"])
        def evaluate_file(rows, gt, resolver, method, config):
            ...
    """
    def decorator(fn):
        if not is_tracing_active(required_mode):
            return fn
        try:
            from langsmith import traceable
        except ImportError:
            logger.warning("langsmith not installed — @traceable_evaluation is a no-op")
            return fn

        traced_fn = traceable(
            name=name or fn.__name__,
            tags=tags or [],
            metadata=metadata or {},
        )(fn)
        return traced_fn

    return decorator
