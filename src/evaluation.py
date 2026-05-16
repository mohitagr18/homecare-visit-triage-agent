"""Per-row and per-file evaluation against ground truth.

PHI CONSTRAINT: Real filenames are used ONLY as internal GT lookup keys.
They are passed in via the resolver, used for dict lookup, then discarded.
All output objects (RowEvalResult, FileEvalResult) use anonymized source_file only.

One-way dependency: evaluation.py imports metrics, models, name_resolver.
It does NOT import nodes.py or graph.py.
"""

from __future__ import annotations

import datetime
import logging
from typing import TYPE_CHECKING

from src.config import AppConfig
from src.metrics import hours_match, time_match
from src.models import (
    FieldEval,
    FileEvalResult,
    GroundTruthRow,
    NormalizedRow,
    RowEvalResult,
)

if TYPE_CHECKING:
    from src.name_resolver import NameResolver

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Per-field evaluators
# ---------------------------------------------------------------------------

def eval_hours(
    predicted: float, expected: float, tolerance_minutes: int
) -> FieldEval:
    """Evaluate total_hours field."""
    score = hours_match(predicted, expected, tolerance_minutes)
    diff_min = abs(predicted - expected) * 60
    comment = (
        f"PASS (diff={diff_min:.1f}min ≤ {tolerance_minutes}min)"
        if score == 1.0
        else f"FAIL (diff={diff_min:.1f}min > {tolerance_minutes}min)"
    )
    return FieldEval(
        field="total_hours",
        predicted=predicted,
        expected=expected,
        score=score,
        comment=comment,
    )


def eval_time_in(
    predicted: datetime.time, expected: datetime.time, tolerance_minutes: int
) -> FieldEval:
    """Evaluate time_in field."""
    score = time_match(predicted, expected, tolerance_minutes)
    pred_min = predicted.hour * 60 + predicted.minute
    exp_min = expected.hour * 60 + expected.minute
    diff_min = abs(pred_min - exp_min)
    comment = (
        f"PASS (diff={diff_min}min ≤ {tolerance_minutes}min)"
        if score == 1.0
        else f"FAIL (diff={diff_min}min > {tolerance_minutes}min)"
    )
    return FieldEval(
        field="time_in",
        predicted=str(predicted),
        expected=str(expected),
        score=score,
        comment=comment,
    )


def eval_time_out(
    predicted: datetime.time, expected: datetime.time, tolerance_minutes: int
) -> FieldEval:
    """Evaluate time_out field."""
    score = time_match(predicted, expected, tolerance_minutes)
    pred_min = predicted.hour * 60 + predicted.minute
    exp_min = expected.hour * 60 + expected.minute
    diff_min = abs(pred_min - exp_min)
    comment = (
        f"PASS (diff={diff_min}min ≤ {tolerance_minutes}min)"
        if score == 1.0
        else f"FAIL (diff={diff_min}min > {tolerance_minutes}min)"
    )
    return FieldEval(
        field="time_out",
        predicted=str(predicted),
        expected=str(expected),
        score=score,
        comment=comment,
    )


# ---------------------------------------------------------------------------
# Per-row evaluator
# ---------------------------------------------------------------------------

def evaluate_row(
    row: NormalizedRow,
    gt_row: GroundTruthRow | None,
    config: AppConfig,
) -> RowEvalResult:
    """Evaluate one normalized row against its ground truth row.

    Args:
        row:     Normalized extraction row (anonymized source_file).
        gt_row:  Matching GT row, or None if no GT was found for this (file, date).
        config:  AppConfig with evaluation tolerances.

    Returns:
        RowEvalResult with scores. source_file is always anonymized.
    """
    tol_hours = config.evaluation.hours_tolerance_minutes
    tol_time = config.evaluation.time_tolerance_minutes

    if gt_row is None:
        # No GT match — cannot score
        return RowEvalResult(
            source_file=row.source_file,
            row_index=row.row_index,
            date=row.date,
            field_evals=[],
            fully_correct=False,
            matched_gt=False,
            flagged_for_review=False,
        )

    field_evals: list[FieldEval] = []

    # Evaluate total_hours (primary metric)
    if gt_row.total_hours is not None:
        field_evals.append(eval_hours(row.total_hours, gt_row.total_hours, tol_hours))

    # Evaluate time_in
    if gt_row.time_in is not None:
        field_evals.append(eval_time_in(row.time_in, gt_row.time_in, tol_time))

    # Evaluate time_out
    if gt_row.time_out is not None:
        field_evals.append(eval_time_out(row.time_out, gt_row.time_out, tol_time))

    scored = [fe for fe in field_evals if fe.score is not None]
    fully_correct = all(fe.score == 1.0 for fe in scored) if scored else False

    # Determine if this row needs HITL review
    flagged = _needs_review(row, gt_row, field_evals, config)

    return RowEvalResult(
        source_file=row.source_file,   # anonymized — NEVER real name
        row_index=row.row_index,
        date=row.date,
        field_evals=field_evals,
        fully_correct=fully_correct,
        matched_gt=True,
        flagged_for_review=flagged,
    )


