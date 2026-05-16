"""Layer 2: Integration Tests — full graph routing with fixture files.

Tests run the COMPILED GRAPH end-to-end using synthetic fixture data.
No real PHI data is used. This layer catches problems that unit tests cannot:
- State fields missing between nodes
- Conditional edge logic firing on wrong condition
- Pydantic serialization errors mid-graph

IEEE paper narrative:
    Layer 2 proves the graph wires correctly — that clean data flows from
    ingest → normalize → evaluate → report without routing errors, and
    that ambiguous data correctly routes to human_review before report.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from src.graph import build_graph
from src.nodes import triage_decision

FIXTURES = Path(__file__).parent / "fixtures"


def _config() -> dict:
    return {"configurable": {"thread_id": str(uuid4())}}


@pytest.fixture
def graph():
    """Fresh compiled graph for each test (in-memory checkpointer)."""
    return build_graph()


@pytest.fixture
def base_state() -> dict:
    """Base state with fixture paths."""
    return {
        "method": "test_method",
        "merged_path": str(FIXTURES / "clean_merged.xlsx"),
        "gt_path": str(FIXTURES / "ground_truth.xlsx"),
        "db_path": str(FIXTURES / "test.db"),
        "output_dir": str(Path("output") / "test_run"),
        "config_dict": {"evaluation": {"hours_tolerance_minutes": 15, "time_tolerance_minutes": 30}},
    }


# ---------------------------------------------------------------------------
# 2.1  Clean path: ingest → normalize → evaluate → report (no HITL)
# ---------------------------------------------------------------------------

class TestCleanPath:

    def test_clean_file_completes_without_review(self, graph, base_state, tmp_path):
        """Clean data routes ingest → normalize → evaluate → report (no HITL pause)."""
        state = {**base_state, "output_dir": str(tmp_path / "run1")}
        result = graph.invoke(state, _config())

        assert result.get("needs_review") is False
        assert result.get("summary") is not None

    def test_state_populated_through_all_nodes(self, graph, base_state, tmp_path):
        """All state fields are populated after a clean run."""
        state = {**base_state, "output_dir": str(tmp_path / "run2")}
        result = graph.invoke(state, _config())

        assert len(result.get("extraction_rows", [])) > 0, "extraction_rows empty"
        assert len(result.get("normalized_rows", [])) > 0, "normalized_rows empty"
        assert len(result.get("eval_results", [])) > 0, "eval_results empty"
        assert result.get("summary") is not None, "summary not written"

    def test_output_artifacts_written(self, graph, base_state, tmp_path):
        """paper_table.md and run_summary.json are written after clean run."""
        out = tmp_path / "run3"
        state = {**base_state, "output_dir": str(out)}
        graph.invoke(state, _config())

        assert (out / "summary" / "paper_table.md").exists()
        assert (out / "summary" / "run_summary.json").exists()
        assert (out / "summary" / "failures.json").exists()

    def test_output_contains_only_anonymized_filenames(self, graph, base_state, tmp_path):
        """No real patient names appear in any output artifact."""
        out = tmp_path / "run4"
        state = {**base_state, "output_dir": str(out)}
        graph.invoke(state, _config())

        # Read all output files and check for real names
        real_names = ["Rivera", "Leal", "Jackson", "Elliott", "Ferguson", "Hanton"]
        for artifact in out.rglob("*.json"):
            content = artifact.read_text()
            for name in real_names:
                assert name not in content, (
                    f"PHI LEAK: '{name}' found in {artifact.name}"
                )


# ---------------------------------------------------------------------------
# 2.2  Routing: ambiguous data triggers HITL pause
# ---------------------------------------------------------------------------

class TestAmbiguousRouting:

    def test_ambiguous_rows_pause_graph(self, graph, base_state, tmp_path):
        """Ambiguous data (flagged rows matching GT) pauses at human_review."""
        state = {
            **base_state,
            "merged_path": str(FIXTURES / "ambiguous_merged.xlsx"),
            "output_dir": str(tmp_path / "run5"),
        }
        config = _config()
        graph.invoke(state, config)

        snapshot = graph.get_state(config)
        assert snapshot.next == ("human_review",), (
            f"Expected pause at human_review, got: {snapshot.next}"
        )

    def test_needs_review_set_true_when_flagged(self, graph, base_state, tmp_path):
        """needs_review is True when any row triggers triage criteria."""
        state = {
            **base_state,
            "merged_path": str(FIXTURES / "ambiguous_merged.xlsx"),
            "output_dir": str(tmp_path / "run6"),
        }
        config = _config()
        result = graph.invoke(state, config)

        assert result.get("needs_review") is True
        assert len(result.get("flagged_for_review", [])) > 0


# ---------------------------------------------------------------------------
# 2.3  Metrics in output are sane
# ---------------------------------------------------------------------------

class TestSanityOfOutput:

    def test_gt_hours_accuracy_is_float_between_0_and_1(self, graph, base_state, tmp_path):
        state = {**base_state, "output_dir": str(tmp_path / "run7")}
        result = graph.invoke(state, _config())

        summary = result.get("summary", {})
        agg = summary.get("aggregate", {}).get("test_method", {})
        acc = agg.get("gt_hours_accuracy", -1)
        assert 0.0 <= acc <= 1.0, f"hours_accuracy out of range: {acc}"

    def test_paper_table_contains_method_row(self, graph, base_state, tmp_path):
        out = tmp_path / "run8"
        state = {**base_state, "output_dir": str(out)}
        graph.invoke(state, _config())

        table = (out / "summary" / "paper_table.md").read_text()
        assert "test_method" in table
        assert "GT Hours Acc" in table
