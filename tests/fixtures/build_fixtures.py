"""Build synthetic test fixtures: clean_merged.xlsx, ambiguous_merged.xlsx, test.db.

Run once to create fixtures used by all test layers.
Kept separate so test files don't import openpyxl/sqlite3 directly.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import openpyxl

FIXTURES_DIR = Path(__file__).parent


def make_merged_xlsx(path: Path, rows: list[dict]) -> None:
    """Write a minimal merged_results.xlsx for testing."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Timesheet Data"

    headers = [
        "Source File", "Date", "Time In", "Time Out",
        "Total Hours", "Calculated Hours", "Status", "Issues",
    ]
    ws.append(headers)

    for row in rows:
        ws.append([
            row.get("source_file", ""),
            row.get("date", ""),
            row.get("time_in", ""),
            row.get("time_out", ""),
            row.get("total_hours", 0),
            row.get("calculated_hours", None),
            row.get("status", "accepted"),
            row.get("issues", None),
        ])

    wb.save(path)


def make_gt_xlsx(path: Path, rows: list[dict]) -> None:
    """Write a minimal ground_truth.xlsx for testing (no header, positional columns)."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Timesheet Extract"

    for row in rows:
        ws.append([
            row.get("source_file", ""),   # real filename
            row.get("date", ""),
            row.get("total_hours", 0),
            row.get("time_in", "7:00 AM"),
            row.get("time_out", "3:00 PM"),
            row.get("employee_name", "Test Employee"),
        ])

    wb.save(path)


def make_name_db(path: Path, mappings: list[dict]) -> None:
    """Write a minimal name_mapping.db.

    Each mapping: {anonymized_id, real_name, source_files (comma-sep string)}
    """
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS patients "
        "(anonymized_id TEXT, real_name TEXT, source_files TEXT)"
    )
    for m in mappings:
        conn.execute(
            "INSERT INTO patients VALUES (?, ?, ?)",
            (m["anonymized_id"], m["real_name"], m["source_files"]),
        )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Fixture definitions
# ---------------------------------------------------------------------------

# Patient mapping: Patient_A → Test.Patient (fictional, no real PHI)
DB_MAPPINGS = [
    {
        "anonymized_id": "Patient_A",
        "real_name": "Test.Patient",
        "source_files": "Test.Patient-Timesheets-010726-011326.pdf,Test.Patient-Timesheets-011426-012026.pdf",
    }
]

# Ground truth: real filenames (internal to fixture only — no actual PHI)
GT_ROWS_CLEAN = [
    {
        "source_file": "Test.Patient-Timesheets-010726-011326.pdf",
        "date": "2026-01-07",
        "total_hours": 8.0,
        "time_in": "7:00 AM",
        "time_out": "3:00 PM",
        "employee_name": "Test Employee",
    },
    {
        "source_file": "Test.Patient-Timesheets-010726-011326.pdf",
        "date": "2026-01-08",
        "total_hours": 8.0,
        "time_in": "7:00 AM",
        "time_out": "3:00 PM",
        "employee_name": "Test Employee",
    },
    {
        "source_file": "Test.Patient-Timesheets-010726-011326.pdf",
        "date": "2026-01-09",
        "total_hours": 8.0,
        "time_in": "7:00 AM",
        "time_out": "3:00 PM",
        "employee_name": "Test Employee",
    },
]

# Clean extracted rows — exactly match GT (should score 100%, no HITL trigger)
CLEAN_ROWS = [
    {
        "source_file": "patient_a_week1.pdf",
        "date": "2026-01-07",
        "time_in": "07:00",
        "time_out": "15:00",
        "total_hours": 8.0,
        "calculated_hours": 8.0,
        "status": "accepted",
        "issues": None,
    },
    {
        "source_file": "patient_a_week1.pdf",
        "date": "2026-01-08",
        "time_in": "07:00",
        "time_out": "15:00",
        "total_hours": 8.0,
        "calculated_hours": 8.0,
        "status": "accepted",
        "issues": None,
    },
    {
        "source_file": "patient_a_week1.pdf",
        "date": "2026-01-09",
        "time_in": "07:00",
        "time_out": "15:00",
        "total_hours": 8.0,
        "calculated_hours": 8.0,
        "status": "accepted",
        "issues": None,
    },
]

# Ambiguous rows — extraction flagged a row that actually matches GT
# This triggers the HITL review gate
AMBIGUOUS_ROWS = [
    {
        "source_file": "patient_a_week1.pdf",
        "date": "2026-01-07",
        "time_in": "07:00",
        "time_out": "15:00",
        "total_hours": 8.0,
        "calculated_hours": 8.0,
        "status": "flagged",         # ← flagged by extractor
        "issues": "Signature unclear",
    },
    {
        "source_file": "patient_a_week1.pdf",
        "date": "2026-01-08",
        "time_in": "07:00",
        "time_out": "15:00",
        "total_hours": 8.0,
        "calculated_hours": 8.0,
        "status": "accepted",
        "issues": None,
    },
]


def build_all() -> None:
    """Create all fixture files in tests/fixtures/."""
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)

    # name_mapping.db
    db_path = FIXTURES_DIR / "test.db"
    db_path.unlink(missing_ok=True)
    make_name_db(db_path, DB_MAPPINGS)

    # Ground truth
    gt_path = FIXTURES_DIR / "ground_truth.xlsx"
    make_gt_xlsx(gt_path, GT_ROWS_CLEAN)

    # clean_merged.xlsx
    make_merged_xlsx(FIXTURES_DIR / "clean_merged.xlsx", CLEAN_ROWS)

    # ambiguous_merged.xlsx
    make_merged_xlsx(FIXTURES_DIR / "ambiguous_merged.xlsx", AMBIGUOUS_ROWS)

    print(f"Fixtures written to {FIXTURES_DIR}")
    for f in sorted(FIXTURES_DIR.glob("*")):
        print(f"  {f.name}")


if __name__ == "__main__":
    build_all()
