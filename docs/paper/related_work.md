# Literature Positioning & Related Work

This document situates the **homecare-visit-triage-agent** repository within the context of existing academic literature and industrial practice across five critical areas: healthcare AI evaluation, OCR/document benchmarking, human-in-the-loop systems, trustworthy safety architectures, and privacy-preserving system design in regulated domains.

---

## 1. Healthcare AI Evaluation
*   **What prior work focuses on:** Existing literature on clinical AI evaluation typically centers on validating diagnostic algorithms, predicting patient outcomes, or measuring the clinical performance of large language models (LLMs) on medical benchmarks (e.g., MedQA).
*   **What it often leaves out:** Most evaluation frameworks assume pre-cleaned, well-structured datasets (e.g., standard clinical trials databases or curated Electronic Health Record datasets). They rarely account for ingestion failure modes, document parsing errors, or the structural gaps between raw clinical document extraction and downstream clinical decision-making.
*   **Our distinct contribution:** This work demonstrates a **defensive evaluation architecture** where the evaluation mechanism itself is stateful and fail-closed. Rather than assuming clean inputs, the pipeline treats input anomalies as primary diagnostic signals. It evaluates the robustness of the system-level wrapper rather than just the raw performance of the underlying model.

---

## 2. OCR & Document Extraction Benchmarking
*   **What prior work focuses on:** Traditional document processing benchmarks (such as PP-OCR or layout-aware VLM evaluations) focus almost exclusively on character-level error rates (CER), word error rates (WER), or bounding box accuracy.
*   **What it often leaves out:** These benchmarks are typically batch scripts that evaluate correctness in a vacuum. They silently drop malformed lines or unparseable text fields, or treat layout/tabular misalignments as aggregate accuracy drops without analyzing how these omissions pollute downstream business or clinical decisions.
*   **Our distinct contribution:** We introduce **denominator-preserving evaluation**. When a document extraction method fails to produce standard-compliant datetimes or numeric values, the Normalization Shield flags the row and retains it in the evaluation denominator (`normalize_skipped`). This prevents "accuracy inflation" where a method appears highly accurate simply because its worst failures were silently dropped during ingestion.

---

## 3. Human-in-the-Loop (HITL) AI Systems
*   **What prior work focuses on:** Standard HITL research often concentrates on active learning (where humans label data to retrain models) or post-hoc feedback loops (where humans audit model outputs on a delayed queue).
*   **What it often leaves out:** Standard agentic frameworks rely on "soft" prompts to request human review, which models can bypass due to instruction-following failures. Furthermore, they do not enforce physical execution halts at the application boundary, allowing borderline or high-risk predictions to advance to persistent databases without human clearance.
*   **Our distinct contribution:** The triage agent enforces a **deterministic triage gate** via a LangGraph state machine. By utilizing physical interrupts (`interrupt_before=["human_review"]`), the system state is frozen on the storage layer whenever borderline confidence thresholds or mathematical inconsistencies are met. It is structurally impossible for an unreviewed borderline record to advance to final reporting or billing generation.

---

## 4. Trustworthy AI & Safety Architectures
*   **What prior work focuses on:** Trustworthy AI research heavily emphasizes prompt-engineering guardrails, alignment tuning (RLHF), and system-level prompt filters (e.g., Llama Guard).
*   **What it often leaves out:** These "soft" safety measures are non-deterministic and susceptible to jailbreaks, formatting drift, and model hallucination. They lack the deterministic guarantees required by regulated software (e.g., medical billing or clinical decision support).
*   **Our distinct contribution:** We present a **defensive trust architecture** that does not rely on model-level safeguards. Instead, we perform **unsupervised self-diagnostic arithmetic** (comparing extracted total hours against the sum of detailed session intervals) to flag errors without requiring ground truth. If the extractor's own output is internally inconsistent, the triage gate intercepts it.

---

## 5. Privacy-Preserving AI in Regulated Domains
*   **What prior work focuses on:** Privacy-preserving literature focuses on differential privacy, homomorphic encryption, or database-level access control list (ACL) rules to protect Patient Health Information (PHI).
*   **What it often leaves out:** When benchmarking extraction pipelines, developers frequently pass real names through evaluation scripts to check matching against a patient registry, leading to accidental leaks of sensitive identifiers into public debug logs, error reports, and evaluation tables.
*   **Our distinct contribution:** The NameResolver serves as an **in-memory identity separation bridge**. Anonymized identifiers are used across the state machine, and real names are loaded into memory solely for ground-truth matching before being discarded. All persistent logs and evaluation reports (`failures.json`, `run_summary.json`) are guaranteed to be PHI-free, meeting HIPAA containment criteria.
