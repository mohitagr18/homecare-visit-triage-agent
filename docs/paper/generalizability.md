# Architectural Generalizability of Trustworthy AI Agents in Regulated Domains

This document provides a domain-neutral architectural analysis of the design patterns implemented in the `homecare-visit-triage-agent`. It abstracts the system's core safety and integrity mechanisms and demonstrates how they generalize to other high-consequence, regulated industries (such as healthcare diagnostic routing and clinical trial matching).

---

## 1. Abstract Architectural Patterns

We identify five core design patterns that are decoupled from the specific task of timesheet processing and applicable to any LLM/VLM-driven document triage agent:

```
  Pattern 1: Fail-Closed Normalization  ──►  Ensures all input formats are typed;
                                             unparseable data increments skip rates.
                                             
  Pattern 2: Decoupled Name Resolution  ──►  Maintains privacy by restricting PII
                                             access to temporary, in-memory scopes.
                                             
  Pattern 3: State-Machine Gating       ──►  Physically interrupts execution on
                                             borderline values or extractor flags.
                                             
  Pattern 4: Self-Diagnostic Mapping    ──►  Verifies internal arithmetic/logical
                                             consistency without ground truth.
                                             
  Pattern 5: Denominator Integrity      ──►  Guarantees final reporting accounts
                                             for skipped and flagged entries.
```

### Pattern 1: Fail-Closed Schema Normalization
*   **Definition:** Raw extraction outputs (untyped strings) must be validated and cast to structured, strongly-typed system models before downstream logic occurs. If parsing fails, the record fails closed (is logged as skipped/unparseable) rather than falling back to default values or being ignored.
*   **Significance:** Prevents corrupt model outputs from silently propagating or causing runtime crashes in decision nodes.

### Pattern 2: Decoupled Name Resolution (In-Memory Isolation)
*   **Definition:** The system isolates Protected Health Information (PHI) or Personally Identifiable Information (PII) by working exclusively with anonymized identifiers throughout its state machine. Real identities are resolved temporarily, in-memory, solely to perform matching operations, and are immediately discarded.
*   **Significance:** Minimizes the HIPAA/GDPR attack surface. If the state machine's persistent storage is compromised, no PII is exposed.

### Pattern 3: State-Machine Triage Gating (Physical Interrupts)
*   **Definition:** Low-confidence extraction flags and borderline values (records near tolerance thresholds) are routed to a physical interrupt node. The execution framework enforces a hard stop (blocking progress) until an external supervisor injects an approval/correction command.
*   **Significance:** Replaces soft "prompt-based safety" with hard, state-machine-enforced safety. The agent is physically incapable of making high-risk decisions autonomously.

### Pattern 4: Self-Diagnostic Consistency Validation
*   **Definition:** The system checks that the internal components of an extracted record are logically consistent (e.g., verifying that itemized values sum to the reported total, or that anatomical terms match the scan type).
*   **Significance:** Enables real-time quality control in production environments where ground truth labels are unavailable.

### Pattern 5: Denominator Integrity in Reporting
*   **Definition:** Evaluation metrics must represent the entire raw dataset. The system accounts for skipped, flagged, and corrected rows, rather than only scoring rows that completed successfully.
*   **Significance:** Prevents "silent data loss," where a model appears highly accurate only because its failures were excluded from the evaluation denominator.

---

## 2. Transferability to Other Regulated Domains

### Case Study 1: Clinical Trial Eligibility Triage
Consider an agent matching patients to oncology clinical trials by extracting criteria (lab results, genetic mutations, and treatment history) from Electronic Health Records (EHRs):

*   **Fail-Closed Schema Normalization:** Lab values (e.g., Platelet Count = `150k`) must be parsed into numeric types. If a value is unparseable (e.g., `not recorded` or corrupted text), the patient is flagged as "eligibility unknown" rather than being matched or ignored.
*   **Decoupled Name Resolution:** The trial matching engine processes patients using anonymized EHR keys. Real patient names are resolved in-memory only when looking up trial exclusion lists and are never stored in match logs.
*   **State-Machine Triage Gating:** If a patient's lab value falls borderline close to the trial criteria (e.g., Creatinine = `1.49 mg/dL` where the trial limit is `1.5 mg/dL`), the agent is blocked from sending an auto-invitation. The pipeline halts, routing the patient record to an oncologist's dashboard for verification.

### Case Study 2: Autonomous Radiology Report Coding
Consider a system extracting billing and diagnostic codes (ICD-10) from unstructured radiology reports (e.g., chest X-ray findings):

*   **Self-Diagnostic Consistency:** The system verifies that the anatomical codes extracted (e.g., lung nodules) match the scan order type (e.g., chest CT). If the codes conflict with the anatomical scope, the system flags the report.
*   **State-Machine Triage Gating:** Laterality conflicts (e.g., the report mentions a fracture in the "left femur" but the scan order specifies "right thigh") trigger a physical graph interrupt, routing the case to a radiologist for clarification before billing submission.

---

## 3. Limitations and Boundaries

While these patterns guarantee high reliability, they introduce specific trade-offs:

1.  **Latency and Throughput Bottlenecks:** Physical interrupts pause execution. In high-throughput, real-time streaming environments, waiting for human decisions can block downstream operations.
2.  **Human Operator Fatigue:** If the extraction models have a high error or flag rate (e.g., our `ocr_only` method with a 79.3% flag rate), the volume of review requests will overwhelm human supervisors. The architecture works best when the underlying model has moderate accuracy, limiting human intervention to true edge cases.
3.  **Lookup Database Synchronization:** The decoupled name resolution pattern depends entirely on the completeness and synchronization of the lookup database. If an anonymized key is missing from the database, the record cannot be evaluated, creating a coverage gap.
