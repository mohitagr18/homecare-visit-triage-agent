# Ablation Study: Architecture-Protected vs. Naive Pipeline Comparison

This document presents the findings of the ablation study conducted on the **homecare-visit-triage-agent**. The study evaluates the effectiveness of the system's safety and containment architecture by comparing it to a simulated "naive" pipeline across multiple dimensions, using the evaluation run outputs of six extractor methods.

---

## 1. Executive Summary

A naive healthcare AI pipeline typically processes data end-to-end without validating intermediate structures, checking mathematical self-consistency, filtering patient identifiers from logs, or intercepting low-confidence predictions. 

By analyzing the data processed by our architecture-protected pipeline, we found that:
1. **10.5% of all rows (86/821)** were malformed and skipped during normalization. A naive pipeline would silently drop these, inflating accuracy metrics.
2. **23.7% of rows (174/735)** were flagged by the extractor itself, and **16 rows** triggered the Human-in-the-Loop (HITL) gate. A naive pipeline would auto-accept these.
3. **21.4% of rows (157/735)** had internal arithmetic inconsistencies (total hours did not equal the sum of session intervals). A naive pipeline would accept these without validation.
4. **0 PHI leaks** were found in our output files, despite the NameResolver handling real patient names in-memory. A naive pipeline would have leaked these names into downstream logs and outputs.

---

## 2. Dimension 1: Silent Dropping of Malformed Rows

When extracting timesheet data from visual or textual sources, models frequently produce malformed dates or unparseable text. Our architecture explicitly tracks skipped rows in `normalize_skipped` to keep the evaluation denominator honest. A naive pipeline silently drops these rows.

| Method | Ingested Rows | Skipped Rows | Normalized Rows | Skip Rate | Naive Behavior |
| :--- | :---: | :---: | :---: | :---: | :--- |
| **band_crop_vlm_cloud** | 221 | 5 | 216 | 2.3% | Silently drops 5 rows |
| **layout_guided_vlm_cloud** | 204 | 7 | 197 | 3.4% | Silently drops 7 rows |
| **layout_guided_vlm_local** | 146 | 0 | 146 | 0.0% | 0 rows dropped |
| **ocr_only** | 44 | 15 | 29 | 34.1% | Silently drops 15 rows |
| **ppocr_grid** | 64 | 27 | 37 | 42.2% | Silently drops 27 rows |
| **vlm_full_page** | 142 | 32 | 110 | 22.5% | Silently drops 32 rows |
| **TOTAL** | **821** | **86** | **735** | **10.5%** | **Silently drops 86 rows** |

### Analysis
Without the normalization-skipped tracking, a reviewer would see a clean run for `ocr_only` with 29 rows processed. The fact that **34.1% of the input data was lost** would remain entirely hidden. Our architecture ensures that all malformed rows are accounted for in the system diagnostics.

---

## 3. Dimension 2: Confident Guessing vs. Human Review

Borderline cases (e.g., hours close to the tolerance boundary) and extractor self-flags are routed to a human review gate via LangGraph conditional edges. A naive pipeline auto-accepts these rows, leading to high-risk automated decision-making.

| Method | Normalized Rows | Extractor Flagged | Extractor Flag Rate | HITL Flagged |
| :--- | :---: | :---: | :---: | :---: |
| **band_crop_vlm_cloud** | 216 | 36 | 16.7% | 1 |
| **layout_guided_vlm_cloud** | 197 | 32 | 16.2% | 0 |
| **layout_guided_vlm_local** | 146 | 30 | 20.5% | 2 |
| **ocr_only** | 29 | 23 | 79.3% | 4 |
| **ppocr_grid** | 37 | 31 | 83.8% | 4 |
| **vlm_full_page** | 110 | 22 | 20.0% | 5 |
| **TOTAL** | **735** | **174** | **23.7%** | **16** |

