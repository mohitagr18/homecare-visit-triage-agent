"""LangGraph node functions for the benchmark pipeline.

One-way dependency:
    nodes.py imports from: state, config, models, ingestion, normalization,
                           ground_truth, name_resolver, evaluation, reporting
    nodes.py does NOT import from graph.py

Each node takes BenchmarkState and returns a partial state update dict.
"""

from __future__ import annotations

import datetime
import logging
from collections import defaultdict
from pathlib import Path
from typing import Any

from langgraph.types import interrupt

from src.config import load_config
from src.evaluation import evaluate_file
from src.ground_truth import load_ground_truth
from src.ingestion import ingest
from src.models import ExtractionRow, NormalizedRow
from src.name_resolver import NameResolver
from src.normalization import normalize_all
from src.reporting import (
    generate_summary,
    write_artifacts,
    write_method_artifacts,
)
from src.state import BenchmarkState
from src.tracing import tracing_ctx

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Node 1: ingest
# ---------------------------------------------------------------------------

def ingest_node(state: BenchmarkState) -> dict[str, Any]:
    """Read merged_results.xlsx → extraction_rows in state.

    If extraction_rows is already populated (e.g., pre-filtered by CLI), skip re-reading.
    """
    if state.get("extraction_rows"):
        logger.info("[%s] ingest: rows already in state (%d rows), skipping re-read",
                    state.get("method", "?"), len(state["extraction_rows"]))
        return {}

    merged_path = Path(state["merged_path"])
    method = state["method"]
    logger.info("[%s] ingest: reading %s", method, merged_path)

    rows = ingest(merged_path)

    logger.info("[%s] ingest: %d rows ingested", method, len(rows))
    return {
        "extraction_rows": [r.model_dump() for r in rows],
    }


# ---------------------------------------------------------------------------
# Node 2: normalize
# ---------------------------------------------------------------------------

def normalize_node(state: BenchmarkState) -> dict[str, Any]:
    """Convert extraction_rows to normalized typed objects.

    If normalized_rows is already populated (e.g., pre-filtered by CLI), skip re-normalizing.
    """
    if state.get("normalized_rows"):
        logger.info("[%s] normalize: rows already in state (%d rows), skipping",
                    state.get("method", "?"), len(state["normalized_rows"]))
        return {}

    method = state["method"]
    raw_rows = [ExtractionRow(**r) for r in state["extraction_rows"]]
    logger.info("[%s] normalize: %d rows to process", method, len(raw_rows))

    normed, skipped = normalize_all(raw_rows)

    logger.info("[%s] normalize: %d OK, %d skipped", method, len(normed), skipped)
    return {
        "normalized_rows": [r.model_dump() for r in normed],
        "normalize_skipped": skipped,
    }


# ---------------------------------------------------------------------------
# Node 3: evaluate
# ---------------------------------------------------------------------------

def evaluate_node(state: BenchmarkState) -> dict[str, Any]:
    """Score normalized rows against ground truth, group by source file."""
    method = state["method"]
    gt_path = Path(state["gt_path"])
    db_path = Path(state["db_path"])

    # Load config
    config = load_config()

    # Load GT and resolver
    gt_lookup = load_ground_truth(gt_path)
    resolver = NameResolver(db_path)
    resolver.set_gt_filenames(list({k[0] for k in gt_lookup.keys()}))

    # Reconstruct NormalizedRow objects
    normed = [NormalizedRow(**r) for r in state["normalized_rows"]]

    # Group by source file
    by_file: dict[str, list[NormalizedRow]] = defaultdict(list)
    for row in normed:
        by_file[row.source_file].append(row)

    logger.info("[%s] evaluate: %d unique source files", method, len(by_file))

    # Evaluate each file — wrapped in a LangSmith trace when mode >= evaluation_only
    file_results = []
    all_flagged: list[dict[str, Any]] = []

    for anon_file, file_rows in by_file.items():
        with tracing_ctx(
            f"evaluate_file:{anon_file}",
            tags=["layer:evaluation", f"method:{method}"],
            metadata={"method": method, "source_file": anon_file, "row_count": len(file_rows)},
            required_mode="evaluation_only",
        ):
            result = evaluate_file(file_rows, gt_lookup, resolver, method, config)
        file_results.append(result)

        # Collect rows flagged for HITL review
        for row_eval in result.row_evals:
            if row_eval.flagged_for_review:
                all_flagged.append({
                    **row_eval.model_dump(),
                    "method": method,
                })

    needs_review = len(all_flagged) > 0
    logger.info(
        "[%s] evaluate: %d file results, %d rows flagged for review",
        method, len(file_results), len(all_flagged),
    )

    return {
        "eval_results": [r.model_dump() for r in file_results],
        "flagged_for_review": all_flagged,
        "needs_review": needs_review,
    }


