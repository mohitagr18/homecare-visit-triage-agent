#!/usr/bin/env python3
"""
Corrected Resolver Analysis: Reconciling Ground Truth Mismatch
=============================================================

This script runs a read-only evaluation of the `band_crop_vlm_cloud` method
using a corrected index-based NameResolver and normalized filename matching.
It demonstrates what the benchmark results look like when resolving:
  1. The regex/index mapping bug (matching week numbers to alphabetical indices)
  2. The hyphen vs. space naming mismatch between the DB and ground_truth.xlsx

Usage:
    uv run python docs/paper/run_corrected_resolver.py
"""

from __future__ import annotations

import re
import sqlite3
import sys
from pathlib import Path

# Setup project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.ingestion import ingest
from src.normalization import normalize_all
from src.ground_truth import load_ground_truth

def get_week_num(anon_filename: str) -> int | None:
    """Extract week number sequentially (1 to 30)."""
    match = re.search(r'week(\d+)', anon_filename)
    if match:
        return int(match.group(1))
    
    # Handle symbols
    symbols = { '[': 27, '\\': 28, ']': 29, '^': 30 }
    for s, w in symbols.items():
        if f'patient_{s}' in anon_filename:
            return w
    
    # Fallback to letter index
    match = re.match(r'patient_([a-z])', anon_filename.lower())
    if match:
        char = match.group(1)
        return ord(char) - ord('a') + 1
    return None

def main():
    gt_path = PROJECT_ROOT / "input" / "ground_truth.xlsx"
    db_path = PROJECT_ROOT / "input" / "band_crop_vlm_cloud" / "name_mapping.db"
    merged_path = PROJECT_ROOT / "input" / "band_crop_vlm_cloud" / "merged_results.xlsx"

    if not gt_path.exists() or not db_path.exists() or not merged_path.exists():
        print("Required input files not found. Ensure raw data exists in input/")
        sys.exit(1)

    # 1. Load Ground Truth and normalize keys
    gt = load_ground_truth(gt_path)
    norm_gt = {}
    for (fname, d), row in gt.items():
        clean_fname = fname.replace('-', '').replace(' ', '').lower()
        norm_gt[(clean_fname, d)] = row

    # 2. Get master alphabetical list of real filenames from DB
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT source_files FROM patients LIMIT 1")
    all_files_str = cur.fetchone()[0]
    conn.close()
    master_files = sorted([f.strip() for f in all_files_str.split(',') if f.strip()])

    # 3. Ingest and Normalize extraction results
    rows_raw = ingest(merged_path)
    normed, skipped = normalize_all(rows_raw)

    matched_count = 0
    date_hallucinations = 0
    no_gt_patient_coverage = 0
    correct_hours = 0
    total_hours_scored = 0

    print("=" * 80)
    print("  CORRECTED RESOLVER EVALUATION (band_crop_vlm_cloud)")
    print("=" * 80)

    for r in normed:
        week_num = get_week_num(r.source_file)
        if week_num is not None and 1 <= week_num <= len(master_files):
            real_file = master_files[week_num - 1]
            clean_real_file = real_file.replace('-', '').replace(' ', '').lower()
            
            # Check if this patient exists in Ground Truth
            patient_prefix = real_file.split('-')[0].split(' ')[0]
            has_gt_coverage = any(k[0].startswith(patient_prefix) for k in gt.keys())

            if not has_gt_coverage:
                no_gt_patient_coverage += 1
                continue

            gt_key = (clean_real_file, r.date)
            if gt_key in norm_gt:
                matched_count += 1
                gt_row = norm_gt[gt_key]
                if gt_row.total_hours is not None:
                    total_hours_scored += 1
                    if abs(r.total_hours - gt_row.total_hours) <= 0.25: # ±15 min tolerance
                        correct_hours += 1
            else:
                date_hallucinations += 1
        else:
            no_gt_patient_coverage += 1

    accuracy = correct_hours / total_hours_scored if total_hours_scored else 0.0

    print(f"Total Normalized Rows:               {len(normed)}")
    print(f"Ingestion/Normalization Skipped:     {skipped}")
    print(f"No Ground Truth Patient Coverage:     {no_gt_patient_coverage}")
    print(f"Date Extraction Hallucinations:       {date_hallucinations}")
    print(f"Successfully Matched to GT:          {matched_count}")
    print("-" * 80)
    print(f"Scored Hours Accuracy (±15min):      {accuracy * 100:.1f}% ({correct_hours}/{total_hours_scored})")
    print("=" * 80)

if __name__ == "__main__":
    main()
