# Reproducibility & Traceability Guide

This guide provides step-by-step instructions for reproducing the empirical results, ablation study dimensions, and security validation audits reported in the paper.

---

## 1. Environment Setup

The pipeline requires **Python 3.11+** and the **`uv`** package manager for dependency isolation.

### Installation
1. Install `uv` if not already present on the system:
   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```
2. Clone this repository and sync the dependencies to create a locked virtual environment:
   ```bash
   uv sync
   ```
3. Run the test suite to verify the installation:
   ```bash
   uv run pytest
   ```
   *Expected result: 69 tests pass successfully.*

---

## 2. Input Dependencies

The analysis depends on the following gitignored files in the `input/` folder:

1. **Ground Truth Registry (`input/ground_truth.xlsx`):**
   Contains 210 manually annotated clinical timesheet rows representing 23 unique source files.
   *Columns:* [0] Source File (real name), [1] Date (ISO format), [2] Total Hours, [3] Time-In (12h format), [4] Time-Out (12h format), [5] Employee Name.
2. **Method Extractions (`input/{method}/merged_results.xlsx`):**
   Contains untrusted extraction outputs (approx. 225 rows per method across 30 anonymized files) for six different methods:
   - `band_crop_vlm_cloud`
   - `layout_guided_vlm_cloud`
   - `layout_guided_vlm_local`
   - `ocr_only`
   - `ppocr_grid`
   - `vlm_full_page`
3. **Anonymization Databases (`input/{method}/name_mapping.db`):**
   SQLite databases mapping anonymized filename keys (e.g., `Patient_L`) to real patient names (e.g., `N.Rivera`) and source file lists.

---

## 3. Step-by-Step Reproduction

### Step 3.1: Generate the Canonical Benchmark Table
To run the evaluation state machine for all 6 methods sequentially and generate the unified paper table:

```bash
uv run python scripts/run_all_methods.py
```

* **What it does:** Runs the LangGraph state machine for each extraction method. Since this is an automated batch run, the script automatically resumes the graph at the HITL gate (`human_review` node) using a bypass command that approves all flagged rows.
* **Primary Output:** 
  A new batch directory is created under `output/batch_YYYYMMDD_HHMMSS/`. The canonical paper-ready markdown table is written to:
  `output/batch_YYYYMMDD_HHMMSS/summary/paper_table.md`

### Step 3.2: Run the Ablation Study & PHI Audit
To execute the ablation study comparing the simulated "naive" pipeline and the "protected" pipeline:

```bash
uv run python docs/paper/run_ablation.py
```

* **What it does:**
  - Simulates a naive pipeline's behavior by checking how many malformed rows would be silently lost and how many borderline decisions or arithmetic discrepancies would be auto-accepted.
  - Performs a static string audit across all persistent output files to search for known real patient names to verify zero leaks.
  - Outputs a multi-dimensional summary table directly to the console.
* **Primary Output:**
  Generates the raw data file containing all metrics at:
  `docs/paper/ablation_raw_data.json`

---

## 4. Key Output Artifacts & Paper Mapping

When a batch run completes, the following files are produced in the latest `output/batch_*/summary/` folder:

1. **`paper_table.md` (Markdown):**
   A structured table comparing the six extraction methods across metrics including:
   - **GT Hours Acc (±15m):** Total hours matching ground truth within tolerance.
   - **GT Time-In Acc / GT Time-Out Acc (±30m):** Time fields matching ground truth within tolerance.
   - **Fully Correct:** Percentage of matched rows where all fields (hours, time-in, time-out) are correct.
   - **Hours Mismatch:** Percentage of rows showing internal mathematical discrepancies.
2. **`run_summary.json` (JSON):**
   Aggregated machine-readable metrics (including both macro and micro averages) and a snapshot of the evaluation configuration.
3. **`failures.json` (JSON):**
   A detailed debug log mapping anonymized filename identifiers and dates to specific field extraction mismatches, showing the predicted vs. expected values.
