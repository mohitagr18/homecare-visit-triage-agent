"""PHI bridge — maps anonymized filenames to real filenames for GT matching.

THIS MODULE IS THE ONLY PLACE IN THE CODEBASE THAT HANDLES REAL FILENAMES.

Real filenames are returned to evaluation.py for in-memory GT lookup only.
They are NEVER stored in any output artifact, log file, or model field.

name_mapping.db schema:
    Table: patients
    Columns: anonymized_id (e.g. "Patient_L"), real_name (e.g. "N.Rivera"),
             source_files (comma-separated list of all real filenames for this patient)

Matching strategy:
    "patient_l_week5.pdf"
        → extract label "patient_l" → capitalize → "Patient_L"
        → look up Patient_L in DB → real_name = "N.Rivera"
        → find all GT source files that start with "N.Rivera"
        → if multiple (same patient, multiple weeks), use week number to narrow by date range
        → return the single best matching real filename
"""

from __future__ import annotations

import logging
import re
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)


class NameResolver:
    """Loads name_mapping.db and resolves anonymized filenames to real filenames.

    Usage:
        resolver = NameResolver(Path("input/band_crop_vlm_cloud/name_mapping.db"))
        real = resolver.resolve("patient_l_week5.pdf")
        # → "N.Rivera-Timesheets-021826-022426.pdf"  (used internally only)
    """

    def __init__(self, db_path: Path) -> None:
        if not db_path.exists():
            raise FileNotFoundError(f"name_mapping.db not found: {db_path}")

        self._db_path = db_path
        # Load entire mapping into memory — DB is small (< 100 rows)
        self._anon_to_real_name: dict[str, str] = {}     # Patient_L → N.Rivera
        self._real_name_to_files: dict[str, list[str]] = {}  # N.Rivera → [file1, file2]
        self._gt_filenames: list[str] = []    # set via set_gt_filenames() for best matching
        self._load()

    def _load(self) -> None:
        conn = sqlite3.connect(self._db_path)
        try:
            cur = conn.cursor()
            cur.execute("SELECT anonymized_id, real_name, source_files FROM patients")
            for anon_id, real_name, source_files_str in cur.fetchall():
                if not anon_id or not real_name:
                    continue
                self._anon_to_real_name[anon_id.strip()] = real_name.strip()
                # source_files is a comma-separated list of ALL filenames in the system.
                # Filter to only files that belong to this patient (start with real_name prefix).
                if source_files_str:
                    all_files = [f.strip() for f in source_files_str.split(",") if f.strip()]
                    prefix = real_name.strip()
                    patient_files = [f for f in all_files if f.startswith(prefix)]
                    if patient_files:
                        self._real_name_to_files[real_name.strip()] = patient_files
        finally:
            conn.close()
        logger.debug(
            "NameResolver loaded %d patient mappings from %s",
            len(self._anon_to_real_name), self._db_path.name,
        )

    def set_gt_filenames(self, gt_filenames: list[str]) -> None:
        """Register GT filenames so resolve() can cross-reference them.

        Call this after loading ground truth, before any resolve() calls.
        The GT filenames contain real names — internal use only.
        """
        self._gt_filenames = gt_filenames

    def resolve(self, anon_filename: str) -> str | None:
        """Map an anonymized filename to its real filename.

        Matching strategy:
        1. Extract patient label from anon filename → look up real_name in DB
        2. If GT filenames are registered, find the GT file that best matches
           (same real_name prefix, closest week number by date range)
        3. Fall back to DB source_files list if GT not registered

        Args:
            anon_filename: e.g. "patient_l_week5.pdf"

        Returns:
            Real filename for internal GT lookup, or None if unresolvable.
            Caller MUST NOT store or log this value in output artifacts.
        """
        anon_id = _extract_patient_label(anon_filename)
        if anon_id is None:
            logger.debug("Cannot extract patient label from: %s", anon_filename)
            return None

        real_name = self._anon_to_real_name.get(anon_id)
        if real_name is None:
            logger.debug("No DB entry for patient label: %s (from %s)", anon_id, anon_filename)
            return None

        # Prefer matching against registered GT filenames (most reliable)
        if self._gt_filenames:
            return self._match_against_gt(real_name, anon_filename)

        # Fallback: use DB source_files filtered to this patient
        real_files = self._real_name_to_files.get(real_name, [])
        if not real_files:
            logger.debug("No real files for real_name=%r (filtered from DB)", real_name)
            return None
        if len(real_files) == 1:
            return real_files[0]

        week_num = _extract_week_number(anon_filename)
        if week_num is not None:
            sorted_files = sorted(real_files, key=_extract_date_range_start)
            idx = week_num - 1
            if 0 <= idx < len(sorted_files):
                return sorted_files[idx]

        logger.warning(
            "Multiple DB files for %s (patient: %s) and no GT registered — using first",
            anon_filename, anon_id,
        )
        return real_files[0]

    def _match_against_gt(self, real_name: str, anon_filename: str) -> str | None:
        """Find the best-matching GT filename for this patient.

        Matches by real_name prefix. If multiple GT files exist for the same patient,
        uses date range encoded in the GT filename to find the best match.
        """
        candidates = [
            f for f in self._gt_filenames
            if f.startswith(real_name + "-") or f.startswith(real_name + " ")
        ]

        if not candidates:
            logger.debug("No GT file found for real_name=%r (from %s)", real_name, anon_filename)
            return None

        if len(candidates) == 1:
            return candidates[0]

        # Multiple candidates: sort by start date, return all; caller picks by row date
        # Return the chronologically first for now — evaluate_file handles per-row matching
        sorted_candidates = sorted(candidates, key=_extract_date_range_start)
        return sorted_candidates[0]

    def resolve_for_date(self, anon_filename: str, row_date: "datetime.date") -> str | None:
        """Resolve to the GT filename whose date range contains row_date.

        More precise than resolve() — use this when you have the actual row date.
        """
        import datetime
        anon_id = _extract_patient_label(anon_filename)
        if anon_id is None:
            return None
        real_name = self._anon_to_real_name.get(anon_id)
        if real_name is None:
            return None

        candidates = [
            f for f in self._gt_filenames
            if f.startswith(real_name + "-") or f.startswith(real_name + " ")
        ]
        if not candidates:
            return None
        if len(candidates) == 1:
            return candidates[0]

        # Pick the candidate whose encoded date range contains row_date
        for candidate in candidates:
            start, end = _parse_date_range(candidate)
            if start and end and start <= row_date <= end:
                return candidate

        # If no range match, fall back to chronologically closest
        sorted_candidates = sorted(candidates, key=_extract_date_range_start)
        return sorted_candidates[0]

    def build_filename_map(
        self, anon_filenames: list[str], gt_filenames: list[str]
    ) -> dict[str, str]:
        """Build a complete anon → real mapping for a list of files.

        Reports unresolvable files (using anonymized names only in the log).

        Args:
            anon_filenames: List from merged_results.xlsx (anonymized).
            gt_filenames: List from ground_truth.xlsx (real — internal only).

        Returns:
            Dict of {anon_filename: real_filename} for resolved pairs.
        """
        result: dict[str, str] = {}
        unresolved: list[str] = []

        for anon in set(anon_filenames):
            real = self.resolve(anon)
            if real is None:
                unresolved.append(anon)
            elif real not in gt_filenames:
                # Resolved to a name not in GT — GT coverage gap, not a resolver error
                logger.debug(
                    "%s → resolved but not in GT (GT coverage gap, not a bug)", anon
                )
                result[anon] = real
            else:
                result[anon] = real

        if unresolved:
            logger.warning(
                "%d anonymized files could not be resolved to GT filenames: %s",
                len(unresolved), unresolved,
            )
        logger.info(
            "Filename map: %d resolved, %d unresolved out of %d unique files",
            len(result), len(unresolved), len(set(anon_filenames)),
        )
        return result


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _extract_patient_label(anon_filename: str) -> str | None:
    """Extract the DB patient key from an anonymized filename.

    "patient_l_week5.pdf" → "Patient_L"
    "patient_a_week1.pdf" → "Patient_A"
    """
    match = re.match(r"patient_([a-z])(?:_week\d+)?\.pdf", anon_filename.lower())
    if match:
        letter = match.group(1).upper()
        return f"Patient_{letter}"
    return None