# ---------------------------------------------------------------------------
# Node 4: human_review (HITL interrupt)
# ---------------------------------------------------------------------------

def human_review_node(state: BenchmarkState) -> dict[str, Any]:
    """HITL interrupt — pause execution for human review of ambiguous rows.

    Execution pauses here. The reviewer sees the flagged rows and provides
    decisions (accept/reject/correct) for each. Graph resumes with decisions.

    Resume with: graph.invoke(Command(resume=[{row_index, accept, corrected_hours}]))
    """
    flagged = state["flagged_for_review"]
    method = state["method"]

    logger.info(
        "[%s] human_review: pausing for %d flagged rows", method, len(flagged)
    )

    # Format flagged rows for reviewer (anonymized only)
    review_payload = {
        "message": (
            f"{len(flagged)} row(s) in method '{method}' flagged for review. "
            "Each row passed extraction validation but triggered a review condition. "
            "Please confirm or correct the hours value."
        ),
        "flagged_rows": [
            {
                "row_index": r["row_index"],
                "source_file": r["source_file"],   # anonymized
                "date": str(r["date"]),
                "field_evals": r["field_evals"],
                "review_reason": (
                    "Extraction flagged but GT matched"
                    if r.get("status") == "flagged"
                    else "Borderline hours within tolerance"
                ),
            }
            for r in flagged
        ],
    }

    # This call pauses the graph and returns control to the caller
    decisions = interrupt(review_payload)

    logger.info("[%s] human_review: resumed with %s", method, type(decisions).__name__)
    return {
        "human_decisions": decisions if isinstance(decisions, list) else [decisions],
    }


# ---------------------------------------------------------------------------
# Node 5: report
# ---------------------------------------------------------------------------

def report_node(state: BenchmarkState) -> dict[str, Any]:
    """Generate summary artifacts and write them to output_dir."""
    from src.models import FileEvalResult

    method = state["method"]
    output_dir = Path(state["output_dir"])
    config_dict = state.get("config_dict", {})

    logger.info("[%s] report: generating summary artifacts", method)

    # Reconstruct FileEvalResult objects
    file_results = [FileEvalResult(**r) for r in state["eval_results"]]

    # Write per-method eval JSON (anonymized)
    write_method_artifacts(file_results, method, output_dir)

    # Generate and write summary
    run_id = output_dir.name
    summary = generate_summary(file_results, run_id, config_dict)
    write_artifacts(summary, output_dir)

    # Log key metric
    agg = summary.aggregate.get(method, {})
    hours_acc = agg.get("gt_hours_accuracy", 0.0)
    logger.info(
        "[%s] report: GT Hours Accuracy = %.1f%% (%d GT-matched rows)",
        method, hours_acc * 100, agg.get("gt_matched_rows", 0),
    )

    artifacts = [
        str(output_dir / "summary" / "run_summary.json"),
        str(output_dir / "summary" / "paper_table.md"),
        str(output_dir / "summary" / "failures.json"),
        str(output_dir / method / f"{method}_eval.json"),
    ]

    return {
        "summary": summary.model_dump(),
        "artifacts_written": artifacts,
    }


# ---------------------------------------------------------------------------
# Conditional edge
# ---------------------------------------------------------------------------

def triage_decision(state: BenchmarkState) -> str:
    """Route to human_review if flagged rows exist, else go straight to report."""
    if state.get("needs_review") and state.get("flagged_for_review"):
        return "human_review"
    return "report"
