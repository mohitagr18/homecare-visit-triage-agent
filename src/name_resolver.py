"""PHI bridge — maps anonymized filenames to real filenames for GT matching.

THIS MODULE IS THE ONLY PLACE IN THE CODEBASE THAT HANDLES REAL FILENAMES.

Real filenames are returned to evaluation.py for in-memory GT lookup only.
They are NEVER stored in any output artifact, log file, or model field.

name_mapping.db schema:
    Table: patients
    Columns: anonymized_id (e.g. "Patient_L"), real_name (e.g. "N.Rivera"),
             source_files (comma-separated list of all real filenames for this patient)

Matching strategy:
    Sequential week index mapping (1 to 30) from the anonymized filename
    directly to the master alphabetical list of real filenames.
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
        self._anon_to_real_name: dict[str, str] = {}     # Patient_L → N.Rivera
        self._real_name_to_files: dict[str, list[str]] = {}  # N.Rivera → [file1, file2]
        self._gt_filenames: list[str] = []    # set via set_gt_filenames() for best matching
        self._master_files: list[str] = []    # Master sorted list of all 30 files in the system
        self._load()

    def _load(self) -> None:
        conn = sqlite3.connect(self._db_path)
        try:
            cur = conn.cursor()
            cur.execute("SELECT anonymized_id, real_name, source_files FROM patients")
            all_files_set = set()
            for anon_id, real_name, source_files_str in cur.fetchall():
                if not anon_id or not real_name:
                    continue
                self._anon_to_real_name[anon_id.strip()] = real_name.strip()
                if source_files_str:
                    files = [f.strip() for f in source_files_str.split(",") if f.strip()]
                    all_files_set.update(files)
                    
                    # Store filtered files for patient prefix as well for compatibility
                    prefix = real_name.strip()
                    patient_files = [f for f in files if f.startswith(prefix)]
                    if patient_files:
                        self._real_name_to_files[real_name.strip()] = patient_files
            
            # Sort alphabetically to establish the sequential mapping mapping: Y-th week file -> index Y-1
            self._master_files = sorted(list(all_files_set))
        finally:
            conn.close()
        logger.debug(
            "NameResolver loaded %d patient mappings and %d master files from %s",
            len(self._anon_to_real_name), len(self._master_files), self._db_path.name,
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
        1. Extract the sequential week index Y from the anonymized filename.
        2. Retrieve the real filename at index Y-1 from the master list.
        3. If GT filenames are registered, normalize spaces and hyphens to return
           the exact filename representation used in the ground truth keys.
        """
        week_num = _extract_week_number(anon_filename)
        if week_num is None or not (1 <= week_num <= len(self._master_files)):
            logger.debug("Cannot resolve week number for: %s", anon_filename)
            # Fall back to letter-based matching for backward compatibility/safety
            anon_id = _extract_patient_label(anon_filename)
            if anon_id is None:
                return None
            real_name = self._anon_to_real_name.get(anon_id)
            if real_name is None:
                return None
            if self._gt_filenames:
                return self._match_against_gt(real_name, anon_filename)
            real_files = self._real_name_to_files.get(real_name, [])
            return real_files[0] if real_files else None

        real_file = self._master_files[week_num - 1]

        # Reconcile hyphen vs space/dot/suffix mismatches if GT filenames are registered
        if self._gt_filenames:
            def _normalize_fn(fname: str) -> str:
                clean = fname.lower().replace('-', '').replace('_', '').replace(' ', '')
                clean = re.sub(r'\.+pdf$', '', clean)
                clean = re.sub(r'\.+$', '', clean)
                clean = re.sub(r'c$', '', clean)
                return clean.strip()

            clean_real = _normalize_fn(real_file)
            for gt_file in self._gt_filenames:
                if _normalize_fn(gt_file) == clean_real:
                    return gt_file

        return real_file


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
        sorted_candidates = sorted(candidates, key=_extract_date_range_start)
        return sorted_candidates[0]

    def resolve_for_date(self, anon_filename: str, row_date: "datetime.date") -> str | None:
        """Resolve to the GT filename. Since week index is 1-to-1, delegates to resolve()."""
        return self.resolve(anon_filename)

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
    """Extract the week number sequentially (1 to 30) from an anonymized filename.

    "patient_l_week5.pdf" → 5
    "patient_a_week1.pdf" → 1
    "patient_\\_week28.pdf" → 28
    """
    match = re.search(r"week(\d+)", anon_filename.lower())
    if match:
        return int(match.group(1))

    # Handle symbol-based filenames
    symbols = { '[': 27, '\\': 28, ']': 29, '^': 30 }
    for s, w in symbols.items():
        if f"patient_{s}" in anon_filename.lower():
            return w

    # Fallback to letter index
    match = re.match(r"patient_([a-z])", anon_filename.lower())
    if match:
        char = match.group(1)
        return ord(char) - ord('a') + 1
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