def _extract_week_number(anon_filename: str) -> int | None:
    """Extract the week number from an anonymized filename.

    "patient_l_week5.pdf" → 5
    "patient_a_week1.pdf" → 1
    """
    match = re.search(r"_week(\d+)\.pdf", anon_filename.lower())
    if match:
        return int(match.group(1))
    return None


def _extract_date_range_start(real_filename: str) -> str:
    """Extract start date string for chronological sorting.

    "N.Rivera-Timesheets-021826-022426.pdf" → "021826"
    Falls back to full filename for stable sort.
    """
    match = re.search(r"-(\d{6})-\d{6}", real_filename)
    if match:
        return match.group(1)
    return real_filename


def _parse_date_range(
    real_filename: str,
) -> tuple["datetime.date | None", "datetime.date | None"]:
    """Parse the MMDDYY-MMDDYY date range encoded in a real filename.

    "N.Rivera-Timesheets-021826-022426.pdf" → (date(2026,2,18), date(2026,2,24))
    Returns (None, None) if parsing fails.
    """
    import datetime
    match = re.search(r"-(\d{2})(\d{2})(\d{2})-(\d{2})(\d{2})(\d{2})", real_filename)
    if not match:
        return None, None
    try:
        m1, d1, y1, m2, d2, y2 = match.groups()
        start = datetime.date(2000 + int(y1), int(m1), int(d1))
        end = datetime.date(2000 + int(y2), int(m2), int(d2))
        return start, end
    except ValueError:
        return None, None
