# System and Threat Model for Trustworthy Timesheet Triage

This document presents the formal security, integrity, and privacy model for the `homecare-visit-triage-agent` system. Designed for inclusion in academic publications, it models the system trust boundaries, hazard capabilities, architectural mitigations, and verification protocols.

---

## 1. System & Threat Model Overview

The triage agent is designed for deployment in regulated healthcare environments where patient privacy (HIPAA) and billing integrity are paramount. We define the system boundary as the boundary between the **untrusted extraction space** (where LLMs, VLMs, or OCR models parse unstructured timesheets) and the **trusted application space** (which processes, scores, and formats billing data).

Our **defensive evaluation architecture** acts as the security boundary, protecting the trusted downstream database from corrupt data and unauthorized disclosures.

```
  [ Untrusted Extraction Space ]           [ Trusted Application Space ]
  (LLMs, VLMs, OCR Engines)               (Triage Core & Verification)
             │
             │ Raw JSON/XLSX
             ▼
      [ Normalizer ] ◄───────────────────── Normalization Boundary
             │
             ├────────────────────────────► [ NameResolver (In-Memory Only) ]
             │                                   ▲
             │                                   │ (Matches secure database)
             ▼                                   ▼
      [ Evaluation ] ◄───────────────────── [ Ground Truth (Secure DB) ]
             │
             ├── [ Triage Gate ] ─────────► [ Human-in-the-Loop Gate ]
             │    (Borderline / Ambiguous)       │ (Hard stop / halt graph)
             ▼                                   ▼
      [ Anonymized Outputs ] ◄───────────────────┘
      (HIPAA-compliant reports)
```

---

## 2. Attacker and Hazard Profile

Rather than assuming a malicious network intruder, the threat model assumes a **non-malicious, unreliable hazard source** (the document extraction model). The extraction engines (VLMs, OCR) exhibit the following capabilities and failure modes:
1.  **Format Incoherence:** Generates text outputs that fail basic format schemas (e.g., unparseable dates or times).
2.  **Arithmetic Hallucination:** Extracts values that are mathematically inconsistent (e.g., individual session hours that do not sum to the reported total daily hours).
3.  **Ambiguous Confidence:** Resolves low-contrast or ambiguous handwriting into highly confident but incorrect extractions.
4.  **PII Leakage:** Directly outputs real patient names and sensitive identifiers into downstream execution contexts.

---

## 3. Security, Integrity, and Privacy Objectives

To guarantee trustworthiness, the system enforces three primary architectural objectives:

*   **Objective A (Privacy/HIPAA Compliance):** Enforce **PHI containment via in-memory identity separation**. Prevent any leakage of Protected Health Information (PHI) to persistent logs, reports, or output directories. Real patient names must exist only in-memory during evaluation and never reach persistent files.
*   **Objective B (Decision and Billing Safety):** Enforce a **human-in-the-loop gate / hard stop**. Prevent low-confidence, borderline, or conflicting extraction outputs from auto-advancing to billing systems. These must be intercepted and routed to human review.
*   **Objective C (Evaluation and Metric Integrity):** Enforce **denominator-preserving evaluation**. Maintain a strict and honest evaluation denominator. Malformed rows cannot be silently dropped; every ingestion failure must be explicitly tracked and accounted for to prevent artificial accuracy inflation.

---

## 4. Architectural Safeguards and Verification Protocols

The table below maps the conceptual threats to the high-level design safeguards implemented in the system, along with the corresponding verification protocols used to validate them.

| Threat | High-Level Design Safeguard | Verification Protocol |
| :--- | :--- | :--- |
| **PII Leakage to Persistent Logs/Outputs** | **PHI Containment via In-Memory Identity Separation:** The system decouples anonymized file identifiers from real patient names. Name resolution (matching anonymized IDs to real names) happens strictly in-memory during evaluation to lookup Ground Truth and is immediately discarded. | **Static Content Scanning:** Automated test suites scan all generated output files (`run_summary.json`, `failures.json`, markdown tables) against a database of known real patient names to verify zero string occurrences. |
| **Unchecked Ambiguity & Confident Guessing** | **Human-in-the-Loop Gate (Hard Stop):** The system analyzes extraction outputs for borderline tolerances and flags. If triggered, it executes a physical state-machine halt (LangGraph interrupt), blocking the automated path and requiring human confirmation to resume. | **State-Machine Boundary Simulation:** HITL tests simulate ambiguous extraction results and verify that the graph halts execution, persists its current state, and rejects completion attempts until explicit reviewer feedback is injected. |
| **Silent Dropping of Malformed Inputs** | **Fail-Closed Normalization:** Raw inputs must conform to strict temporal schemas. Rows failing normalization are routed to an explicit error registry (`normalize_skipped`) rather than being discarded or ignored. | **Negative Format Assertion:** Unit tests supply invalid datetimes to the parser and verify that the system returns structured error types that force the pipeline to increment its error count. |
| **Arithmetic Hallucination Acceptance** | **Self-Diagnostic Arithmetic Validation:** The system computes the internal consistency of raw inputs (summing individual sessions and comparing to total hours) independently of ground truth, establishing an autonomous quality warning signal. | **Consistency Boundary Verification:** Scoring metrics are tested at exact boundaries (e.g., $\le$ and $>$ tolerance limits) to ensure a binary 0/1 compliance outcome with zero partial credit. |

---

## 5. Residual Risk Profile

*   **In-Memory Identity Exposure:** Although patient names are not serialized, they remain in-memory inside the interpreter. A memory-dump attack on the hosting environment remains a vector of exposure.
*   **Decoupled Mapping Security:** The security of the patient name mapping relies entirely on the host environment's access control list (ACL) permissions protecting `name_mapping.db`.
