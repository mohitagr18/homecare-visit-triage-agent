# Homecare Visit Triage Agent — Stateful Evaluation Pipeline

[![Python Version](https://img.shields.io/badge/python-3.11%20%7C%203.12-blue)](https://www.python.org/)
[![Package Manager](https://img.shields.io/badge/package--manager-uv-green)](https://github.com/astral-sh/uv)
[![Test Suite](https://img.shields.io/badge/tests-69%20passed-brightgreen)](#running-tests)

A stateful, production-grade **LangGraph evaluation pipeline** designed to ingest, normalize, and benchmark timesheet extractions from six distinct extraction methods (ranging from OCR-only to multi-page VLMs) against a manually annotated clinical ground truth dataset.

This repository serves as the empirical foundation for demonstrating a **trustworthy, HIPAA-compliant design pattern** for AI document processing in regulated healthcare domains.

---

## 🚀 Key Architectural Safeguards

Most document extraction benchmarks are batch scripts that report aggregate metrics and silently ignore data errors. This pipeline enforces safety through a deterministic state machine:

1.  **Fail-Closed Normalization:** Catching malformed data (unparseable dates, negative hours) at ingestion, ensuring skipped rows are counted explicitly in the evaluation denominator rather than disappearing.
2.  **HIPAA-Compliant Identity Containment:** Real patient names and filenames are restricted to in-memory scopes via `NameResolver` solely for ground truth matching, writing only anonymized identifiers to persistent disk logs.
3.  **Self-Diagnostic Arithmetic:** Programmatically audit extractor arithmetic (e.g. validating if `total_hours` matches the sum of session intervals) without requiring labeled ground truth.
4.  **Deterministic Triage Gate:** Edge cases (borderline hours limits) or extractor-ground truth conflicts trigger a physical graph halt (`interrupt_before=["human_review"]`), preventing automated billing from proceeding without human clearance.

---

## 📂 Project Structure

```
.
├── src/
│   ├── config.py           # Pydantic configuration loader (config.yaml)
│   ├── ingestion.py        # Ingests merged Excel outputs from extraction runs
│   ├── normalization.py    # Standardizes fields, filters schema violations
│   ├── name_resolver.py    # Ephemeral mapping bridge between anon and real names
│   ├── evaluation.py       # Scores normalized extractions against ground truth
│   ├── graph.py            # LangGraph state machine flow definitions
│   └── reporting.py        # Generates failure analysis and run diagnostics
├── docs/
│   └── paper/              # Academic evidence and ablation records
│       ├── ablation_study.md      # Naive vs. Protected pipeline comparison
│       ├── threat_model.md        # Formal boundary risk and mitigation map
│       ├── generalizability.md    # Abstracts patterns to radiology/clinical trials
│       └── evidence_package.md    # Consolidated manuscript package
├── input/                  # Gitignored input files (ground_truth.xlsx, DBs)
├── tests/                  # 3-layer test suite (Unit, Integration, HITL)
├── config.yaml             # Core tolerance thresholds and path definitions
└── pyproject.toml          # uv-managed dependencies and package metadata
```

---

## ⚙️ Getting Started

### Prerequisites

*   Python `>= 3.11`
*   `uv` Package Manager (Fast Rust-based python packaging)

To install `uv` on macOS/Linux:
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### Installation

Clone the repository and sync the virtual environment:
```bash
uv sync
```
This automatically creates a virtual environment and installs all dependencies (including `langgraph`, `openpyxl`, `pydantic`, `pytest`, etc.).

---

## 🧪 Running Tests

The test suite covers unit logic, full-state integration, Human-in-the-Loop interrupts, and validation:

```bash
uv run pytest
```

---

## 📊 Running the Ablation Study

To regenerate the empirical comparisons and audit logs showing what goes wrong in a naive pipeline versus our protected implementation:

```bash
uv run python docs/paper/run_ablation.py
```

### Key Findings Summary
Running the ablation study on **821 raw ingested timesheet rows** across 6 extraction methods reveals:
*   **10.5% of all rows (86/821)** were malformed and caught by the normalization shield. A naive pipeline would silently drop them.
*   **21.4% of rows (157/735)** failed internal math consistency (reported total hours did not match the sum of start/stop times).
*   **50 rows** triggered the Human-in-the-Loop triage gate because of borderline limits or matching conflicts.
*   **0 PHI leaks** were found across all persistent outputs and logs.

For detailed analysis, refer to [ablation_study.md](file:///Users/mohit/Documents/GitHub/homecare-visit-triage-agent/docs/paper/ablation_study.md) and [evidence_package.md](file:///Users/mohit/Documents/GitHub/homecare-visit-triage-agent/docs/paper/evidence_package.md).