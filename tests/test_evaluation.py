"""Layer 4: Evaluation Tests — scored against the labeled ground truth dataset.

These tests run against actual input data (not fixtures) and assert on
quantitative accuracy thresholds. This is the dataset evaluation layer —
equivalent to running a model against a benchmark and checking it meets
a minimum bar.

IMPORTANT: These tests require input/ data to exist. They are skipped
automatically if input data is missing (e.g., in CI without data).

IEEE paper narrative:
    Layer 4 produces the numbers in Table 1 of the paper. The tests act
    as regression guards — if a code change causes hours accuracy to drop
    below the observed baseline, the test suite catches it before the paper
    numbers are invalidated.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.config import load_config
from src.evaluation import evaluate_file, evaluate_row
from src.ground_truth import load_ground_truth
from src.ingestion import ingest
from src.metrics import hours_match, time_match
from src.models import GroundTruthRow, NormalizedRow
from src.name_resolver import NameResolver
from src.normalization import normalize_all

# Data paths — skip tests if not present
INPUT_DIR = Path("input")
GT_PATH = INPUT_DIR / "ground_truth.xlsx"
METHOD = "band_crop_vlm_cloud"
MERGED_PATH = INPUT_DIR / METHOD / "merged_results.xlsx"
DB_PATH = INPUT_DIR / METHOD / "name_mapping.db"

has_real_data = pytest.mark.skipif(
    not (GT_PATH.exists() and MERGED_PATH.exists() and DB_PATH.exists()),
    reason="Real input data not available — skipping evaluation layer tests",
)


# ---------------------------------------------------------------------------
# 4.1  Per-field evaluator correctness
# ---------------------------------------------------------------------------

class TestFieldEvaluators:
    """These tests use synthetic data — no real data required."""

    def _make_normed(self, **kwargs) -> NormalizedRow:
        import datetime
        defaults = {
            "source_file": "patient_a_week1.pdf",
            "row_index": 1,
            "date": datetime.date(2026, 1, 7),
            "time_in": datetime.time(7, 0),
            "time_out": datetime.time(15, 0),
            "total_hours": 8.0,
            "calculated_hours": 8.0,
            "status": "accepted",
            "issues": None,
        }
        defaults.update(kwargs)
        return NormalizedRow(**defaults)

    def _make_gt(self, **kwargs) -> GroundTruthRow:
        import datetime
        defaults = {
            "source_file": "Real.Patient-010726-011326.pdf",
            "date": datetime.date(2026, 1, 7),
            "time_in": datetime.time(7, 0),
            "time_out": datetime.time(15, 0),
            "total_hours": 8.0,
        }
        defaults.update(kwargs)
        return GroundTruthRow(**defaults)

    def test_exact_hours_match_scores_1(self):
        config = load_config()
        normed = self._make_normed(total_hours=8.0)
        gt = self._make_gt(total_hours=8.0)
        result = evaluate_row(normed, gt, config)
        hours_eval = next(fe for fe in result.field_evals if fe.field == "total_hours")
        assert hours_eval.score == 1.0

    def test_hours_within_tolerance_scores_1(self):
        config = load_config()
        normed = self._make_normed(total_hours=8.25)   # +15min from 8.0
        gt = self._make_gt(total_hours=8.0)
        result = evaluate_row(normed, gt, config)
        hours_eval = next(fe for fe in result.field_evals if fe.field == "total_hours")
        assert hours_eval.score == 1.0

    def test_hours_over_tolerance_scores_0(self):
        config = load_config()
        normed = self._make_normed(total_hours=8.5)   # +30min from 8.0 → over ±15min
        gt = self._make_gt(total_hours=8.0)
        result = evaluate_row(normed, gt, config)
        hours_eval = next(fe for fe in result.field_evals if fe.field == "total_hours")
        assert hours_eval.score == 0.0

    def test_no_gt_match_produces_unmatched_result(self):
        config = load_config()
        normed = self._make_normed()
        result = evaluate_row(normed, None, config)
        assert result.matched_gt is False
        assert result.fully_correct is False
        assert result.field_evals == []

    def test_eval_result_source_file_is_anonymized(self):
        """RowEvalResult.source_file must never be a real filename."""
        config = load_config()
        normed = self._make_normed(source_file="patient_a_week1.pdf")
        gt = self._make_gt()
        result = evaluate_row(normed, gt, config)
        assert result.source_file == "patient_a_week1.pdf"
        # Must not be the real filename used in GT
        assert result.source_file != gt.source_file


# ---------------------------------------------------------------------------
# 4.2  Dataset evaluation — requires real input data
# ---------------------------------------------------------------------------

@has_real_data
class TestDatasetEvaluation:
    """Run the full evaluation pipeline against real GT data and assert thresholds."""

    @pytest.fixture(scope="class")
    def full_eval_results(self):
        config = load_config()
        rows_raw = ingest(MERGED_PATH)
        rows, _ = normalize_all(rows_raw)
        gt = load_ground_truth(GT_PATH)
        resolver = NameResolver(DB_PATH)
        resolver.set_gt_filenames(list({k[0] for k in gt.keys()}))

        # Evaluate all files that have GT coverage
        from collections import defaultdict
        by_file = defaultdict(list)
        for row in rows:
            by_file[row.source_file].append(row)

        results = []
        for anon_file, file_rows in by_file.items():
            result = evaluate_file(file_rows, gt, resolver, METHOD, config)
            if result.gt_matched_rows > 0:
                results.append(result)
        return results

    def test_at_least_one_file_has_gt_coverage(self, full_eval_results):
        assert len(full_eval_results) > 0, (
            "No files matched GT — name resolver is broken for all patients"
        )

    def test_gt_hours_accuracy_above_minimum_threshold(self, full_eval_results):
        """Primary paper metric: GT Hours Accuracy (±15 min) must be ≥ 60%.

        This is a conservative floor — actual observed performance is ~83%.
        The test catches major regressions without being fragile to small changes.
        """
        all_scores = [
            fe.score
            for r in full_eval_results
            for row_eval in r.row_evals
            for fe in row_eval.field_evals
            if fe.field == "total_hours" and row_eval.matched_gt
        ]
        assert len(all_scores) > 0, "No GT-matched hours scores found"
        accuracy = sum(all_scores) / len(all_scores)
        assert accuracy >= 0.60, (
            f"GT Hours Accuracy {accuracy:.1%} is below minimum threshold 60%"
        )

    def test_no_phi_in_eval_results(self, full_eval_results):
        """All source_file fields in evaluation results must be anonymized."""
        real_names = ["Rivera", "Leal", "Jackson", "Elliott", "Ferguson", "Hanton",
                      "Drewry", "Moran", "Derricott", "Bussa", "Pegram"]
        for file_result in full_eval_results:
            assert not any(n in file_result.source_file for n in real_names), (
                f"PHI LEAK in FileEvalResult.source_file: {file_result.source_file}"
            )
            for row_eval in file_result.row_evals:
                assert not any(n in row_eval.source_file for n in real_names), (
                    f"PHI LEAK in RowEvalResult.source_file: {row_eval.source_file}"
                )

    def test_fully_correct_rate_above_zero(self, full_eval_results):
        """At least some rows should be fully correct (all fields pass)."""
        total_fc = sum(
            1 for r in full_eval_results
            for row_eval in r.row_evals
            if row_eval.matched_gt and row_eval.fully_correct
        )
        assert total_fc > 0, "No fully correct rows — something is wrong with evaluation"

    def test_failures_json_contains_only_anonymized_ids(self, tmp_path):
        """failures.json must not contain real patient names."""
        import json
        from src.reporting import generate_summary, write_artifacts

        config = load_config()
        rows_raw = ingest(MERGED_PATH)
        rows, _ = normalize_all(rows_raw)
        gt = load_ground_truth(GT_PATH)
        resolver = NameResolver(DB_PATH)
        resolver.set_gt_filenames(list({k[0] for k in gt.keys()}))

        from collections import defaultdict
        by_file = defaultdict(list)
        for row in rows:
            by_file[row.source_file].append(row)

        all_results = [
            evaluate_file(file_rows, gt, resolver, METHOD, config)
            for file_rows in by_file.values()
        ]

        out = tmp_path / "phi_test"
        summary = generate_summary(all_results, "phi_test_run", {})
        write_artifacts(summary, out)

        failures_path = out / "summary" / "failures.json"
        assert failures_path.exists()
        failures = json.loads(failures_path.read_text())

        real_names = ["Rivera", "Leal", "Jackson", "Elliott", "Ferguson",
                      "Hanton", "Drewry", "Moran", "Derricott", "Bussa", "Pegram"]
        content = failures_path.read_text()
        for name in real_names:
            assert name not in content, f"PHI LEAK in failures.json: '{name}' found"