def _needs_review(
    row: NormalizedRow,
    gt_row: GroundTruthRow,
    field_evals: list[FieldEval],
    config: AppConfig,
) -> bool:
    """Return True if this row should be routed to the HITL review gate.

    Review is triggered by:
    1. Extraction status is 'flagged' but values match GT (validator disagreed with GT)
    2. Hours mismatch is within tolerance but borderline (diff > 10min for ±15min tolerance)
    """
    tol_hours = config.evaluation.hours_tolerance_minutes

    # Rule 1: flagged by extractor but GT says it's correct
    if config.evaluation.review_flagged_matching_gt:
        hours_eval = next((fe for fe in field_evals if fe.field == "total_hours"), None)
        if row.status == "flagged" and hours_eval and hours_eval.score == 1.0:
            return True

    # Rule 2: hours within tolerance but borderline (> 2/3 of tolerance used)
    if config.evaluation.review_borderline_hours:
        hours_eval = next((fe for fe in field_evals if fe.field == "total_hours"), None)
        if hours_eval and gt_row.total_hours is not None:
            diff_min = abs(row.total_hours - gt_row.total_hours) * 60
            borderline_threshold = tol_hours * 2 / 3   # e.g., 10min for ±15min tolerance
            if 0 < diff_min > borderline_threshold and hours_eval.score == 1.0:
                return True

    return False


# ---------------------------------------------------------------------------
# Per-file evaluator
# ---------------------------------------------------------------------------

def evaluate_file(
    rows: list[NormalizedRow],
    gt_lookup: dict[tuple[str, datetime.date], GroundTruthRow],
    resolver: "NameResolver",
    method: str,
    config: AppConfig,
) -> FileEvalResult:
    """Evaluate all rows for one anonymized source file.

    Args:
        rows:       All NormalizedRow objects for this source file (same source_file).
        gt_lookup:  {(real_filename, date): GroundTruthRow} — internal, never in output.
        resolver:   NameResolver for in-memory anon→real resolution.
        method:     Method name (e.g., "band_crop_vlm_cloud").
        config:     AppConfig.

    Returns:
        FileEvalResult with aggregated metrics. source_file is always anonymized.
    """
    if not rows:
        raise ValueError("evaluate_file called with empty rows list")

    anon_file = rows[0].source_file  # all rows share the same anonymized filename

    row_evals: list[RowEvalResult] = []
    for row in rows:
        # Resolve per-row using the row's actual date for accurate multi-week matching
        # Real filename used ONLY as dict lookup key — never stored in output
        real_file = resolver.resolve_for_date(anon_file, row.date)
        gt_key = (real_file, row.date) if real_file else None
        gt_row = gt_lookup.get(gt_key) if gt_key else None
        row_eval = evaluate_row(row, gt_row, config)
        row_evals.append(row_eval)

    # Aggregated metrics
    matched = [r for r in row_evals if r.matched_gt]
    unmatched = [r for r in row_evals if not r.matched_gt]

    if unmatched:
        if len(unmatched) == len(row_evals):
            # Try to see if this is a date anomaly vs missing patient
            real_file_any = resolver.resolve_for_date(anon_file, rows[0].date)
            if real_file_any:
                dates = sorted(list(set(str(r.date) for r in rows)))
                logger.warning(
                    "DATA ANOMALY: %s resolved to a known patient, but 0/%d extracted dates matched GT. "
                    "Extracted dates: %s. This likely indicates an extraction pipeline error (e.g., misread year/month).",
                    anon_file, len(rows), dates
                )
            else:
                logger.debug(
                    "%s: %d/%d rows have no GT match (GT coverage gap)",
                    anon_file, len(unmatched), len(row_evals),
                )
        else:
            logger.debug(
                "%s: %d/%d rows have no GT match (GT coverage gap)",
                anon_file, len(unmatched), len(row_evals),
            )

    hours_scores = [
        fe.score
        for r in matched
        for fe in r.field_evals
        if fe.field == "total_hours"
    ]
    time_in_scores = [
        fe.score
        for r in matched
        for fe in r.field_evals
        if fe.field == "time_in"
    ]
    time_out_scores = [
        fe.score
        for r in matched
        for fe in r.field_evals
        if fe.field == "time_out"
    ]
    fully_correct_flags = [r.fully_correct for r in matched]

    def _accuracy(scores: list[float]) -> float:
        return sum(scores) / len(scores) if scores else 0.0

    # Hours mismatch rate: internal metric (no GT needed)
    # Rows where total_hours != calculated_hours (beyond floating point tolerance)
    mismatch_rows = [
        r for r in rows
        if r.calculated_hours is not None
        and abs(r.total_hours - r.calculated_hours) > 0.01
    ]
    hours_mismatch_rate = len(mismatch_rows) / len(rows) if rows else 0.0

    return FileEvalResult(
        method=method,
        source_file=anon_file,          # anonymized — NEVER real name
        total_rows=len(rows),
        accepted_rows=sum(1 for r in rows if r.status == "accepted"),
        flagged_rows=sum(1 for r in rows if r.status == "flagged"),
        gt_matched_rows=len(matched),
        row_evals=row_evals,
        hours_accuracy=_accuracy(hours_scores),
        time_in_accuracy=_accuracy(time_in_scores),
        time_out_accuracy=_accuracy(time_out_scores),
        fully_correct_rate=_accuracy([1.0 if f else 0.0 for f in fully_correct_flags]),
        hours_mismatch_rate=hours_mismatch_rate,
    )
