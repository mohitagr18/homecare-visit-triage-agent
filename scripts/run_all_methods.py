"""Batch runner for all extraction methods.

Runs the benchmark graph for all methods sequentially, collecting all results,
and generates a single unified summary report (paper_table.md) comparing them.
"""

from __future__ import annotations

import argparse
import datetime
import logging
import sys
from pathlib import Path
from uuid import uuid4

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import load_config
from src.graph import build_graph
from src.ingestion import ingest
from src.models import FileEvalResult
from src.normalization import normalize_all
from src.reporting import generate_summary, write_artifacts, write_method_artifacts

def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
        datefmt="%H:%M:%S",
    )

def main():
    from dotenv import load_dotenv
    load_dotenv()
    
    setup_logging()
    logger = logging.getLogger("run_all_methods")

    config = load_config()

    # The 6 methods to compare
    methods = [
        "band_crop_vlm_cloud",
        "layout_guided_vlm_cloud",
        "layout_guided_vlm_local",
        "ocr_only",
        "ppocr_grid",
        "vlm_full_page",
    ]

    run_id = f"batch_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"
    output_dir = config.output_path / run_id
    output_dir.mkdir(parents=True, exist_ok=True)

    config_dict = {
        "evaluation": {
            "hours_tolerance_minutes": config.evaluation.hours_tolerance_minutes,
            "time_tolerance_minutes": config.evaluation.time_tolerance_minutes,
        }
    }

    all_file_results = []
    g = build_graph()

    for method in methods:
        logger.info("=" * 60)
        logger.info("Running method: %s", method)
        logger.info("=" * 60)

        input_method_dir = config.input_path / method
        merged_path = input_method_dir / "merged_results.xlsx"
        db_path = input_method_dir / "name_mapping.db"
        gt_path = config.ground_truth_path

        if not (merged_path.exists() and db_path.exists()):
            logger.error("Skipping %s — missing merged_results.xlsx or name_mapping.db", method)
            continue

        # Ingest and normalize
        all_rows = ingest(merged_path)
        normed, skipped = normalize_all(all_rows)
        if skipped:
            logger.warning("[%s] Normalization: %d rows skipped", method, skipped)

        thread_id = str(uuid4())
        invoke_config = {"configurable": {"thread_id": thread_id}}

        # State for this method
        initial_state = {
            "method": method,
            "merged_path": str(merged_path),
            "gt_path": str(gt_path),
            "db_path": str(db_path),
            "output_dir": str(output_dir),
            "config_dict": config_dict,
            "extraction_rows": [r.model_dump() for r in all_rows],
            "normalized_rows": [r.model_dump() for r in normed],
        }

        # Run the graph
        result = g.invoke(initial_state, invoke_config)

        # Handle HITL pause (auto-accept since this is an automated batch run)
        snapshot = g.get_state(invoke_config)
        if snapshot.next:
            flagged = result.get("flagged_for_review", [])
            logger.info("[%s] Graph paused for HITL. Auto-accepting %d flagged rows...", method, len(flagged))
            from langgraph.types import Command
            decisions = [{"row_index": r["row_index"], "accept": True} for r in flagged]
            result = g.invoke(Command(resume=decisions), invoke_config)

        # Collect FileEvalResult objects from the report node output
        # Wait, the report node currently writes method artifacts and returns the summary dict.
        # But we need the FileEvalResult objects to aggregate them all at the end.
        # The evaluate node output is saved in result["eval_results"].
        eval_results = result.get("eval_results", [])
        method_file_results = [FileEvalResult(**r) for r in eval_results]
        all_file_results.extend(method_file_results)

        # Write per-method json
        write_method_artifacts(method_file_results, method, output_dir)

    # Generate the unified summary across all methods
    logger.info("=" * 60)
    logger.info("Generating unified paper table for %d methods", len(methods))
    summary = generate_summary(all_file_results, run_id, config_dict)
    write_artifacts(summary, output_dir)

    # Cleanup old runs
    import shutil
    run_dirs = [d for d in config.output_path.iterdir() if d.is_dir() and (d.name.startswith("run_") or d.name.startswith("batch_"))]
    run_dirs.sort(key=lambda d: d.stat().st_mtime, reverse=True)
    for old_run in run_dirs[2:]:
        logger.info("Deleting old run directory: %s", old_run.name)
        shutil.rmtree(old_run, ignore_errors=True)

    logger.info("Batch run complete. Unified table available at:")
    logger.info(str(output_dir / "summary" / "paper_table.md"))

if __name__ == "__main__":
    main()
