"""Layer 1: Unit Tests — node functions and pure functions in isolation.

Tests run WITHOUT the graph. Each test exercises one function directly.
This layer catches logic errors in metric thresholds, parsing, and routing.

IEEE paper narrative:
    Layer 1 proves correctness of individual components. Any failure here
    indicates a broken business rule (e.g., tolerance arithmetic), not a
    system integration problem.
"""

from __future__ import annotations

import datetime

import pytest

from src.metrics import exact_match, hours_match, time_match
from src.models import ExtractionRow, NormalizedRow
from src.normalization import normalize
from src.nodes import triage_decision


# ---------------------------------------------------------------------------
# 1.1  Metric boundary tests
# ---------------------------------------------------------------------------

class TestHoursMatch:
    """Boundary conditions for hours_match (primary paper metric)."""

    def test_exact_match_passes(self):
        assert hours_match(8.0, 8.0, 15) == 1.0

    def test_at_tolerance_boundary_passes(self):
        # 0.25h = 15min exactly — must PASS
        assert hours_match(7.0, 7.25, 15) == 1.0

    def test_one_minute_over_boundary_fails(self):
        # 0.26h ≈ 15.6min — must FAIL
        assert hours_match(7.0, 7.26, 15) == 0.0

    def test_under_tolerance_boundary_passes(self):
        # 0.20h = 12min — under 15min tolerance
        assert hours_match(7.0, 7.20, 15) == 1.0

    def test_negative_diff_same_as_positive(self):
        # Tolerance is symmetric
        assert hours_match(7.25, 7.0, 15) == 1.0
        assert hours_match(7.26, 7.0, 15) == 0.0

    def test_zero_hours_passes_zero_gt(self):
        assert hours_match(0.0, 0.0, 15) == 1.0

    def test_large_diff_fails(self):
        assert hours_match(7.0, 9.0, 15) == 0.0


class TestTimeMatch:
    """Boundary conditions for time_match."""

    def test_exact_match_passes(self):
        assert time_match(datetime.time(8, 0), datetime.time(8, 0), 30) == 1.0

    def test_at_tolerance_boundary_passes(self):
        # 30min diff at ±30min tolerance — must PASS
        assert time_match(datetime.time(8, 0), datetime.time(8, 30), 30) == 1.0

    def test_one_minute_over_boundary_fails(self):
        # 31min diff — must FAIL
        assert time_match(datetime.time(8, 0), datetime.time(8, 31), 30) == 0.0

    def test_earlier_time_symmetric(self):
        assert time_match(datetime.time(8, 30), datetime.time(8, 0), 30) == 1.0
        assert time_match(datetime.time(8, 31), datetime.time(8, 0), 30) == 0.0

    def test_large_diff_fails(self):
        assert time_match(datetime.time(7, 0), datetime.time(15, 0), 30) == 0.0


class TestExactMatch:
    def test_equal_strings_pass(self):
        assert exact_match("foo", "foo") == 1.0

    def test_unequal_strings_fail(self):
        assert exact_match("foo", "bar") == 0.0

    def test_both_none_pass(self):
        assert exact_match(None, None) == 1.0

    def test_one_none_fails(self):
        assert exact_match(None, "foo") == 0.0
        assert exact_match("foo", None) == 0.0


# ---------------------------------------------------------------------------
# 1.2  Normalization edge cases
# ---------------------------------------------------------------------------

class TestNormalize:

    def _make_row(self, **kwargs) -> ExtractionRow:
        defaults = {
            "source_file": "patient_a_week1.pdf",
            "row_index": 1,
            "date": "2026-01-07",
            "time_in": "08:30",
            "time_out": "15:30",
            "total_hours": 7.0,
            "calculated_hours": 7.0,
            "status": "accepted",
            "issues": None,
        }
        defaults.update(kwargs)
        return ExtractionRow(**defaults)

    def test_valid_row_normalizes_correctly(self):
        row = self._make_row()
        result = normalize(row)
        assert result is not None
        assert result.date == datetime.date(2026, 1, 7)
        assert result.time_in == datetime.time(8, 30)
        assert result.time_out == datetime.time(15, 30)
        assert result.total_hours == 7.0

    def test_source_file_preserved_as_anonymized(self):
        """PHI constraint: source_file must never be a real name after normalization."""
        row = self._make_row(source_file="patient_a_week1.pdf")
        result = normalize(row)
        assert result is not None
        assert result.source_file == "patient_a_week1.pdf"
        # Must not contain common real names (basic PHI check)
        for real_name in ["Rivera", "Leal", "Jackson", "Elliott", "Ferguson"]:
            assert real_name not in result.source_file

    def test_empty_time_in_returns_none(self):
        row = self._make_row(time_in="")
        result = normalize(row)
        assert result is None

    def test_empty_time_out_returns_none(self):
        row = self._make_row(time_out="")
        result = normalize(row)
        assert result is None

    def test_invalid_date_returns_none(self):
        row = self._make_row(date="not-a-date")
        result = normalize(row)
        assert result is None

    def test_invalid_time_returns_none(self):
        row = self._make_row(time_in="25:99")
        result = normalize(row)
        assert result is None


# ---------------------------------------------------------------------------
# 1.3  Triage routing (conditional edge logic)
# ---------------------------------------------------------------------------

class TestTriageDecision:

    def _make_state(self, needs_review: bool, flagged: list) -> dict:
        return {
            "needs_review": needs_review,
            "flagged_for_review": flagged,
        }

    def test_routes_to_human_review_when_flagged(self):
        state = self._make_state(True, [{"row_index": 1}])
        assert triage_decision(state) == "human_review"

    def test_routes_to_report_when_clean(self):
        state = self._make_state(False, [])
        assert triage_decision(state) == "report"

    def test_routes_to_report_when_needs_review_false_despite_flagged(self):
        # needs_review=False overrides — should not block (defensive)
        state = self._make_state(False, [{"row_index": 1}])
        assert triage_decision(state) == "report"

    def test_routes_to_report_when_flagged_list_empty(self):
        state = self._make_state(True, [])
        assert triage_decision(state) == "report"


# ---------------------------------------------------------------------------
# 1.4  Name resolver PHI constraint
# ---------------------------------------------------------------------------

class TestNameResolverPHI:
    """Verify real names never appear in NormalizedRow output."""

    def test_normalized_row_never_contains_real_name(self):
        """Normalization preserves anonymized filename — no real names injected."""
        row = ExtractionRow(
            source_file="patient_l_week5.pdf",
            row_index=1,
            date="2026-02-18",
            time_in="07:00",
            time_out="15:00",
            total_hours=8.0,
            calculated_hours=8.0,
            status="accepted",
            issues=None,
        )
        normed = normalize(row)
        assert normed is not None
        # These are real names that should NEVER appear after normalization
        for real_name in ["Rivera", "Leal", "Jackson", "Elliott", "Ferguson", "Hanton"]:
            assert real_name not in normed.source_file, (
                f"PHI LEAK: real name '{real_name}' found in NormalizedRow.source_file"
            )

    def test_row_eval_source_file_format(self):
        """RowEvalResult source_file must look like an anonymized ID."""
        normed = NormalizedRow(
            source_file="patient_a_week1.pdf",
            row_index=1,
            date=datetime.date(2026, 1, 7),
            time_in=datetime.time(8, 0),
            time_out=datetime.time(15, 0),
            total_hours=8.0,
            calculated_hours=8.0,
            status="accepted",
            issues=None,
        )
        # Format check: must start with "patient_"
        assert normed.source_file.startswith("patient_"), (
            f"source_file does not look anonymized: {normed.source_file!r}"
        )
