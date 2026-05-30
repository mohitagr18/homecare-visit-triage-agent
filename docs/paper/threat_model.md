# Formal Threat Model: Healthcare AI Safety, Integrity, and Privacy

This document maps identified healthcare AI pipeline threats to their corresponding code mitigations and test evidence in the **homecare-visit-triage-agent** system.

---

## 1. System Entry Points and Trust Boundaries

The system is executed as a command-line utility (CLI) or within an automated evaluation pipeline. Data flows from untrusted inputs through a normalization boundary before matching against trusted ground truth.

```
                  [ UNTRUSTED INPUT ZONE ]
   input/{method}/merged_results.xlsx ────┐
   (pre-extracted spreadsheet data)       │
                                          ▼
                                   [ normalization ] ◄── Normalization Boundary
                                          │ (Parsed python objects)
                                          ▼
                                   [ evaluation ]
                                          ▲
   input/{method}/name_mapping.db ────────┼─── (In-memory lookup only)
   (untrusted local mapping DB)           │
                                          ▼
                                  [ NameResolver ]
                                          ▲
   input/ground_truth.xlsx ───────────────┘
   (trusted clinical ground truth)
```

---

## 2. Threat Mitigation and Verification Mapping

The table below maps critical risks to specific implementation files, line numbers, and unit/integration tests.

| Threat ID | Threat / Risk | Mitigating Code Module & Function | Unit / Integration Test Verification |
| :--- | :--- | :--- | :--- |
| **T1** | **Silent Accuracy Inflation:** Malformed rows are discarded without tracking, resulting in an artificially sanitized evaluation denominator. | `normalize_all()` in [normalization.py](file:///Users/mohit/Documents/GitHub/homecare-visit-triage-agent/src/normalization.py#L63-L75) tracks and counts malformed inputs in a `skipped` count, which is stored in the graph state as `normalize_skipped` in `normalize_node()` in [nodes.py](file:///Users/mohit/Documents/GitHub/homecare-visit-triage-agent/src/nodes.py#L88). | `TestNormalize` in [test_unit.py](file:///Users/mohit/Documents/GitHub/homecare-visit-triage-agent/tests/test_unit.py#L99) asserts that rows with invalid formats return `None` (which triggers the skipped count). |
| **T2** | **Unchecked Ambiguity:** The system automatically processes borderline records near tolerance limits, increasing the risk of inaccurate billing. | `_needs_review()` in [evaluation.py](file:///Users/mohit/Documents/GitHub/homecare-visit-triage-agent/src/evaluation.py#L166-L195) flags rows where model status is "flagged" or total hours are borderline (within 2/3 of tolerance range). The `triage_decision` conditional edge routes these to a human-in-the-loop (HITL) gate. | `TestTriageDecision` in [test_unit.py](file:///Users/mohit/Documents/GitHub/homecare-visit-triage-agent/tests/test_unit.py#L160) and `TestHITLInterrupt` in [test_hitl.py](file:///Users/mohit/Documents/GitHub/homecare-visit-triage-agent/tests/test_hitl.py#L59) verify routing logic and pause triggers. |
| **T3** | **PHI Leakage:** Patient identifiers or real names are written to logs, reports, or output directories. | `NameResolver` in [name_resolver.py](file:///Users/mohit/Documents/GitHub/homecare-visit-triage-agent/src/name_resolver.py) resolves anonymized filenames to real filenames *in-memory* only to fetch the corresponding Ground Truth. Real filenames and patient names are never written to disk. All outputs in [reporting.py](file:///Users/mohit/Documents/GitHub/homecare-visit-triage-agent/src/reporting.py) use anonymized names. | `TestNameResolverPHI` in [test_unit.py](file:///Users/mohit/Documents/GitHub/homecare-visit-triage-agent/tests/test_unit.py#L190) and `TestDatasetEvaluation.test_no_phi_in_eval_results` (and `test_failures_json_contains_only_anonymized_ids`) in [test_evaluation.py](file:///Users/mohit/Documents/GitHub/homecare-visit-triage-agent/tests/test_evaluation.py#L178) verify zero occurrences of real patient names. |
| **T4** | **Irreversible Graph Traversal:** Low-confidence or conflict rows proceed directly to final reporting without a hard-stop block for human review. | `builder.compile(interrupt_before=["human_review"])` in [graph.py](file:///Users/mohit/Documents/GitHub/homecare-visit-triage-agent/src/graph.py#L74-L77) enforces a physical interrupt in LangGraph state storage, blocking any execution path from bypassing human review once routed. | `TestHITLInterrupt` and `TestHITLResume` in [test_hitl.py](file:///Users/mohit/Documents/GitHub/homecare-visit-triage-agent/tests/test_hitl.py) check that the graph pauses before `human_review` and only resumes when a resume command containing reviewer decisions is dispatched. |
| **T5** | **Denominator Manipulation:** System metrics are reported without context of skipped or unparseable inputs, leading to an artificially sanitized baseline representation. | The `normalize_skipped` count and the model's self-flags (`extractor_flagged` count) are included in `RunSummary` in [models.py](file:///Users/mohit/Documents/GitHub/homecare-visit-triage-agent/src/models.py) and formatted in the markdown paper table by [reporting.py](file:///Users/mohit/Documents/GitHub/homecare-visit-triage-agent/src/reporting.py) to preserve context. | `TestDatasetEvaluation` in [test_evaluation.py](file:///Users/mohit/Documents/GitHub/homecare-visit-triage-agent/tests/test_evaluation.py#L129) validates that these metrics are written to output files. |
| **T6** | **Temporal Hallucination:** VLM extraction misreads date stamps (such as year or month), producing a plausible date that mismatches the target period. | [evaluation.py](file:///Users/mohit/Documents/GitHub/homecare-visit-triage-agent/src/evaluation.py#L240-L250) detects when all rows for a resolved patient fail to match any ground truth date, logging a specific `DATA ANOMALY` warning. | Verified through self-diagnostics logged in `evaluate_file()`. |
| **T7** | **Tolerance Gaming:** The system utilizes partial credit or rounding metrics to inflate compliance rates. | [metrics.py](file:///Users/mohit/Documents/GitHub/homecare-visit-triage-agent/src/metrics.py) implements binary 0/1 scoring with strict boundaries and zero tolerance for partial credits. | `TestHoursMatch` and `TestTimeMatch` in [test_unit.py](file:///Users/mohit/Documents/GitHub/homecare-visit-triage-agent/tests/test_unit.py#L28) assert exact behavior at tolerance boundaries. |

---

## 3. Residual Risk Analysis

*   **In-Memory Real Names:** Real patient names are loaded into NameResolver's dictionaries during execution. Although they are not written to output files, they remain in-memory. Memory dump attacks on the host environment could theoretically extract them.
*   **SQLite DB Access Control:** The DB file `name_mapping.db` is stored locally. While it is gitignored, the database itself lacks native encryption. Standard file-system permissions must be configured to protect this file.
