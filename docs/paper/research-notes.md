# IEEE Paper Research Notes & Case Studies

This document collects findings, methodology examples, and publishable observations designed for inclusion in the IEEE paper.

## Observation: Unsupervised Detection of Date Extraction Anomalies
One of the significant advantages of the four-layer benchmarking architecture is its ability to surface critical data quality anomalies without relying on perfect, 100% complete ground truth coverage.

During pipeline evaluation across a dataset with sparse ground truth labels, the pipeline evaluated a patient (`H.Leal`) who successfully resolved via the PHI-anonymization bridge. The extracted dates were:
- `2025-01-14`
- `2025-01-15`
- `2025-12-03`

However, the known ground truth temporal bounds for this patient were:
- `2025-12-24` to `2025-12-30`
- `2025-12-31` to `2026-01-06`

Instead of silently reporting a `0% Accuracy` or `No Ground Truth Match`, the benchmarker raised a **Data Anomaly Warning**:
> `DATA ANOMALY: patient_c_week3.pdf resolved to a known patient, but 0/3 extracted dates matched GT. Extracted dates: ['2025-01-14', '2025-01-15', '2025-12-03']. This likely indicates an extraction pipeline error (e.g., misread year/month).`

**Why this matters for the paper:**
1. **Defensive Evaluation**: It proves that ground truth is useful even for rows it doesn't explicitly label. The mere existence of temporal bounds acts as a constraint mechanism to audit un-annotated rows.
2. **Early Warning System**: Misreading a year (e.g., 2026 read as 2025) is a common VLM failure mode. This catches systemic biases deterministically before they pollute billing systems.

## Case Studies of Pipeline Guarantees

The following examples demonstrate how the testing architecture mathematically proves the pipeline's trustworthiness. 

### Case Study A: Guaranteeing State Consistency (Layer 2 - Integration)
A major flaw in many LLM pipelines is "silent data loss." If a model processes 200 rows but hallucinates malformed date formats for 5 of them (e.g., `25:99`), naive pipelines crash on those 5 rows, drop them, and only evaluate the remaining 195, artificially inflating accuracy.

**The Execution Example:**
The integration test suite evaluates the LangGraph workflow end-to-end to prove it is a closed system. 
1. The graph ingests rows.
2. The `normalize` node encounters hallucinated dates and skips parsing them.
3. The integration test intercepts the final state and asserts that the total rows ingested exactly equals the sum of successfully evaluated rows plus tracked failures/skips: `len(initial_rows) == len(evaluated_rows) + skipped_count`.

**Significance:** It proves malformed LLM outputs cannot silently disappear from the denominator. The graph is mathematically forced to penalize the model in the final score.

### Case Study B: Halting on Ambiguity (Layer 3 - HITL)
An OCR pipeline flags a signature as "unclear", but the extracted hours (8.0) perfectly match the Ground Truth (8.0). Autonomous agents often hallucinate a guess in edge cases. The architecture must prohibit this.

**The Execution Example:**
1. A synthetic test injects a borderline row into the LangGraph state.
2. The `triage_decision` conditional edge detects the conflict.
3. The test mechanically asserts that the graph halts: `assert snapshot.next == ("human_review",)`.

**Significance:** The test proves the graph waits indefinitely until a human payload is injected (`Command(resume=[{"accept": True}])`). This proves the trust boundary is enforced mechanically by the state machine rather than by prompting guidelines.
