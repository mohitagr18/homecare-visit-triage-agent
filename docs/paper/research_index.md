# Research Artifact Index & Evidence Dashboard

Welcome to the research repository for the **homecare-visit-triage-agent**. This document serves as the primary "start here" page for academic reviewers, mapping out the evidence package, system threats, generalizability arguments, related literature, and reproducibility steps.

---

## 1. Executive Findings Summary (Plain English)

*   **The Problem:** Document processing pipelines in healthcare (e.g., extracting visit timesheets for billing and payroll) are increasingly powered by unreliable AI extractors (VLMs, OCR). A naive pipeline processes this data end-to-end without validation, leading to silent data loss, mathematical hallucinations, and Patient Health Information (PHI) leaks.
*   **The Solution:** This repository demonstrates a **defensive evaluation architecture** using a stateful LangGraph workflow. It wraps untrusted AI extractors in structural safeguards:
    1.  **Fail-Closed Ingestion:** Explicitly tracks malformed inputs so they are counted in the performance denominator, preventing artificial accuracy inflation.
    2.  **In-Memory Identity Separation:** Isolates sensitive patient names to temporary memory scopes for matching against ground truth, writing only anonymized keys to disk.
    3.  **Self-Diagnostic Arithmetic:** Validates extractor outputs (e.g., verifying if individual sessions sum to the reported total hours) without needing labeled ground truth.
    4.  **Deterministic Triage Gate:** Automatically interrupts the graph and halts execution in physical memory (`human_review` node) when borderline tolerances or mathematical errors are detected, ensuring human clearance before reporting.

### Key Empirical Findings
Benchmarking **821 timesheet extraction rows** processed by six different models reveals:
*   **10.5% (86/821) of input rows were malformed.** A naive pipeline would silently drop these; the protected pipeline catches them explicitly (`normalize_skipped=86`).
*   **21.4% (157/735) of rows failed internal math checks.** A naive pipeline would accept these incorrect hours; the protected pipeline flags them automatically.
*   **50 rows triggered the Human-in-the-Loop (HITL) gate.** The protected pipeline halted execution to prevent incorrect billing from proceeding.
*   **0 PHI string leaks occurred** across 9 persistent output files.

---

## 2. Canonical Evidence Tables

### Table A: Naive Pipeline vs. Architecture-Protected Pipeline
A comparison of failure mode handling between a naive script and our stateful safety architecture:

| Dimension | Naive Pipeline (Simulated) | Architecture-Protected Pipeline (Observed) | Safety & Research Impact |
| :--- | :--- | :--- | :--- |
| **Malformed Ingestion** | Silently dropped (86 rows vanished) | Explicitly tracked: `normalize_skipped=86` | Preserves evaluation denominator honesty; prevents artificial accuracy inflation. |
| **Extractor Warnings** | Warnings ignored (174 flags discarded) | Flags logged as data quality indicators | Retains internal model confidence signals for administrative audit. |
| **Borderline Decisions** | Silently auto-accepted (50 rows) | Routed to Human-in-the-Loop (HITL) gate | Enforces physical human oversight on edge cases near billing tolerance. |
| **Protected PII/PHI** | Real patient names written to logs/files | 0 PHI leaks detected across 9 output files | Strict HIPAA-compliance through anonymized state tracking. |
| **Internal Consistency** | Math errors ignored (21.4% mismatch rate) | 157 arithmetic anomalies intercepted | Surfaces extraction failures using unsupervised self-diagnostic arithmetic. |

### Table B: Threat-to-Safeguard Mapping
Formal system hazards mapped to the design safeguards and verification protocols implemented:

| Threat Vector | High-Level Design Safeguard | Verification Protocol |
| :--- | :--- | :--- |
| **PII Leakage to Persistent Logs** | **In-Memory Separation of Identity:** Decouples anonymized file identifiers from real patient names. Name resolution happens strictly in-memory during evaluation and is immediately discarded. | **Static Content Scanning:** Test suites scan all generated output files (`run_summary.json`, `failures.json`, tables) against known patient names to verify zero string leaks. |
| **Unchecked Ambiguity** | **Deterministic Gating & State Lock:** Routes borderline tolerances and flags to a physical state-machine halt (LangGraph interrupt), blocking automated progression. | **State-Machine Boundary Simulation:** HITL tests simulate ambiguous extraction results and verify that the graph halts execution and rejects completion attempts until feedback is injected. |
| **Silent Data Omission** | **Fail-Closed Schema Normalization:** Raw inputs must conform to strict temporal schemas. Rows failing normalization route to `normalize_skipped` counts. | **Negative Format Assertion:** Unit tests supply invalid datetimes to the parser and verify that the system returns structured error types that force the pipeline to increment its error count. |
| **Arithmetic Hallucinations** | **Self-Diagnostic Math Constraints:** Computes internal consistency of total hours vs. session intervals independently of ground truth, establishing a quality warning signal. | **Consistency Boundary Verification:** Scoring metrics are tested at exact boundaries to ensure a binary 0/1 compliance outcome with zero partial credit. |

