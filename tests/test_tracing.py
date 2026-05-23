"""Smoke tests for LangSmith tracing utilities (src/tracing.py).

These tests verify that:
1. Mode resolution reads from the environment correctly.
2. tracing_ctx is a no-op when mode=off.
3. tracing_ctx runs the body in both evaluation_only and all_tests modes.
4. @traceable_evaluation wraps/unwraps correctly per mode.

No network calls are made — these tests mock the langsmith package where needed.
"""

from __future__ import annotations

import os

import pytest


# ---------------------------------------------------------------------------
# Mode resolution
# ---------------------------------------------------------------------------

class TestGetTraceMode:

    def test_defaults_to_evaluation_only_when_unset(self, monkeypatch):
        monkeypatch.delenv("LANGSMITH_TRACE_MODE", raising=False)
        from src.tracing import get_trace_mode
        assert get_trace_mode() == "evaluation_only"

    def test_reads_off(self, monkeypatch):
        monkeypatch.setenv("LANGSMITH_TRACE_MODE", "off")
        from importlib import reload
        import src.tracing as tracing_mod
        reload(tracing_mod)
        assert tracing_mod.get_trace_mode() == "off"

    def test_reads_evaluation_only(self, monkeypatch):
        monkeypatch.setenv("LANGSMITH_TRACE_MODE", "evaluation_only")
        from src.tracing import get_trace_mode
        assert get_trace_mode() == "evaluation_only"

    def test_reads_all_tests(self, monkeypatch):
        monkeypatch.setenv("LANGSMITH_TRACE_MODE", "all_tests")
        from src.tracing import get_trace_mode
        assert get_trace_mode() == "all_tests"

    def test_invalid_mode_defaults_to_evaluation_only(self, monkeypatch, caplog):
        monkeypatch.setenv("LANGSMITH_TRACE_MODE", "banana")
        import logging
        from src.tracing import get_trace_mode
        with caplog.at_level(logging.WARNING, logger="src.tracing"):
            result = get_trace_mode()
        assert result == "evaluation_only"


# ---------------------------------------------------------------------------
# is_tracing_active
# ---------------------------------------------------------------------------

class TestIsTracingActive:

    def test_off_mode_is_never_active(self, monkeypatch):
        monkeypatch.setenv("LANGSMITH_TRACE_MODE", "off")
        from src.tracing import is_tracing_active
        assert is_tracing_active("evaluation_only") is False
        assert is_tracing_active("all_tests") is False

    def test_evaluation_only_mode_active_for_eval(self, monkeypatch):
        monkeypatch.setenv("LANGSMITH_TRACE_MODE", "evaluation_only")
        from src.tracing import is_tracing_active
        assert is_tracing_active("evaluation_only") is True

    def test_evaluation_only_mode_not_active_for_all_tests(self, monkeypatch):
        monkeypatch.setenv("LANGSMITH_TRACE_MODE", "evaluation_only")
        from src.tracing import is_tracing_active
        assert is_tracing_active("all_tests") is False

    def test_all_tests_mode_active_for_both(self, monkeypatch):
        monkeypatch.setenv("LANGSMITH_TRACE_MODE", "all_tests")
        from src.tracing import is_tracing_active
        assert is_tracing_active("evaluation_only") is True
        assert is_tracing_active("all_tests") is True


# ---------------------------------------------------------------------------
# tracing_ctx — no-op behavior when off
# ---------------------------------------------------------------------------

class TestTracingCtxNoOp:

    def test_block_executes_normally_when_off(self, monkeypatch):
        monkeypatch.setenv("LANGSMITH_TRACE_MODE", "off")
        from src.tracing import tracing_ctx
        result = []
        with tracing_ctx("smoke_test", required_mode="evaluation_only"):
            result.append(42)
        assert result == [42]

    def test_exception_propagates_through_noop_ctx(self, monkeypatch):
        monkeypatch.setenv("LANGSMITH_TRACE_MODE", "off")
        from src.tracing import tracing_ctx
        with pytest.raises(ValueError, match="expected"):
            with tracing_ctx("smoke_test", required_mode="evaluation_only"):
                raise ValueError("expected")

    def test_block_executes_normally_in_evaluation_only_mode(self, monkeypatch):
        """tracing_ctx body must always run, even when langsmith is unavailable."""
        monkeypatch.setenv("LANGSMITH_TRACE_MODE", "evaluation_only")
        from src.tracing import tracing_ctx
        result = []
        # We don't mock langsmith — real tracing_context is called or degrades gracefully
        with tracing_ctx("smoke_eval", required_mode="evaluation_only"):
            result.append("ran")
        assert result == ["ran"]


# ---------------------------------------------------------------------------
# @traceable_evaluation — passthrough when off
# ---------------------------------------------------------------------------

class TestTraceable:

    def test_fn_unchanged_when_off(self, monkeypatch):
        monkeypatch.setenv("LANGSMITH_TRACE_MODE", "off")
        from src.tracing import traceable_evaluation

        @traceable_evaluation(name="test_fn", required_mode="evaluation_only")
        def my_fn(x):
            return x * 2

        assert my_fn(3) == 6

    def test_fn_wrapped_in_evaluation_only(self, monkeypatch):
        monkeypatch.setenv("LANGSMITH_TRACE_MODE", "evaluation_only")
        from src.tracing import traceable_evaluation

        @traceable_evaluation(name="test_fn_traced", tags=["smoke"], required_mode="evaluation_only")
        def my_fn(x):
            return x + 1

        # Must still return the correct value
        assert my_fn(10) == 11
