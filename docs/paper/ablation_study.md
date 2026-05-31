# Ablation Study: Defensive Evaluation Architecture vs. Naive Pipeline

This document presents the empirical findings of the ablation study conducted on the **homecare-visit-triage-agent**. The study evaluates the effectiveness of our **defensive evaluation architecture** by comparing it to a simulated "naive" pipeline across multiple dimensions, using the extraction outputs of six document processing methods.

For a visual flowchart of these two paths, see the side-by-side conceptual comparison in [ieee_diagrams.md Section 5](../../workflows/ieee_diagrams.md#5-ablation-concept-naive-vs-architecture-protected-data-flow).

---

## 1. Executive Summary

A naive **trustworthy document-processing pipeline** typically processes extracted data end-to-end without validating schemas, checking mathematical self-consistency, filtering patient identifiers from persistent logs, or enforcing physical gates on low-confidence predictions. 

By analyzing the data processed by our **defensive evaluation architecture**, we found that:
1.  **10.5% of all rows (86/821)** were malformed and skipped during ingestion. A naive pipeline would silently drop these, inflating accuracy metrics. Our architecture enforces **denominator-preserving evaluation**.
2.  **23.7% of rows (174/735)** were flagged by the extractor itself, and **50 rows** triggered the **human-in-the-loop gate** (a physical hard stop). A naive pipeline would auto-accept these.
3.  **21.4% of rows (157/735)** had internal arithmetic inconsistencies (total hours did not equal the sum of session intervals). A naive pipeline would accept these without validation.
4.  **0 PHI leaks** were found in our output files, demonstrating robust **PHI containment via in-memory identity separation**.

---

## 2. Dimension 1: Denominator-Preserving Evaluation vs. Silent Dropping

When extracting timesheet data from visual or textual sources, models frequently produce malformed dates or unparseable text. Our architecture enforces **fail-closed normalization** and tracks skipped rows in `normalize_skipped` to keep the evaluation denominator honest. A naive pipeline silently drops these rows.

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
Without **denominator-preserving evaluation**, a reviewer would see a clean run for `ocr_only` with 29 rows processed. The fact that **34.1% of the input data was lost** would remain hidden. Our architecture ensures that all malformed rows are explicitly accounted for in the final system diagnostics.

---

## 3. Dimension 2: Human-in-the-Loop Gate (Hard Stop) vs. Confident Guessing

Borderline cases (e.g., hours close to tolerance boundaries) and extractor self-flags are routed to a **human-in-the-loop gate**. Our architecture executes a physical **hard stop** (LangGraph interrupt) until an administrator resolves the conflict. A naive pipeline auto-accepts these rows, leading to high-risk automated decision-making.

| Method | Normalized Rows | Extractor Flagged | Extractor Flag Rate | HITL Flagged |
| :--- | :---: | :---: | :---: | :---: |
| **band_crop_vlm_cloud** | 216 | 36 | 16.7% | 7 |
| **layout_guided_vlm_cloud** | 197 | 32 | 16.2% | 4 |
| **layout_guided_vlm_local** | 146 | 30 | 20.5% | 4 |
| **ocr_only** | 29 | 23 | 79.3% | 11 |
| **ppocr_grid** | 37 | 31 | 83.8% | 13 |
| **vlm_full_page** | 110 | 22 | 20.0% | 11 |
| **TOTAL** | **735** | **174** | **23.7%** | **50** |

### Analysis
*   **Extractor Flags:** 174 rows (23.7%) triggered internal extractor flags. In a naive setup, these warnings are discarded, and potentially corrupt extractions proceed to billing.
*   **HITL Review:** 50 critical rows triggered the **human-in-the-loop gate**. The protected pipeline physically halts (LangGraph interrupt) until a human verifies the conflict. The naive pipeline silently auto-approves them.

---

## 4. Dimension 3: PHI Containment via In-Memory Identity Separation

The pipeline must perform name matching against ground truth files containing real patient names. The NameResolver encapsulates this mapping, ensuring real names remain strictly in-memory during evaluation and never escape to persistent files.

*   **Real patient name mappings loaded:** 12 names (Rivera, Leal, Jackson, Elliott, Ferguson, Hanton, Drewry, Moran, Derricott, Bussa, Pegram, etc.)
*   **Output files scanned for PHI leaks:** 9 files (including `run_summary.json`, `failures.json`, and per-method evaluation reports)
*   **Leaks found:** 0

### Analysis
A naive pipeline matching names against ground truth would typically output real patient names into debug logs, evaluation tables, and mismatch reports (`failures.json`). Under HIPAA, this constitutes an unauthorized disclosure. Our **PHI containment** architecture restricts real names to in-memory lookup keys, writing only anonymized patient IDs (e.g., `Patient_L`) to disk.

---

## 5. Dimension 4: Self-Diagnostic Arithmetic Validation

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

## 6. Dimension 5: Accuracy Context (Defensive Evaluation Architecture)

The table below summarizes the micro-level accuracy compared with the architectural context that accompanies it.

| Method | Micro-Acc (Row Match) | GT Matched Rows | Skipped Rows | Extractor Flags | HITL Reviews | Math Mismatch |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **band_crop_vlm_cloud** | 78.4% | 171 | 5 | 36 | 7 | 12.0% |
| **layout_guided_vlm_cloud** | 72.9% | 155 | 7 | 32 | 4 | 10.2% |
| **layout_guided_vlm_local** | 63.9% | 108 | 0 | 30 | 4 | 22.6% |
| **ocr_only** | 51.7% | 29 | 15 | 23 | 11 | 86.2% |
| **ppocr_grid** | 47.2% | 36 | 27 | 31 | 13 | 75.7% |
| **vlm_full_page** | 68.2% | 85 | 32 | 22 | 11 | 22.7% |

> [!NOTE]
> - **Micro-Accuracy:** Measures accuracy directly at the row level across the entire ground truth set.
> - **Macro-Accuracy:** Measures the average of the file-level accuracy scores (reported in `paper_table.md` as 85.4% for `band_crop_vlm_cloud` and 79.2% for `layout_guided_vlm_cloud`). Both methods are valid; macro-averaging weighs each file/patient equally, while micro-averaging weighs each row equally.

### Conclusion
While the underlying model capability is identical between the two setups, the reporting is fundamentally different:
*   **A naive pipeline** reports a single, optimistic number: **"78.4% micro-accuracy"**, implying the entire dataset was processed cleanly.
*   **The protected pipeline** reports: **"78.4% micro-accuracy, but with 5 rows skipped, 16.7% flagged by the extractor, 7 rows sent to HITL, and 12.0% exhibiting arithmetic errors."**

Our **defensive evaluation architecture** ensures that the reliability of agentic workflows in healthcare is transparent, auditable, and secure.

---

## 7. Concrete Execution Case Studies & Notes

The following examples and methodology case studies demonstrate how the stateful safety architecture mathematically proves the pipeline's trustworthiness.

### Case Study A: Unsupervised Detection of Date Extraction Anomalies
One of the significant advantages of the **defensive evaluation architecture** is its ability to surface critical data quality anomalies without relying on perfect, 100% complete ground truth coverage.

During pipeline evaluation across a dataset with sparse ground truth labels, the pipeline evaluated a patient (`Patient_C`) who successfully resolved via the **in-memory identity separation** bridge. The extracted dates were:
- `2025-01-14`
- `2025-01-15`
- `2025-12-03`

However, the known ground truth temporal bounds for this patient were:
- `2025-12-24` to `2025-12-30`
- `2025-12-31` to `2026-01-06`

Instead of silently reporting a `0% Accuracy` or `No Ground Truth Match`, the benchmarker raised a **Data Anomaly Warning**:
> `DATA ANOMALY: patient_c_week3.pdf resolved to a known patient, but 0/3 extracted dates matched GT. Extracted dates: ['2025-01-14', '2025-01-15', '2025-12-03']. This likely indicates an extraction pipeline error (e.g., misread year/month).`

**Why this matters for the paper:**
1.  **Defensive Evaluation:** It proves that ground truth is useful even for rows it doesn't explicitly label. The mere existence of temporal bounds acts as a constraint mechanism to audit un-annotated rows.
2.  **Early Warning System:** Misreading a year (e.g., 2026 read as 2025) is a common VLM failure mode. This catches systemic biases deterministically before they pollute billing systems.

### Case Study B: Guaranteeing State Consistency (Layer 2 - Integration Testing)
A major flaw in many LLM pipelines is "silent data loss." If a model processes 200 rows but hallucinate malformed date formats for 5 of them (e.g., `25:99`), naive pipelines crash on those 5 rows, drop them, and only evaluate the remaining 195, artificially inflating accuracy.

**The Execution Example:**
The integration test suite evaluates the LangGraph workflow end-to-end to prove it is a closed system:
1.  The graph ingests rows.
2.  The `normalize` node encounters hallucinated dates and skips parsing them.
3.  The integration test intercepts the final state and asserts that the total rows ingested exactly equals the sum of successfully evaluated rows plus tracked failures/skips: `len(initial_rows) == len(evaluated_rows) + skipped_count`.

**Significance:** It proves malformed LLM outputs cannot silently disappear from the denominator (**denominator-preserving evaluation**). The graph is mathematically forced to penalize the model in the final score.

### Case Study C: Halting on Ambiguity (Layer 3 - HITL Testing)
An OCR pipeline flags a signature as "unclear", but the extracted hours (8.0) perfectly match the Ground Truth (8.0). Autonomous agents often hallucinate a guess in edge cases. The architecture must prohibit this.

**The Execution Example:**
1.  A synthetic test injects a borderline row into the LangGraph state.
2.  The `triage_decision` conditional edge detects the conflict.
3.  The test mechanically asserts that the graph halts (**human-in-the-loop gate / hard stop**): `assert snapshot.next == ("human_review",)`.

**Significance:** The test proves the graph waits indefinitely until a human review payload is injected (`Command(resume=[{"accept": True}])`). This proves the trust boundary is enforced mechanically by the state machine rather than by prompting guidelines.
