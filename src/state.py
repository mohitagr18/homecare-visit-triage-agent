"""BenchmarkState — the single shared state schema for the LangGraph graph.

One-way dependency rule: state.py imports nothing from src/.
All nodes import from state.py; graph.py imports from nodes.py.
"""

from __future__ import annotations

from typing import Any
from typing_extensions import TypedDict


class BenchmarkState(TypedDict, total=False):
    """Shared state flowing through the benchmark LangGraph.

    Fields are populated incrementally as the graph executes.
    Optional fields (total=False) start as missing/None.
    """

    # --- Inputs (set before invoking the graph) ---
    method: str                          # e.g., "band_crop_vlm_cloud"
    merged_path: str                     # path to merged_results.xlsx
    gt_path: str                         # path to ground_truth.xlsx
    db_path: str                         # path to name_mapping.db
    output_dir: str                      # path to run output directory
    config_dict: dict[str, Any]          # serialized AppConfig for reproducibility

    # --- After ingest node ---
    extraction_rows: list[dict[str, Any]]    # list of ExtractionRow.model_dump()

    # --- After normalize node ---
    normalized_rows: list[dict[str, Any]]    # list of NormalizedRow.model_dump()
    normalize_skipped: int                   # rows skipped due to parse failures

    # --- After evaluate node ---
    eval_results: list[dict[str, Any]]       # list of FileEvalResult.model_dump()
    flagged_for_review: list[dict[str, Any]] # RowEvalResult dicts flagged for HITL
    needs_review: bool                       # routing signal for triage edge

    # --- After human_review node (HITL) ---
    human_decisions: list[dict[str, Any]] | None   # reviewer decisions per flagged row

    # --- After report node ---
    summary: dict[str, Any] | None           # RunSummary.model_dump()
    artifacts_written: list[str]             # paths of written output files
