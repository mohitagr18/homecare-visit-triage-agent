# Case Studies for IEEE Paper: The Four-Layer Testing Architecture

The following concrete examples demonstrate how the four-layer testing architecture provides mathematical and structural proof that the benchmarking engine is trustworthy. These examples map directly to the four layers of the methodology and can be used in the "Results" or "Case Studies" sections of the IEEE paper.

---

## Case Study 1 (Layer 1 - Unit): Enforcing Tolerance Boundaries

**The Scenario:** 
When evaluating timesheets, a strict mathematical boundary must be enforced. If the ground truth dictates 8.0 hours and the model extracts 8.25 hours, a ±15-minute tolerance rule must pass it. However, 8.26 hours (approx. 15.6 minutes) must strictly fail. If the evaluator's math is flawed, the final accuracy metrics reported in the paper are invalid.

**The Execution Example:**
The Layer 1 unit test suite isolates the pure mathematical function `hours_match()` from the rest of the LangGraph state. 
- The test physically injects the boundary condition: `assert hours_match(extracted=8.26, gt=8.0, tolerance=15) == 0.0`. 
- The test asserts that `hours_match(extracted=8.25, gt=8.0, tolerance=15) == 1.0`.

**Significance for the Paper:** 
This proves that the core scoring logic is mechanically sound and deterministic before any VLM output is even ingested. It prevents "silent passes" caused by floating-point rounding errors or flawed business logic.

---

## Case Study 2 (Layer 2 - Integration): Guaranteeing State Consistency 

**The Scenario:** 
A major flaw in many LLM pipelines is "silent data loss." If a model processes 200 rows but hallucinates malformed date formats for 5 of them (e.g., `25:99`), naive pipelines will crash on those 5 rows, drop them, and only evaluate the remaining 195. This artificially inflates the final accuracy percentage because the denominator shrank.

**The Execution Example:**
The Layer 2 integration test suite evaluates the LangGraph workflow end-to-end to prove the graph is a "closed system."
1. **Input:** The graph ingests 200 rows.
2. **Execution:** The `normalize` node encounters the 5 hallucinated dates and correctly skips parsing them into typed `datetime` objects.
3. **Test Verification:** The integration test intercepts the final state and asserts that the total rows ingested exactly equals the sum of successfully evaluated rows plus tracked failures/skips: `len(initial_rows) == len(evaluated_rows) + skipped_count`.

**Significance for the Paper:** 
This proves that malformed LLM outputs cannot silently disappear from the denominator of the final accuracy metric. If an LLM hallucinates gibberish, the graph state machine is mathematically forced to track it and penalize the model in the final score.

---

## Case Study 3 (Layer 3 - HITL): Halting on Ambiguity

**The Scenario:** 
An OCR pipeline flags a signature on a timesheet as "unclear", but the extracted mathematical values (8.0 hours) perfectly match the Ground Truth (8.0 hours). If an autonomous agent encounters conflicting signals, it often hallucinates a guess. The architecture must physically prohibit autonomous guessing in edge cases.

**The Execution Example:**
1. The synthetic test injects a borderline row into the LangGraph state.
2. The `triage_decision` conditional edge detects the conflict (Validator says "Flagged" but Evaluator says "GT Matched").
3. **Test Verification:** The test mechanically asserts that the graph halts: `assert snapshot.next == ("human_review",)`. 

**Significance for the Paper:** 
The test proves the LangGraph execution physically stops. It waits indefinitely until a human payload is injected (`Command(resume=[{"accept": True}])`). This proves the trust boundary is mechanically enforced by the graph state rather than just being a set of prompting guidelines.

---

## Case Study 4 (Layer 4 - Evaluation): Detecting Temporal Hallucinations

**The Scenario:** 
LLMs frequently suffer from "temporal drift" or hallucinations when reading handwriting (e.g., misreading a year as 2025 instead of 2026). Traditional pipelines simply mark this as a "Missed Row" resulting in 0% accuracy without explaining the root cause.

**The Execution Example:**
During the batch evaluation of the `vlm_full_page` methodology, the pipeline evaluated `patient_p_week16.pdf`. The model hallucinated the year, extracting dates like `2026-12-25`.

**The Pipeline Response:**
Because the pipeline maps the anonymized ID to the true Ground Truth file, it inherently knows the temporal bounds of that specific patient's care. It detected that the extracted dates completely failed to intersect with *any* known ground truth dates for that patient. Instead of silently scoring it `0%`, the pipeline emitted a structural data anomaly warning:

> `WARNING: DATA ANOMALY: patient_p_week16.pdf resolved to a known patient, but 0/10 extracted dates matched GT. Extracted dates: ['2026-12-25', '2026-12-26']. This likely indicates an extraction pipeline error (e.g., misread year/month).`

**Significance for the Paper:** 
The pipeline successfully categorized a failure not just as "wrong hours", but specifically as an upstream temporal hallucination. It demonstrates that ground truth metadata is useful defensively, even for rows it doesn't explicitly label.
