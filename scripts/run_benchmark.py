"""CLI entry point for the benchmark pipeline.

Usage examples:
    # Smoke test — one file
    uv run python scripts/run_benchmark.py --method band_crop_vlm_cloud --file patient_a_week1

    # Two files (state leakage check)
    uv run python scripts/run_benchmark.py --method band_crop_vlm_cloud --limit 2

    # All files
    uv run python scripts/run_benchmark.py --method band_crop_vlm_cloud --all

    # Custom run ID
    uv run python scripts/run_benchmark.py --method band_crop_vlm_cloud --all --run-id paper_final
"""

from __future__ import annotations

import argparse
import datetime
import logging
import shutil
import sys
from pathlib import Path
from uuid import uuid4

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import load_config
from src.graph import build_graph
from src.ingestion import ingest
from src.normalization import normalize_all
from src.models import NormalizedRow


def setup_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
        datefmt="%H:%M:%S",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Benchmark document extraction methods against ground truth.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--method", required=True,
        help="Method name (must match input/{method}/ directory). e.g., band_crop_vlm_cloud",
    )

    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument(
        "--file", metavar="STEM",
        help="Run single file by stem (e.g., patient_a_week1 → patient_a_week1.pdf)",
    )
    scope.add_argument(
        "--limit", type=int, metavar="N",
        help="Run first N unique source files",
    )
    scope.add_argument(
        "--all", dest="run_all", action="store_true",
        help="Run all source files in merged_results.xlsx",
    )

    parser.add_argument(
        "--run-id", default=None,
        help="Custom run ID (default: run_YYYYMMDD_HHMMSS)",
    )
    parser.add_argument(
        "--log-level", default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    parser.add_argument(
        "--skip-review", action="store_true",
        help="Auto-accept all flagged rows and skip human review (useful for automated CI runs)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    setup_logging(args.log_level)
    logger = logging.getLogger("run_benchmark")

    config = load_config()

    # Resolve paths
    method = args.method
    input_method_dir = config.input_path / method
    merged_path = input_method_dir / "merged_results.xlsx"
    db_path = input_method_dir / "name_mapping.db"
    gt_path = config.ground_truth_path

    # Validate paths
    for p, label in [(merged_path, "merged_results.xlsx"), (db_path, "name_mapping.db"), (gt_path, "ground_truth.xlsx")]:
        if not p.exists():
            logger.error("Required file not found: %s (%s)", p, label)
            sys.exit(1)

    # Determine which source files to run
    logger.info("Ingesting %s to determine available source files...", merged_path)
    all_rows = ingest(merged_path)
    normed, skipped = normalize_all(all_rows)
    if skipped:
        logger.warning("Normalization: %d rows skipped", skipped)

    unique_files = list(dict.fromkeys(r.source_file for r in normed))  # preserve order
    logger.info("Found %d unique source files in merged_results.xlsx", len(unique_files))

    if args.file:
        stem = args.file if args.file.endswith(".pdf") else args.file + ".pdf"
        if stem not in unique_files:
            logger.error("File %r not found in merged_results.xlsx", stem)
            logger.info("Available files: %s", unique_files[:5])
            sys.exit(1)
        selected_files = [stem]
    elif args.limit:
        selected_files = unique_files[: args.limit]
        logger.info("Running first %d files (of %d)", args.limit, len(unique_files))
    else:  # --all
        selected_files = unique_files
        logger.info("Running ALL %d files", len(unique_files))

    # Filter normalized rows to selected files
    selected_rows = [r for r in normed if r.source_file in set(selected_files)]
    logger.info("Processing %d rows across %d files", len(selected_rows), len(selected_files))

    # Build run ID and output dir
    run_id = args.run_id or f"run_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"
    output_dir = config.output_path / run_id
    output_dir.mkdir(parents=True, exist_ok=True)

    # Cleanup old runs to keep only the latest 2
    run_dirs = [d for d in config.output_path.iterdir() if d.is_dir() and d.name.startswith("run_")]
    # Sort by modification time, newest first
    run_dirs.sort(key=lambda d: d.stat().st_mtime, reverse=True)
    for old_run in run_dirs[2:]:
        logger.info("Deleting old run directory to keep only latest 2: %s", old_run.name)
        shutil.rmtree(old_run, ignore_errors=True)

    # Serialize config for reproducibility
    config_dict = {
        "evaluation": {
            "hours_tolerance_minutes": config.evaluation.hours_tolerance_minutes,
            "time_tolerance_minutes": config.evaluation.time_tolerance_minutes,
        }
    }

    # Build graph and run
    g = build_graph()
    thread_id = str(uuid4())
    invoke_config = {"configurable": {"thread_id": thread_id}}

    # Pass only the selected (filtered) rows.
    # We pre-populate both extraction_rows and normalized_rows so the ingest/normalize
    # nodes inside the graph still execute (for testing purposes) but using the filtered set.
    # The ingest node will read the full xlsx, but evaluate_node will then use the filtered
    # normalized_rows from state. We achieve file-level filtering by restricting what enters
    # the graph state — the ingest node re-reads all rows but normalize_node and evaluate_node
    # will receive the pre-filtered normalized_rows we set here.
    #
    # NOTE: ingest/normalize nodes will re-run on the full file (that's fine for integration
    # testing). The filter is enforced by only passing selected_rows to evaluate via state.
    selected_set = set(selected_files)
    selected_raw = [r for r in all_rows if r.source_file in selected_set]

    initial_state = {
        "method": method,
        "merged_path": str(merged_path),
        "gt_path": str(gt_path),
        "db_path": str(db_path),
        "output_dir": str(output_dir),
        "config_dict": config_dict,
        # Pre-populate so evaluate node sees only selected files
        "extraction_rows": [r.model_dump() for r in selected_raw],
        "normalized_rows": [r.model_dump() for r in selected_rows],
    }

    logger.info("Starting graph run_id=%s thread_id=%s", run_id, thread_id)

    try:
        result = g.invoke(initial_state, invoke_config)
    except Exception as e:
        logger.error("Graph invocation failed: %s", e)
        raise

    # Check if graph paused for HITL review
    snapshot = g.get_state(invoke_config)
    if snapshot.next:
        flagged = result.get("flagged_for_review", [])
        if getattr(args, "skip_review", False):
            logger.info("Graph paused for HITL. --skip-review is set, auto-accepting %d flagged rows...", len(flagged))
            from langgraph.types import Command
            decisions = [{"row_index": r["row_index"], "accept": True} for r in flagged]
            result = g.invoke(Command(resume=decisions), invoke_config)
            snapshot = g.get_state(invoke_config)
        else:
            logger.warning(
                "Graph paused at: %s. Resume with: graph.invoke(Command(resume=[...]), config)",
                snapshot.next,
            )
            logger.info(
                "Flagged rows: %d — review required before final report",
                len(flagged),
            )

    if not snapshot.next:
        # Completed — print summary
        summary = result.get("summary", {})
        agg = summary.get("aggregate", {}).get(method, {})
        logger.info("=" * 60)
        logger.info("RUN COMPLETE: %s / %s", run_id, method)
        logger.info("GT Hours Accuracy:  %.1f%%", agg.get("gt_hours_accuracy", 0) * 100)
        logger.info("GT Time-In Accuracy: %.1f%%", agg.get("gt_time_in_accuracy", 0) * 100)
        logger.info("GT Time-Out Accuracy: %.1f%%", agg.get("gt_time_out_accuracy", 0) * 100)
        logger.info("Fully Correct Rate:  %.1f%%", agg.get("fully_correct_rate", 0) * 100)
        logger.info("GT Matched Rows:    %d / %d", agg.get("gt_matched_rows", 0), agg.get("total_rows", 0))
        logger.info("=" * 60)
        logger.info("Paper table: %s", output_dir / "summary" / "paper_table.md")


if __name__ == "__main__":
    main()
