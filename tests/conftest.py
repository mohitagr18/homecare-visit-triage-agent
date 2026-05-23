"""pytest configuration: load .env and enable LangSmith tracing per mode.

Tracing modes (set LANGSMITH_TRACE_MODE in .env or environment):
    off              — no tracing (default if variable is missing or "off")
    evaluation_only  — traces only the evaluate node (default)
    all_tests        — wraps the entire test session in a LangSmith project context

The entire test suite always runs regardless of tracing mode.
"""

from __future__ import annotations

import os
from dotenv import load_dotenv

# Load .env first so all LangSmith env vars are available before any import
load_dotenv()


def pytest_configure(config):
    """Called early in pytest startup — set up session-level tracing if needed."""
    mode = os.environ.get("LANGSMITH_TRACE_MODE", "evaluation_only").strip().lower()
    if mode == "all_tests":
        _enable_all_tests_tracing()


def _enable_all_tests_tracing():
    """Set LangSmith env vars so the full pytest session is traced as one project."""
    project = os.environ.get("LANGSMITH_PROJECT", "visit-triage-agent-tests")
    # langsmith reads LANGSMITH_TRACING=true to enable background tracing
    os.environ["LANGSMITH_TRACING"] = "true"
    os.environ["LANGSMITH_PROJECT"] = project
    print(f"\n[LangSmith] all_tests tracing enabled → project: {project}")