### Analysis
* **Extractor Flags:** 174 rows (23.7%) triggered internal extractor flags. In a naive setup, these warnings are discarded, and potentially corrupt extractions proceed to billing.
* **HITL Review:** 16 critical rows triggered the HITL gate. The protected pipeline physically halts (LangGraph interrupt) until a human verifies the conflict. The naive pipeline silently auto-approves them.

---

## 4. Dimension 3: Protected PHI / Real Name Containment

The pipeline must perform name matching against ground truth files containing real patient names. The NameResolver encapsulates this mapping, ensuring real names remain strictly in-memory during evaluation and never escape to persistent files.

* **Real patient name mappings loaded:** 12 names (Rivera, Leal, Jackson, Elliott, Ferguson, Hanton, Drewry, Moran, Derricott, Bussa, Pegram, etc.)
* **Output files scanned for PHI leaks:** 9 files (including `run_summary.json`, `failures.json`, and per-method evaluation reports)
* **Leaks found:** 0

### Analysis
A naive pipeline matching names against ground truth would typically output real patient names into debug logs, evaluation tables, and mismatch reports (`failures.json`). Under HIPAA, this constitutes an unauthorized disclosure. The protected architecture restricts real names to in-memory lookup keys, writing only anonymized patient IDs to disk.

---

## 5. Dimension 4: Internal Arithmetic Consistency

We compute a self-diagnostic metric, `hours_mismatch_rate`, which measures how often the model's reported `total_hours` disagrees with its own detailed session intervals. This check operates purely on the extraction output without needing ground truth.

| Method | Normalized Rows | Math Mismatches | Mismatch Rate |
| :--- | :---: | :---: | :---: |
| **band_crop_vlm_cloud** | 216 | 26 | 12.0% |
| **layout_guided_vlm_cloud** | 197 | 20 | 10.2% |
| **layout_guided_vlm_local** | 146 | 33 | 22.6% |
| **ocr_only** | 29 | 25 | 86.2% |
| **ppocr_grid** | 37 | 28 | 75.7% |
| **vlm_full_page** | 110 | 25 | 22.7% |
| **TOTAL** | **735** | **157** | **21.4%** |

### Analysis
Across all runs, **21.4% of rows** had internal math inconsistencies. The local OCR pipelines were particularly poor (up to 86.2% mismatch). A naive pipeline treats these numbers as authoritative. The protected pipeline surfaces these discrepancies, allowing the system to flag them for audit.

---

## 6. Dimension 5: Accuracy Context (Honest Reporting)

The following table compares the baseline accuracy with the architectural context that accompanies it.

| Method | Hours Accuracy (GT matched) | GT Matched Rows | Skipped Rows | Extractor Flags | HITL Reviews | Math Mismatch |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **band_crop_vlm_cloud** | 84.6% | 26 | 5 | 36 | 1 | 12.0% |
| **layout_guided_vlm_cloud** | 78.3% | 23 | 7 | 32 | 0 | 10.2% |
| **layout_guided_vlm_local** | 78.6% | 14 | 0 | 30 | 2 | 22.6% |
| **ocr_only** | 75.0% | 8 | 15 | 23 | 4 | 86.2% |
| **ppocr_grid** | 75.0% | 8 | 27 | 31 | 4 | 75.7% |
| **vlm_full_page** | 77.8% | 18 | 32 | 22 | 5 | 22.7% |

### Conclusion
The raw mathematical accuracy score on the evaluated ground-truth subset remains the same (e.g., 84.6% for `band_crop_vlm_cloud`) because both pipelines process the same underlying data with the same models, and malformed rows cannot match ground truth in either setup. 

However, the reporting of this accuracy is fundamentally different:
*   **A naive pipeline** reports a single, optimistic number: **"84.6% hours accuracy"**, implying the entire dataset was processed cleanly.
*   **The protected pipeline** reports: **"84.6% hours accuracy, but with 5 rows skipped, 16.7% flagged by the extractor, 1 row sent to HITL, and 12.0% exhibiting arithmetic errors."**

While the raw model capability is identical, the transparency, auditability, and trustworthiness of the reported metric are completely transformed.
