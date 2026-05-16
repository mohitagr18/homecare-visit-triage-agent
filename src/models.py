"""Pydantic data models for the benchmarking pipeline.

PHI CONSTRAINT: source_file fields in NormalizedRow, RowEvalResult, and FileEvalResult
are ALWAYS anonymized (e.g., "patient_l_week5.pdf"). Real filenames NEVER appear here.
"""

from __future__ import annotations

import datetime
from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Ingestion layer — raw data from merged_results.xlsx
# ---------------------------------------------------------------------------

class ExtractionRow(BaseModel):
    """One row from merged_results.xlsx, as ingested before normalization."""

    source_file: str            # anonymized: "patient_l_week5.pdf"
    row_index: int
    date: str                   # ISO string: "2026-01-07"
    time_in: str                # "HH:MM" e.g. "08:30"
    time_out: str               # "HH:MM" e.g. "15:30"
    total_hours: float
    calculated_hours: float | None
    status: str                 # "accepted" | "flagged"
    issues: str | None


# ---------------------------------------------------------------------------
# Normalization layer — typed Python objects, anonymized filenames
# ---------------------------------------------------------------------------

class NormalizedRow(BaseModel):
    """Post-normalization row with typed date/time objects. PHI-safe."""

    source_file: str             # anonymized — NEVER the real patient filename
    row_index: int
    date: datetime.date
    time_in: datetime.time
    time_out: datetime.time
    total_hours: float
    calculated_hours: float | None
    status: str
    issues: str | None


# ---------------------------------------------------------------------------
# Ground truth — loaded internally for matching (real filenames, not output)
# ---------------------------------------------------------------------------

class GroundTruthRow(BaseModel):
    """One row from ground_truth.xlsx. Contains real filenames — INTERNAL USE ONLY."""

    source_file: str             # real filename — never written to output
    date: datetime.date
    time_in: datetime.time | None
    time_out: datetime.time | None
    total_hours: float | None


# ---------------------------------------------------------------------------
# Evaluation layer
# ---------------------------------------------------------------------------

class FieldEval(BaseModel):
    """Score for a single field comparison."""

    field: str
    predicted: Any
    expected: Any
    score: float                 # 0.0 or 1.0
    comment: str


class RowEvalResult(BaseModel):
    """Evaluation result for one extracted row. PHI-safe."""

    source_file: str             # anonymized — NEVER real patient name
    row_index: int
    date: datetime.date
    field_evals: list[FieldEval] = Field(default_factory=list)
    fully_correct: bool          # True if all scored fields == 1.0
    matched_gt: bool             # True if a GT row was found for this (file, date)
    flagged_for_review: bool = False  # True if this row needs HITL review


class FileEvalResult(BaseModel):
    """Aggregated evaluation for one source file within a method. PHI-safe."""

    method: str
    source_file: str             # anonymized
    total_rows: int
    accepted_rows: int
    flagged_rows: int
    gt_matched_rows: int
    row_evals: list[RowEvalResult] = Field(default_factory=list)
    # Aggregated metrics
    hours_accuracy: float        # primary metric (±15 min)
    time_in_accuracy: float      # ±30 min
    time_out_accuracy: float     # ±30 min
    fully_correct_rate: float
    hours_mismatch_rate: float   # internal: total_hours vs calculated_hours (no GT needed)


class RunSummary(BaseModel):
    """Aggregated results for an entire benchmark run across all methods."""

    run_id: str
    timestamp: str
    methods: list[str]
    config_snapshot: dict[str, Any]
    per_method: dict[str, list[FileEvalResult]] = Field(default_factory=dict)
    # Cross-method aggregates (populated by reporting.py)
    aggregate: dict[str, Any] = Field(default_factory=dict)
