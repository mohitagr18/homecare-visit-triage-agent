# Research Evidence Strengthening — Implementation Plan Checklist

This implementation plan checklist outlines the remaining work to transform the `homecare-visit-triage-agent` from a functional prototype into a peer-reviewed research-quality demonstration of trustworthy healthcare AI.

*   **Hard constraint:** All modifications must be additive (documentation, scripts, and tables under `docs/paper/`). The main codebase in `src/` and `tests/` remains frozen.

---

## 📋 Checklist & Status Tracker

### 🟩 Phase 1: Baseline Comparison / Ablation Study
*Goal: Provide empirical evidence of the system's safety and containment capabilities compared to a naive pipeline.*

- [x] **Step 1.1 — Implement Ablation Script:** Create a Python script (`docs/paper/run_ablation.py`) to extract metrics.
- [x] **Step 1.2 — Execute & Compute Naive Accuracy:** Run the script against the 6 evaluation methods and save the raw JSON output to `docs/paper/ablation_raw_data.json`.
- [x] **Step 1.3 — Build Comparison Table:** Create `docs/paper/ablation_study.md` containing comparative tables.
- [x] **Step 1.4 — Write the Analysis:** Detail how the architecture prevents silent drops, confident guesses, PHI leaks, and math errors.

### 🟩 Phase 2: Formal Threat Model
*Goal: Create a clear table matching healthcare AI risks (HIPAA violations, unchecked ambiguity, temporal hallucination) with specific code modules and unit tests.*

- [x] **Step 2.1 — Identify Threats:** List major threats to safety, integrity, and privacy in a timesheet triage pipeline.
- [x] **Step 2.2 — Map Mitigations:** Align each threat to the exact function in `src/` and unit test in `tests/`.
- [x] **Step 2.3 — Draft Threat Model Document:** Create `docs/paper/threat_model.md` with the completed mapping.

### ⬜ Phase 3: Generalizability Argument
*Goal: Formulate a domain-neutral description of the system's core design patterns (e.g., fail-closed normalization, HITL gates) and how they transfer to other regulated domains.*

- [ ] **Step 3.1 — Extract Abstract Patterns:** Define the five core safety principles used in this repository in general terms.
- [ ] **Step 3.2 — Map to Other Domains:** Explain how these patterns apply to healthcare areas like radiology AI reporting or clinical trials matching.
- [ ] **Step 3.3 — Document Limitations:** Highlight boundaries where this architectural pattern is not suitable.
- [ ] **Step 3.4 — Draft Generalizability Document:** Create `docs/paper/generalizability.md`.

### ⬜ Phase 4: Related Work Section
*Goal: Position the pipeline against existing academic work in human-in-the-loop (HITL) systems, AI safety frameworks, and medical evaluation benchmarks.*

- [ ] **Step 4.1 — Literature Research:** Identify 5-10 key papers or guidance documents (e.g., FDA AI/ML, NIST AI RMF, constitutional AI).
- [ ] **Step 4.2 — Draft Subsections:** Formulate the HITL, Healthcare AI Evaluation, and Trustworthy System Design literature positioning.
- [ ] **Step 4.3 — Draft Related Work Document:** Create `docs/paper/related_work.md`.

### ⬜ Phase 5: Evidence Packaging
*Goal: Consolidate the findings, tables, arguments, and draft sections into a single publication-ready markdown package.*

- [ ] **Step 5.1 — Consolidate Tables and Sections:** Combine all tables and text from Phases 1-4.
- [ ] **Step 5.2 — Draft Summary Paragraph:** Write a final executive summary explaining what the collective evidence proves.
- [ ] **Step 5.3 — Draft Evidence Package:** Create `docs/paper/evidence_package.md`.

---

## 📈 Current Results Summary (Phase 1)

The ablation study completed successfully. Key findings include:

1. **Silent Dropping:** Across all runs, **10.5% (86/821)** of rows were malformed and skipped by normalization. A naive pipeline would silently ignore these, artificially inflating final accuracy.
2. **Review Interception:** **23.7% (174/735)** of rows triggered internal extractor warnings, and **16 rows** required HITL gating. The protected pipeline successfully routed these to the review state rather than auto-accepting them.
3. **PHI Containment:** Zero real name leaks were detected across 9 output files, validating that real names remained strictly in-memory during the NameResolver ground truth matching.
4. **Internal Consistency:** **21.4% (157/735)** of rows showed arithmetic inconsistencies between total reported hours and detailed session calculations, demonstrating the value of our self-diagnostic validation check.

---

## 🚀 How to Resume Work

To continue with Phase 2:
1. Review the code paths in `src/evaluation.py`, `src/name_resolver.py`, `src/normalization.py`, and `src/graph.py` to identify trust boundaries and data flow mechanisms.
2. Draft the threat model using the templates described in the original implementation plan.
3. Save the threat model to `docs/paper/threat_model.md` and mark the corresponding tasks as completed in this checklist.
