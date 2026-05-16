"""Normalize ExtractionRow → NormalizedRow by converting string types to Python objects.

This layer:
- Parses date strings ("2026-01-07") → datetime.date
- Parses time strings ("08:30") → datetime.time
- Coerces hours to float
- Preserves the anonymized source_file as-is (NEVER calls name resolver)

Real filename resolution happens in evaluation.py — NOT here.
NormalizedRow.source_file is always the anonymized filename.
"""

from __future__ import annotations

import datetime
import logging
from typing import TYPE_CHECKING

from src.models import ExtractionRow, NormalizedRow

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


def normalize(row: ExtractionRow) -> NormalizedRow | None:
    """Convert an ExtractionRow to a NormalizedRow with typed Python objects.

    Returns None if required fields cannot be parsed (row will be counted as skipped).

    Args:
        row: An ExtractionRow from ingestion.py (all fields are strings/floats).

    Returns:
        NormalizedRow with date/time as Python objects, or None on parse failure.
    """
    date_obj = _parse_date(row.date, row.row_index)
    if date_obj is None:
        return None

    time_in = _parse_hhmm_time(row.time_in, row.row_index, "time_in")
    if time_in is None:
        return None

    time_out = _parse_hhmm_time(row.time_out, row.row_index, "time_out")
    if time_out is None:
        return None

    return NormalizedRow(
        source_file=row.source_file,      # anonymized — preserved as-is
        row_index=row.row_index,
        date=date_obj,
        time_in=time_in,
        time_out=time_out,
        total_hours=row.total_hours,
        calculated_hours=row.calculated_hours,
        status=row.status,
        issues=row.issues,
    )


def normalize_all(rows: list[ExtractionRow]) -> tuple[list[NormalizedRow], int]:
    """Normalize a list of ExtractionRows, returning (results, skip_count)."""
    results: list[NormalizedRow] = []
    skipped = 0
    for row in rows:
        norm = normalize(row)
        if norm is None:
            skipped += 1
        else:
            results.append(norm)
    if skipped:
        logger.warning("Normalization: %d rows skipped due to parse failures", skipped)
    return results, skipped


# ---------------------------------------------------------------------------
# Private parse helpers
# ---------------------------------------------------------------------------

def _parse_date(raw: str, row_index: int) -> datetime.date | None:
    """Parse ISO date string → datetime.date. Handles datetime objects too."""
    if isinstance(raw, datetime.datetime):
        return raw.date()
    if isinstance(raw, datetime.date):
        return raw
    s = str(raw).strip()
    # ISO format: "2026-01-07"
    try:
        return datetime.date.fromisoformat(s)
    except ValueError:
        pass
    # Excel serial date (shouldn't happen with openpyxl data_only=True but just in case)
    logger.debug("Row %d — cannot parse date: %r", row_index, raw)
    return None


def _parse_hhmm_time(raw: str, row_index: int, field: str) -> datetime.time | None:
    """Parse HH:MM 24-hour time string → datetime.time.

    merged_results.xlsx uses 24h format (e.g., "08:30", "15:30").
    """
    if isinstance(raw, datetime.time):
        return raw
    if not raw or str(raw).strip() in ("", "None", "nan"):
        logger.debug("Row %d — empty %s", row_index, field)
        return None
    s = str(raw).strip()
    # HH:MM
    try:
        return datetime.time.fromisoformat(s)
    except ValueError:
        pass
    # H:MM (single digit hour)
    try:
        return datetime.datetime.strptime(s, "%H:%M").time()
    except ValueError:
        pass
    logger.debug("Row %d — cannot parse %s: %r", row_index, field, raw)
    return None
