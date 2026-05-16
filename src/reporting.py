"""Generate run summary artifacts and the paper-ready markdown table.

Writes to output/{run_id}/summary/:
    run_summary.json  — machine-readable aggregated metrics per method
    paper_table.md    — markdown table ready to paste into the IEEE paper
    failures.json     — rows with GT match but score < 1.0 (for debugging)

PHI CONSTRAINT: All output uses anonymized identifiers only.
Real filenames and patient names NEVER appear in any artifact written here.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, date, time
from pathlib import Path
from typing import Any

from src.models import FileEvalResult, RunSummary

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Custom JSON serializer (handles date/time objects from Pydantic models)
# ---------------------------------------------------------------------------

def _json_default(obj: Any) -> Any:
    if isinstance(obj, (date, time)):
        return obj.isoformat()
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


# ---------------------------------------------------------------------------
# Summary generation
# ---------------------------------------------------------------------------

def generate_summary(
    file_results: list[FileEvalResult],
    run_id: str,
    config_snapshot: dict[str, Any],
) -> RunSummary:
    """Aggregate FileEvalResults into a RunSummary.

    Args:
        file_results:    All FileEvalResult objects from this run.
        run_id:          Unique run identifier (e.g., "run_20260515_221300").
        config_snapshot: Serialized config dict for reproducibility.

    Returns:
        RunSummary with per-method and aggregate metrics.
    """
    per_method: dict[str, list[FileEvalResult]] = {}
    for result in file_results:
        per_method.setdefault(result.method, []).append(result)

    # Build aggregate per-method statistics
    aggregate: dict[str, dict[str, Any]] = {}
    for method, results in per_method.items():
        all_hours = [r.hours_accuracy for r in results if r.gt_matched_rows > 0]
        all_time_in = [r.time_in_accuracy for r in results if r.gt_matched_rows > 0]
        all_time_out = [r.time_out_accuracy for r in results if r.gt_matched_rows > 0]
        all_fc = [r.fully_correct_rate for r in results if r.gt_matched_rows > 0]
        all_mismatch = [r.hours_mismatch_rate for r in results]

        aggregate[method] = {
            "gt_hours_accuracy": _mean(all_hours),
            "gt_time_in_accuracy": _mean(all_time_in),
            "gt_time_out_accuracy": _mean(all_time_out),
            "fully_correct_rate": _mean(all_fc),
            "hours_mismatch_rate": _mean(all_mismatch),
            "total_files": len(results),
            "total_rows": sum(r.total_rows for r in results),
            "gt_matched_rows": sum(r.gt_matched_rows for r in results),
            "accepted_rows": sum(r.accepted_rows for r in results),
            "flagged_rows": sum(r.flagged_rows for r in results),
        }

    return RunSummary(
        run_id=run_id,
        timestamp=datetime.utcnow().isoformat() + "Z",
        methods=list(per_method.keys()),
        config_snapshot=config_snapshot,
        per_method=per_method,
        aggregate=aggregate,
    )


# ---------------------------------------------------------------------------
# Artifact writers
# ---------------------------------------------------------------------------

def write_artifacts(summary: RunSummary, output_dir: Path) -> None:
    """Write all summary artifacts to output_dir/summary/.

    Args:
        summary:    RunSummary from generate_summary().
        output_dir: Run-specific output directory (e.g., output/run_20260515_221300).
    """
    summary_dir = output_dir / "summary"
    summary_dir.mkdir(parents=True, exist_ok=True)

    _write_run_summary(summary, summary_dir)
    _write_paper_table(summary, summary_dir)
    _write_failures(summary, summary_dir)

    logger.info("Summary artifacts written to %s", summary_dir)


def _write_run_summary(summary: RunSummary, summary_dir: Path) -> None:
    """Write run_summary.json — machine-readable full results."""
    path = summary_dir / "run_summary.json"

    # Build a clean serializable dict
    data = {
        "run_id": summary.run_id,
        "timestamp": summary.timestamp,
        "methods": summary.methods,
        "config_snapshot": summary.config_snapshot,
        "aggregate": summary.aggregate,
        "per_method_file_count": {
            method: len(results)
            for method, results in summary.per_method.items()
        },
    }

    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=_json_default)
    logger.info("Written: %s", path)


def _write_paper_table(summary: RunSummary, summary_dir: Path) -> None:
    """Write paper_table.md — IEEE-ready markdown table."""
    path = summary_dir / "paper_table.md"

    lines = [
        "# Benchmark Results",
        "",
        f"Run ID: `{summary.run_id}`  ",
        f"Timestamp: {summary.timestamp}  ",
        f"Hours tolerance: ±{summary.config_snapshot.get('evaluation', {}).get('hours_tolerance_minutes', 15)} min  ",
        f"Time tolerance: ±{summary.config_snapshot.get('evaluation', {}).get('time_tolerance_minutes', 30)} min",
        "",
        "| Method | GT Hours Acc (±15m) | GT Time-In Acc (±30m) | GT Time-Out Acc (±30m) | Fully Correct | Hours Mismatch | Files | GT Rows |",
        "|---|---|---|---|---|---|---|---|",
    ]

    for method in summary.methods:
        agg = summary.aggregate.get(method, {})
        lines.append(
            f"| {method} "
            f"| {_pct(agg.get('gt_hours_accuracy', 0))} "
            f"| {_pct(agg.get('gt_time_in_accuracy', 0))} "
            f"| {_pct(agg.get('gt_time_out_accuracy', 0))} "
            f"| {_pct(agg.get('fully_correct_rate', 0))} "
            f"| {_pct(agg.get('hours_mismatch_rate', 0))} "
            f"| {agg.get('total_files', 0)} "
            f"| {agg.get('gt_matched_rows', 0)} |"
        )

    lines += [
        "",
        "> **Primary metric:** GT Hours Accuracy (±15 min)",
        "> All source files use anonymized identifiers (PHI-safe output).",
    ]

    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
    logger.info("Written: %s", path)


def _write_failures(summary: RunSummary, summary_dir: Path) -> None:
    """Write failures.json — rows with GT match but any score < 1.0."""
    path = summary_dir / "failures.json"
    failures: list[dict[str, Any]] = []

    for method, file_results in summary.per_method.items():
        for file_result in file_results:
            for row_eval in file_result.row_evals:
                if not row_eval.matched_gt:
                    continue
                failed_fields = [fe for fe in row_eval.field_evals if fe.score < 1.0]
                if not failed_fields:
                    continue
                failures.append({
                    "method": method,
                    "source_file": row_eval.source_file,   # anonymized
                    "row_index": row_eval.row_index,
                    "date": row_eval.date,
                    "failed_fields": [
                        {
                            "field": fe.field,
                            "predicted": fe.predicted,
                            "expected": fe.expected,
                            "comment": fe.comment,
                        }
                        for fe in failed_fields
                    ],
                })

    with open(path, "w") as f:
        json.dump(failures, f, indent=2, default=_json_default)
    logger.info("Written: %s (%d failure rows)", path, len(failures))


def write_method_artifacts(
    file_results: list[FileEvalResult],
    method: str,
    output_dir: Path,
) -> None:
    """Write per-method eval JSON to output_dir/{method}/."""
    method_dir = output_dir / method
    method_dir.mkdir(parents=True, exist_ok=True)

    eval_path = method_dir / f"{method}_eval.json"
    data = [r.model_dump() for r in file_results]

    with open(eval_path, "w") as f:
        json.dump(data, f, indent=2, default=_json_default)
    logger.info("Written: %s (%d file results)", eval_path, len(file_results))


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"
