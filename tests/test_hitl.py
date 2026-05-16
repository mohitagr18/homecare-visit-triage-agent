"""Layer 3: HITL Tests — interrupt and resume at the human_review boundary.

These tests prove that the graph:
1. Pauses execution when ambiguous rows are detected
2. Correctly stores state at the interrupt point
3. Resumes from exactly where it paused after receiving human decisions
4. Incorporates human decisions into the final report

This is the most critical testing layer for the IEEE paper because it
demonstrates the human-in-the-loop architecture is testable, not just
described. Without this layer, the HITL gate is untestable from the
outside and therefore untrustworthy.

IEEE paper narrative:
    Layer 3 proves that evaluation pipeline ambiguity is surfaced to a
    human rather than silently resolved by algorithm. The test harness
    simulates a reviewer accepting a flagged row, confirming that the
    graph's execution boundary is both pauseable and resumeable.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from langgraph.types import Command

from src.graph import build_graph

FIXTURES = Path(__file__).parent / "fixtures"


def _config(prefix: str = "hitl") -> dict:
    return {"configurable": {"thread_id": f"{prefix}-{uuid4()}"}}


@pytest.fixture
def graph():
    return build_graph()


@pytest.fixture
def ambiguous_state(tmp_path) -> dict:
    return {
        "method": "test_method",
        "merged_path": str(FIXTURES / "ambiguous_merged.xlsx"),
        "gt_path": str(FIXTURES / "ground_truth.xlsx"),
        "db_path": str(FIXTURES / "test.db"),
        "output_dir": str(tmp_path / "hitl_run"),
        "config_dict": {"evaluation": {"hours_tolerance_minutes": 15, "time_tolerance_minutes": 30}},
    }


# ---------------------------------------------------------------------------
# 3.1  Interrupt behavior
# ---------------------------------------------------------------------------

class TestHITLInterrupt:

    def test_ambiguous_rows_trigger_interrupt(self, graph, ambiguous_state):
        """Graph pauses at human_review when flagged rows are detected."""
        config = _config()
        graph.invoke(ambiguous_state, config)

        snapshot = graph.get_state(config)
        assert snapshot.next == ("human_review",), (
            f"Expected interrupt at human_review, got next={snapshot.next}"
        )

    def test_flagged_rows_in_state_at_interrupt(self, graph, ambiguous_state):
        """flagged_for_review is populated in state before the interrupt."""
        config = _config()
        result = graph.invoke(ambiguous_state, config)

        assert len(result.get("flagged_for_review", [])) > 0, (
            "No flagged rows in state — HITL interrupt was not triggered"
        )

    def test_eval_results_in_state_at_interrupt(self, graph, ambiguous_state):
        """eval_results are present before interrupt — evaluation completed."""
        config = _config()
        result = graph.invoke(ambiguous_state, config)

        assert len(result.get("eval_results", [])) > 0, (
            "eval_results empty at interrupt — evaluate node did not run"
        )

    def test_summary_not_yet_written_at_interrupt(self, graph, ambiguous_state):
        """summary is None before resume — report node has not run yet."""
        config = _config()
        result = graph.invoke(ambiguous_state, config)

        assert result.get("summary") is None, (
            "summary was written before human review completed — HITL was bypassed"
        )

    def test_clean_data_does_not_trigger_interrupt(self, graph, tmp_path):
        """Clean data with no flagged rows skips human_review entirely."""
        state = {
            "method": "test_method",
            "merged_path": str(FIXTURES / "clean_merged.xlsx"),
            "gt_path": str(FIXTURES / "ground_truth.xlsx"),
            "db_path": str(FIXTURES / "test.db"),
            "output_dir": str(tmp_path / "clean_hitl"),
            "config_dict": {"evaluation": {"hours_tolerance_minutes": 15, "time_tolerance_minutes": 30}},
        }
        config = _config()
        result = graph.invoke(state, config)

        snapshot = graph.get_state(config)
        # Graph should be fully complete — no pending nodes
        assert snapshot.next == (), (
            f"Clean run paused unexpectedly at: {snapshot.next}"
        )
        assert result.get("summary") is not None


# ---------------------------------------------------------------------------
# 3.2  Resume behavior
# ---------------------------------------------------------------------------

class TestHITLResume:

    def test_graph_completes_after_resume(self, graph, ambiguous_state):
        """Graph completes successfully after human decision is provided."""
        config = _config()
        graph.invoke(ambiguous_state, config)   # pauses at human_review

        # Simulate human accepting the flagged row
        result = graph.invoke(
            Command(resume=[{"row_index": 1, "accept": True, "comment": "Verified correct"}]),
            config,
        )

        assert result.get("summary") is not None, (
            "summary not written after resume — report node did not run"
        )

    def test_human_decisions_stored_in_state(self, graph, ambiguous_state):
        """human_decisions in state contains the reviewer's input after resume."""
        config = _config()
        graph.invoke(ambiguous_state, config)

        result = graph.invoke(
            Command(resume=[{"row_index": 1, "accept": True}]),
            config,
        )

        decisions = result.get("human_decisions")
        assert decisions is not None, "human_decisions is None after resume"
        assert len(decisions) > 0

    def test_artifacts_written_after_resume(self, graph, ambiguous_state, tmp_path):
        """Output artifacts are written to disk after HITL resume completes."""
        out = tmp_path / "hitl_artifacts"
        state = {**ambiguous_state, "output_dir": str(out)}
        config = _config()
        graph.invoke(state, config)

        graph.invoke(
            Command(resume=[{"row_index": 1, "accept": True}]),
            config,
        )

        assert (out / "summary" / "paper_table.md").exists(), "paper_table.md missing"
        assert (out / "summary" / "run_summary.json").exists(), "run_summary.json missing"

    def test_graph_fully_complete_after_resume(self, graph, ambiguous_state):
        """No pending nodes remain after successful resume."""
        config = _config()
        graph.invoke(ambiguous_state, config)

        graph.invoke(Command(resume=[{"row_index": 1, "accept": True}]), config)

        snapshot = graph.get_state(config)
        assert snapshot.next == (), (
            f"Graph still has pending nodes after resume: {snapshot.next}"
        )