### Table C: Comparative Extractor Performance (Canonical Output)
Results generated by running `scripts/run_all_methods.py` across all methods:

| Method | GT Hours Acc (±15m) | GT Time-In Acc (±30m) | GT Time-Out Acc (±30m) | Fully Correct | Hours Mismatch | Files | GT Rows |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **band_crop_vlm_cloud** | 85.4% | 75.1% | 75.2% | 75.5% | 10.7% | 30 | 171 |
| **layout_guided_vlm_cloud** | 79.2% | 69.2% | 68.3% | 68.8% | 10.2% | 30 | 155 |
| **layout_guided_vlm_local** | 58.5% | 59.3% | 54.9% | 50.0% | 27.0% | 21 | 108 |
| **ocr_only** | 42.7% | 36.0% | 41.7% | 13.3% | 88.3% | 10 | 29 |
| **ppocr_grid** | 44.6% | 38.3% | 34.7% | 19.4% | 73.1% | 13 | 36 |
| **vlm_full_page** | 67.2% | 61.1% | 50.4% | 48.4% | 26.2% | 20 | 85 |

*   **To regenerate this table:** Refer to the [reproducibility.md](reproducibility.md) guide.

---

## 3. Research Artifact Index

Navigate the academic evaluation components using the mapping below:

```
  docs/paper/
  ├── research_index.md       <-- You are here
  ├── related_work.md         <-- Literature review and positioning
  ├── reproducibility.md       <-- Reproduction commands and validation
  ├── ablation_study.md       <-- Naive vs. Protected pipeline details
  ├── threat_model.md         <-- Trust boundaries, hazard profile, and mitigations
  ├── generalizability.md     <-- Transferable design patterns for clinical domains
  └── evidence_package.md     <-- Consolidated manuscript package
```

### 1. [ablation_study.md](ablation_study.md)
*   **What question it answers:** What is the empirical benefit of our safety architecture compared to a simulated naive pipeline?
*   **Why it matters to the paper:** Provides the core quantitative backing, showing that model accuracy measurements are unreliable without fail-closed denominator protection and math audits.
*   **When a reviewer should read it:** First, to see the concrete numbers supporting the system's performance claims.

### 2. [threat_model.md](threat_model.md)
*   **What question it answers:** What are the security, privacy, and integrity boundaries of the system, and how does it prevent HIPAA violations?
*   **Why it matters to the paper:** Establishes the threat profiles and maps specific threats (like PII leaks or arithmetic hallucinations) to technical safeguards.
*   **When a reviewer should read it:** To understand the structural security design of the pipeline.

### 3. [generalizability.md](generalizability.md)
*   **What question it answers:** How can the five core architectural patterns developed here be applied to other regulated industries?
*   **Why it matters to the paper:** Elevates the contribution from a single timesheet parser to a generalizable architectural pattern for any high-consequence healthcare triage agent (e.g., oncology clinical trials or radiology coding).
*   **When a reviewer should read it:** To assess the intellectual contribution and transferability of the design.

### 4. [related_work.md](related_work.md)
*   **What question it answers:** Where does this system sit in relation to current healthcare AI, OCR benchmarking, and human-in-the-loop literature?
*   **Why it matters to the paper:** Demonstrates academic rigor by highlighting the gaps in traditional literature (which ignore ingestion loss and lack physical interrupt bounds) and how this architecture fills them.
*   **When a reviewer should read it:** During the literature review check.

### 5. [reproducibility.md](reproducibility.md)
*   **What question it answers:** How can a reviewer clone the repo and regenerate all tables, metrics, and logs locally?
*   **Why it matters to the paper:** Guarantees transparency and open-science traceability.
*   **When a reviewer should read it:** When executing the code to verify the results.

### 6. [evidence_package.md](evidence_package.md)
*   **What question it answers:** Where can I find a consolidated overview of the whole project for publication draft integration?
*   **Why it matters to the paper:** Gathers the ablation results, threat boundaries, and conclusions into one unified place.
*   **When a reviewer should read it:** For a quick, self-contained overview of the paper's empirical and theoretical contributions.
