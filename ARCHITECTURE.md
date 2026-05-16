# Homecare Visit Triage Agent — Architecture & Implementation Plan

> **Purpose:** This document is the single source of truth for building this project.
> Any engineer or AI agent should be able to read this file and implement the full system
> without additional context.

---

## 0. Project Context — Read This First

### Local Paths
```
Project root:     /Users/mohit/Documents/GitHub/homecare-visit-triage-agent
Architecture:     /Users/mohit/Documents/GitHub/homecare-visit-triage-agent/ARCHITECTURE.md  (this file)
```

### Reference Repositories (for patterns and code reuse)
```
Primary:   https://github.com/mohitagr18/langgraph-agent-testing
           → Reuse: LangGraph graph wiring, state schema, one-way dependency pattern,
             evaluator-as-function pattern, 3-layer test hierarchy, uv/pyproject.toml setup

Secondary: https://github.com/mohitagr18/timesheet-ocr
           → Reuse: Pydantic config (src/config.py), parser helpers (parse_date, parse_hours,
             parse_time, clean_name), benchmark export patterns, PHI anonymization approach
```

### Existing Files in the Workspace (as of project start)
```
/Users/mohit/Documents/GitHub/homecare-visit-triage-agent/
├── .env                                          ← API keys (gitignored)
├── .gitignore                                    ← already ignores input/, .DS_Store
├── README.md                                     ← placeholder
├── ARCHITECTURE.md                               ← THIS FILE
└── input/                                        ← gitignored; contains all input data
    ├── ground_truth.xlsx                          ← 210 GT rows, 23 source files, no header row
    │                                                Columns (positional): [0] source_file (REAL name),
    │                                                [1] date (ISO), [2] total_hours, [3] time_in (12h "7:00 AM"),
    │                                                [4] time_out (12h "3:00 PM"), [5] employee_name (not evaluated)
    ├── You Shipped an AI Agent to...Medium.pdf    ← Reference article (not used in code)
    └── band_crop_vlm_cloud/                       ← First method (of 6)
        ├── merged_results.xlsx                    ← 225 rows, 30 anonymized source files
        │                                            Sheet: "Timesheet Data"
        │                                            Key cols: Source File (anon), Date (ISO),
        │                                            Time In (HH:MM), Time Out, Total Hours, Status, Issues
        ├── name_mapping.db                        ← SQLite: patients table maps e.g. Patient_L → N.Rivera
        │                                            Cols: anonymized_id, real_name, source_files
        └── benchmark_patient_*.xlsx (×30)         ← Per-file debug artifacts (IGNORED by pipeline)
```

### Files That Do NOT Exist Yet (to be created)
```
pyproject.toml, uv.lock, config.yaml, langgraph.json
src/ (entire directory)
scripts/run_benchmark.py
tests/ (entire directory)
output/ (created at runtime)
```

### Tool Requirements
```
Python:  >= 3.11
Manager: uv (NOT pip, NOT conda). Install: https://docs.astral.sh/uv/
Run:     uv sync → uv run python scripts/run_benchmark.py
Test:    uv run pytest tests/ -v
```

### PHI/PII Hard Constraint
```
This is healthcare data (HIPAA). Real patient/employee names and filenames exist ONLY in:
  - input/ground_truth.xlsx
  - input/{method}/name_mapping.db
These are gitignored. All output artifacts MUST use anonymized identifiers only.
The name resolver maps anon → real IN-MEMORY ONLY for GT matching. See Section 11.
```

---

## 1. Project Summary

**What:** A LangGraph-based evaluation pipeline that benchmarks 6 document extraction
methods against manually-annotated ground truth for healthcare timesheets.

**Why:** Most OCR/VLM benchmarks are batch scripts that report aggregate accuracy.
This project models the benchmark as a **testable stateful graph** with:
- Explicit node functions that can be unit-tested in isolation
- Graph routing that can be integration-tested
- A human-in-the-loop review gate for ambiguous results
- Per-field evaluation scored against a labeled dataset

**IEEE paper contribution:** A four-layer testing methodology (unit → integration →
HITL → evaluation) applied to document extraction in a HIPAA-regulated domain,
demonstrating that software testing practices for agentic AI workflows generalize
to document processing pipelines.

**What this pipeline does NOT do:** It does not run OCR or VLM extraction.
The extraction is already done (by the `timesheet-ocr` system). This pipeline
starts from pre-extracted outputs (`merged_results.xlsx`) and evaluates them.

---

## 2. Data Flow

```
input/{method}/merged_results.xlsx     input/ground_truth.xlsx
        ↓                                      ↓
    [ingest node]                    [load_ground_truth node]
        ↓                                      ↓
  ExtractionRow list               GroundTruthRow lookup dict
        ↓                                      ↓
   [normalize node]                             │
        ↓                                      │
  NormalizedRow list ──────────────────→ [evaluate node]
                                               ↓
                              EvalResult list + needs_review flag
                                               ↓
                                      [triage conditional edge]
                                        ↓              ↓
                                  needs_review=True   needs_review=False
                                        ↓              ↓
                                [human_review node]    │
                                  (HITL interrupt)     │
                                        ↓              │
                                  human decisions      │
                                        ↓              ↓
                                      [report node]
                                           ↓
                              run_summary.json + paper_table.md
```

> **PHI/PII CONSTRAINT:** Real patient names and filenames are NEVER written to any
> output artifact. Name resolution (anonymized → real) happens in-memory only inside
> the evaluate node for GT matching. All outputs use anonymized identifiers.

---

## 3. LangGraph State Graph

### State Schema
```python
class BenchmarkState(TypedDict):
    # Inputs
    method: str
    merged_path: str
    gt_path: str
    db_path: str
    config: dict

    # After ingest
    extraction_rows: list[dict]          # ExtractionRow dicts

    # After normalize
    normalized_rows: list[dict]          # NormalizedRow dicts

    # After evaluate
    eval_results: list[dict]             # RowEvalResult dicts
    flagged_for_review: list[dict]       # ambiguous rows needing human review
    needs_review: bool                   # routing signal

    # After human_review (HITL)
    human_decisions: list[dict] | None   # reviewer confirmations/corrections

    # After report
    summary: dict | None                 # RunSummary dict
```

### Graph Topology
```python
builder = StateGraph(BenchmarkState)

builder.add_node("ingest", ingest_node)
builder.add_node("normalize", normalize_node)
builder.add_node("evaluate", evaluate_node)
builder.add_node("human_review", human_review_node)   # HITL interrupt
builder.add_node("report", report_node)

builder.add_edge(START, "ingest")
builder.add_edge("ingest", "normalize")
builder.add_edge("normalize", "evaluate")
builder.add_conditional_edges("evaluate", triage_decision)  # → human_review or report
builder.add_edge("human_review", "report")
builder.add_edge("report", END)
```

### Triage Decision (Conditional Edge)
```python
def triage_decision(state: BenchmarkState) -> str:
    if state["needs_review"] and state["flagged_for_review"]:
        return "human_review"
    return "report"
```

**What triggers review:**
- Hours mismatch within tolerance (GT says 7.0, extraction says 7.25 — passes ±15min
  but should a human confirm the GT annotation is correct?)
- Multiple GT rows match the same (file, date) — ambiguous match
- Extraction status is `flagged` but values match GT — internal validation disagreed
  with what turns out to be correct

### HITL Interrupt Node
```python
from langgraph.types import interrupt

def human_review_node(state: BenchmarkState) -> dict:
    flagged = state["flagged_for_review"]
    decisions = interrupt({
        "message": f"{len(flagged)} rows flagged for review",
        "flagged_rows": flagged,
    })
    return {"human_decisions": decisions}
```

Execution pauses here. A human reviews the flagged rows, confirms or corrects them,
and resumes the graph with their decisions. The report node incorporates these decisions.

---

## 4. Input Files (What Exists Now)

### `input/ground_truth.xlsx`
- Sheet: `Timesheet Extract`. **No header row.** 210 rows, 23 unique source files.
- 6 positional columns:
  - `[0]` source_file — **real filename** (e.g., `N.Rivera-Timesheets-021826-022426.pdf`)
  - `[1]` date — ISO string (e.g., `2026-02-18`)
  - `[2]` total_hours — float (e.g., `8.0`)
  - `[3]` time_in — 12-hour string (e.g., `7:00 AM`)
  - `[4]` time_out — 12-hour string (e.g., `3:00 PM`)
  - `[5]` employee_name — real name (**not evaluated**)

### `input/{method}/merged_results.xlsx`
- Sheet: `Timesheet Data`. ~225 rows per method, 30 anonymized source files.
- Key columns: `Source File` (anonymized), `Date`, `Time In` (HH:MM),
  `Time Out`, `Total Hours`, `Calculated Hours`, `Status`, `Issues`

### `input/{method}/name_mapping.db`
- SQLite. Table `patients`: `anonymized_id` → `real_name` + `source_files`
- Example: `Patient_L` → `N.Rivera` (with all real filenames listed)
- Used **in-memory only** during evaluation for GT lookup. Never in output.

### Currently available method: `band_crop_vlm_cloud`
All 6 methods will be added. Each gets its own `input/{method}/` directory.

---

## 5. Module Responsibilities

### `src/state.py` — State schema
Defines `BenchmarkState` TypedDict. All node functions import this.
No node function imports from `src/graph.py` (one-way dependency).

### `src/nodes.py` — Node functions
Pure functions that take state and return state updates:
- `ingest_node(state)` — reads `merged_results.xlsx` → `extraction_rows`
- `normalize_node(state)` — parses dates/times → `normalized_rows`
- `evaluate_node(state)` — GT matching + scoring → `eval_results` + `flagged_for_review` + `needs_review`
- `human_review_node(state)` — HITL interrupt, returns `human_decisions`
- `report_node(state)` — aggregates + writes summary artifacts

### `src/graph.py` — Graph wiring
Imports node functions and wires the graph. Exports `build_graph()` and module-level `graph`.
This is the only file that knows the graph exists.

### `src/models.py` — Pydantic data types
```python
class ExtractionRow(BaseModel):
    source_file: str           # anonymized
    page: int
    row_index: int
    date: str                  # ISO string
    time_in: str               # HH:MM
    time_out: str
    total_hours: float
    calculated_hours: float | None
    status: str                # "accepted" | "flagged"
    issues: str | None

class NormalizedRow(BaseModel):
    source_file: str           # anonymized (NEVER real)
    row_index: int
    date: datetime.date
    time_in: datetime.time
    time_out: datetime.time
    total_hours: float
    calculated_hours: float | None
    status: str
    issues: str | None

class GroundTruthRow(BaseModel):
    source_file: str           # real filename (internal use only)
    date: datetime.date
    time_in: datetime.time | None
    time_out: datetime.time | None
    total_hours: float | None

class FieldEval(BaseModel):
    field: str
    predicted: Any
    expected: Any
    score: float               # 0.0 or 1.0
    comment: str

class RowEvalResult(BaseModel):
    source_file: str           # anonymized (NEVER real)
    row_index: int
    date: datetime.date
    field_evals: list[FieldEval]
    fully_correct: bool
    matched_gt: bool

class RunSummary(BaseModel):
    run_id: str
    timestamp: str
    methods: list[str]
    hours_accuracy: float      # primary metric
    time_in_accuracy: float
    time_out_accuracy: float
    fully_correct_rate: float
    hours_mismatch_rate: float # internal, no GT needed
    total_rows: int
    gt_matched_rows: int
    flagged_for_review: int
    human_reviewed: int
```

### `src/ingestion.py` — Excel reader
- `ingest(merged_path: Path) → list[ExtractionRow]`
- Reads `Timesheet Data` sheet, maps columns, handles None/empty

### `src/ground_truth.py` — GT loader
- `load_ground_truth(gt_path: Path) → dict[tuple[str, date], GroundTruthRow]`
- No header row, positional columns, parses 12h times (`7:00 AM` → `07:00`)
- Returns `{(real_filename, date): GroundTruthRow}` for O(1) lookup

### `src/name_resolver.py` — PHI bridge (internal only)
- `NameResolver(db_path)` — reads `name_mapping.db` once
- `resolve(anon_filename) → real_filename | None` — in-memory only
- Real filenames NEVER reach output. Used only inside evaluate node.

### `src/normalization.py` — Type conversion
- `normalize(row: ExtractionRow) → NormalizedRow`
- Parses date strings → `datetime.date`, time strings → `datetime.time`
- Preserves anonymized `source_file` as-is

### `src/metrics.py` — Pure scoring functions
- `hours_match(predicted, expected, tolerance_minutes) → float`
- `time_match(predicted, expected, tolerance_minutes) → float`
- `exact_match(a, b) → float`
- All return `{0.0, 1.0}`. No side effects. Fully unit-testable.

### `src/evaluation.py` — Per-field evaluators
- `evaluate_row(row, gt_row, config) → RowEvalResult`
- `eval_hours()`, `eval_time_in()`, `eval_time_out()` — per-field
- Uses `NameResolver` internally for GT lookup key, discards real filename

### `src/reporting.py` — Summary + paper table
- `generate_summary(eval_results, human_decisions, run_id) → RunSummary`
- Writes: `run_summary.json`, `paper_table.md`, `failures.json`
- All output uses anonymized filenames only

### `src/config.py` — Pydantic config
- YAML + env-var override (`DOCBENCH_<SECTION>_<KEY>`)
- Key fields: `hours_tolerance_minutes: 15`, `time_tolerance_minutes: 30`

### `scripts/run_benchmark.py` — CLI entry point
- `--method`, `--limit N`, `--file <stem>`, `--no-cache`, `--all`, `--run-id`
- Default: `--limit 1` with warning. `--all` required for full sweep.

---

## 6. Directory Layout

```
homecare-visit-triage-agent/
├── input/
│   ├── ground_truth.xlsx
│   └── {method}/
│       ├── merged_results.xlsx
│       ├── name_mapping.db
│       └── benchmark_*.xlsx        # ignored by pipeline
├── src/
│   ├── __init__.py
│   ├── state.py                    # BenchmarkState TypedDict
│   ├── nodes.py                    # Node functions (ingest, normalize, evaluate, etc.)
│   ├── graph.py                    # Graph wiring (imports nodes, exports build_graph)
│   ├── models.py                   # Pydantic data types
│   ├── ingestion.py                # merged_results.xlsx reader
│   ├── ground_truth.py             # ground_truth.xlsx reader
│   ├── name_resolver.py            # anonymized ↔ real (in-memory only)
│   ├── normalization.py            # ExtractionRow → NormalizedRow
│   ├── evaluation.py               # NormalizedRow + GT → EvalResult
│   ├── metrics.py                  # Pure scoring functions
│   ├── reporting.py                # Summary + paper table writer
│   └── config.py                   # Pydantic AppConfig
├── scripts/
│   └── run_benchmark.py            # CLI entry point
├── tests/
│   ├── test_unit.py                # Layer 1: node functions in isolation
│   ├── test_integration.py         # Layer 2: full graph routing
│   ├── test_hitl.py                # Layer 3: interrupt/resume
│   ├── test_evaluation.py          # Layer 4: scored against GT dataset
│   └── fixtures/                   # synthetic xlsx/db for tests
├── output/                         # gitignored
│   └── {run_id}/
│       ├── run_config.json
│       ├── {method}/
│       │   ├── {method}_rows.json
│       │   ├── {method}_eval.json
│       │   └── {method}.log
│       └── summary/
│           ├── run_summary.json
│           ├── paper_table.md
│           └── failures.json
├── pyproject.toml
├── uv.lock
├── config.yaml
├── langgraph.json                  # LangGraph platform config
└── README.md
```

---

## 7. Four-Layer Testing Strategy (IEEE Paper Core)

### Layer 1: Unit Tests (`tests/test_unit.py`)
Test node functions in isolation without running the graph.

```python
def test_hours_at_tolerance_boundary():
    assert hours_match(7.0, 7.25, tolerance_minutes=15) == 1.0   # exactly at boundary
    assert hours_match(7.0, 7.26, tolerance_minutes=15) == 0.0   # just over

def test_normalize_handles_malformed_time():
    row = make_extraction_row(time_in="", time_out="15:30")
    result = normalize(row)
    assert result is None  # unrecoverable → skipped

def test_triage_flags_ambiguous_rows():
    state = make_state(flagged_for_review=[some_row])
    assert triage_decision(state) == "human_review"

def test_triage_skips_review_when_clean():
    state = make_state(flagged_for_review=[])
    assert triage_decision(state) == "report"

def test_name_resolver_never_leaks_phi():
    resolver = NameResolver(test_db)
    real = resolver.resolve("patient_l_week5.pdf")
    # Verify resolve works internally
    assert real is not None
    # But NormalizedRow never contains it
    row = normalize(make_extraction_row(source_file="patient_l_week5.pdf"))
    assert "Rivera" not in row.source_file
```

### Layer 2: Integration Tests (`tests/test_integration.py`)
Run the compiled graph end-to-end with in-memory checkpointer.

```python
@pytest.fixture
def graph():
    return build_graph()

def test_clean_file_completes_without_review(graph):
    config = {"configurable": {"thread_id": f"int-{uuid4()}"}}
    result = graph.invoke({
        "method": "band_crop_vlm_cloud",
        "merged_path": "tests/fixtures/clean_merged.xlsx",
        ...
    }, config)
    assert result["needs_review"] is False
    assert result["summary"] is not None

def test_state_flows_through_all_nodes(graph):
    config = {"configurable": {"thread_id": f"int-{uuid4()}"}}
    result = graph.invoke({...}, config)
    assert len(result["extraction_rows"]) > 0
    assert len(result["normalized_rows"]) > 0
    assert len(result["eval_results"]) > 0
```

### Layer 3: HITL Tests (`tests/test_hitl.py`)
Prove the graph pauses and resumes at the review boundary.

```python
def test_ambiguous_rows_trigger_interrupt(graph):
    config = {"configurable": {"thread_id": f"hitl-{uuid4()}"}}
    # First invoke — should pause
    result = graph.invoke({
        "merged_path": "tests/fixtures/ambiguous_merged.xlsx", ...
    }, config)
    # Verify execution paused at human_review
    snapshot = graph.get_state(config)
    assert snapshot.next == ("human_review",)

def test_resume_after_human_decision(graph):
    config = {"configurable": {"thread_id": f"hitl-{uuid4()}"}}
    graph.invoke({...}, config)  # pauses
    # Resume with human decisions
    result = graph.invoke(
        Command(resume=[{"row_index": 3, "accept": True}]),
        config
    )
    assert result["summary"] is not None
    assert result["human_decisions"] is not None
```

### Layer 4: Evaluation Tests (`tests/test_evaluation.py`)
Score the pipeline against the full labeled dataset.

```python
def test_gt_hours_accuracy_above_threshold():
    result = run_full_benchmark("band_crop_vlm_cloud")
    assert result.hours_accuracy >= 0.80  # minimum expected accuracy

def test_per_field_evaluators_score_correctly():
    row = make_normalized_row(total_hours=7.0)
    gt = make_gt_row(total_hours=7.0)
    eval_result = evaluate_row(row, gt, config)
    hours_eval = next(e for e in eval_result.field_evals if e.field == "hours")
    assert hours_eval.score == 1.0
```

---

## 8. Six Extraction Methods

| Method | Description |
|---|---|
| `band_crop_vlm_cloud` | Surgical two-band crop → Gemini (cloud VLM) |
| `layout_guided_vlm_cloud` | PP-DocLayoutV3 table crop → Gemini |
| `layout_guided_vlm_local` | PP-DocLayoutV3 table crop → Ollama (local VLM) |
| `vlm_full_page` | Full page → Ollama (local VLM) |
| `ppocr_grid` | PaddleOCR grid + VLM fallback |
| `ocr_only` | PaddleOCR grid, no VLM fallback |

Start with `band_crop_vlm_cloud` (already in `input/`). Add others incrementally.

---

## 9. Paper Table Format (Target Output)

| Method | GT Hours Acc (±15m) | GT Time-In Acc (±30m) | GT Time-Out Acc (±30m) | Fully Correct | Hours Mismatch |
|---|---|---|---|---|---|
| band_crop_vlm_cloud | 91.0% | 88.5% | 88.5% | 82.3% | 9.0% |
| layout_guided_vlm_cloud | — | — | — | — | — |
| ... | ... | ... | ... | ... | ... |

Primary metric: **GT Hours Accuracy (±15 min)**

---

## 10. Implementation Plan — With Verification Criteria

**Rule: every phase has an observable verification.** You should never wonder "is it working?"
If the verification step fails, the phase is not done. Do not proceed to the next phase.

---

### Phase 1: Project Scaffolding

**What you build:** `pyproject.toml`, `config.yaml`, `src/__init__.py`, `src/config.py`, `langgraph.json`

**How you know it's working:**

```bash
# 1. Dependencies install cleanly
uv sync
# ✅ Expected: "Resolved X packages" with no errors. A uv.lock file appears.

# 2. Config loads from YAML
uv run python -c "from src.config import load_config; c = load_config(); print(c)"
# ✅ Expected: Prints the config object with hours_tolerance_minutes=15, etc.
# ❌ Failure: ImportError, YAML parse error, or missing field → fix before proceeding

# 3. LangGraph is importable
uv run python -c "from langgraph.graph import StateGraph; print('OK')"
# ✅ Expected: "OK"
```

**Files that must exist after Phase 1:**
```
pyproject.toml          ← has langgraph, pydantic, openpyxl, pyyaml, pytest
uv.lock                 ← auto-generated by uv sync
config.yaml             ← hours_tolerance_minutes: 15, time_tolerance_minutes: 30
src/__init__.py          ← empty
src/config.py            ← load_config() returns a Pydantic AppConfig
langgraph.json           ← points to src/graph.py (graph.py doesn't exist yet — that's OK)
```

---

### Phase 2: Data Layer (Models + Ingestion + GT + Name Resolver + Normalization + Metrics)

**What you build:** `src/models.py`, `src/ingestion.py`, `src/ground_truth.py`, `src/name_resolver.py`, `src/normalization.py`, `src/metrics.py`

**How you know it's working — step by step:**

```bash
# 2.1 Models are importable and valid
uv run python -c "
from src.models import ExtractionRow, NormalizedRow, GroundTruthRow, RowEvalResult
print('All models imported OK')
"
# ✅ Expected: "All models imported OK"

# 2.2 Ingestion reads your actual merged_results.xlsx
uv run python -c "
from src.ingestion import ingest
from pathlib import Path
rows = ingest(Path('input/band_crop_vlm_cloud/merged_results.xlsx'))
print(f'Ingested {len(rows)} rows')
print(f'First row: source_file={rows[0].source_file}, date={rows[0].date}, hours={rows[0].total_hours}')
print(f'Last row:  source_file={rows[-1].source_file}, date={rows[-1].date}')
"
# ✅ Expected: "Ingested 225 rows" (or close), first row shows patient_a_week1.pdf, date, hours
# ❌ Failure: KeyError on column name → column mapping is wrong

# 2.3 Ground truth loads and parses 12h times
uv run python -c "
from src.ground_truth import load_ground_truth
from pathlib import Path
gt = load_ground_truth(Path('input/ground_truth.xlsx'))
print(f'Loaded {len(gt)} GT entries')
sample_key = list(gt.keys())[0]
print(f'Sample key: {sample_key}')
print(f'Sample value: {gt[sample_key]}')
"
# ✅ Expected: "Loaded 210 GT entries"
#    Sample key is a (real_filename, date) tuple
#    Sample value shows time_in as datetime.time (e.g., 07:00), NOT "7:00 AM"
# ❌ Failure: time_in is still a string → 12h parsing is broken

# 2.4 Name resolver maps anonymized → real
uv run python -c "
from src.name_resolver import NameResolver
from pathlib import Path
resolver = NameResolver(Path('input/band_crop_vlm_cloud/name_mapping.db'))
real = resolver.resolve('patient_a_week1.pdf')
print(f'patient_a_week1.pdf → {real}')
# Also test that the anon filename for N.Rivera resolves
for anon in ['patient_l_week5.pdf', 'patient_l_week6.pdf']:
    real = resolver.resolve(anon)
    print(f'{anon} → {real}')
"
# ✅ Expected: Each prints a real filename (e.g., "N.Rivera-Timesheets-021826-022426.pdf")
# ❌ Failure: Returns None → mapping logic is wrong. Check DB schema.

# 2.5 Normalization converts types
uv run python -c "
from src.ingestion import ingest
from src.normalization import normalize
from pathlib import Path
rows = ingest(Path('input/band_crop_vlm_cloud/merged_results.xlsx'))
norm = normalize(rows[0])
print(f'date type: {type(norm.date).__name__} = {norm.date}')
print(f'time_in type: {type(norm.time_in).__name__} = {norm.time_in}')
print(f'source_file: {norm.source_file}')  # must be anonymized
"
# ✅ Expected: date type=date, time_in type=time, source_file=patient_a_week1.pdf
# ❌ Failure: date is still a string → parsing didn't run

# 2.6 Metrics return correct boundary values
uv run python -c "
from src.metrics import hours_match, time_match
from datetime import time
# Exactly at tolerance (15min = 0.25h)
print('7.0 vs 7.25 (±15min):', hours_match(7.0, 7.25, 15))  # should be 1.0
print('7.0 vs 7.26 (±15min):', hours_match(7.0, 7.26, 15))  # should be 0.0
# Time match
print('08:30 vs 08:45 (±30min):', time_match(time(8,30), time(8,45), 30))  # should be 1.0
print('08:30 vs 09:15 (±30min):', time_match(time(8,30), time(9,15), 30))  # should be 0.0
"
# ✅ Expected: 1.0, 0.0, 1.0, 0.0 — exactly these values
# ❌ Failure: Wrong values → tolerance arithmetic is broken
```

**Files that must exist after Phase 2:**
```
src/models.py, src/ingestion.py, src/ground_truth.py
src/name_resolver.py, src/normalization.py, src/metrics.py
```

---

### Phase 3: Evaluation Logic

**What you build:** `src/evaluation.py`, `src/reporting.py`

**How you know it's working:**

```bash
# 3.1 End-to-end evaluation of one file (no graph yet — just functions)
uv run python -c "
from pathlib import Path
from src.ingestion import ingest
from src.normalization import normalize
from src.ground_truth import load_ground_truth
from src.name_resolver import NameResolver
from src.evaluation import evaluate_row
from src.config import load_config

config = load_config()
rows = ingest(Path('input/band_crop_vlm_cloud/merged_results.xlsx'))
gt = load_ground_truth(Path('input/ground_truth.xlsx'))
resolver = NameResolver(Path('input/band_crop_vlm_cloud/name_mapping.db'))

# Pick first row, normalize, resolve, evaluate
norm = normalize(rows[0])
real_file = resolver.resolve(norm.source_file)
gt_key = (real_file, norm.date) if real_file else None
gt_row = gt.get(gt_key) if gt_key else None

result = evaluate_row(norm, gt_row, config)
print(f'File: {result.source_file}')       # must be anonymized
print(f'Date: {result.date}')
print(f'Matched GT: {result.matched_gt}')
print(f'Fully correct: {result.fully_correct}')
for fe in result.field_evals:
    print(f'  {fe.field}: score={fe.score}, comment={fe.comment}')
"
# ✅ Expected:
#   File: patient_a_week1.pdf  (anonymized — no real name)
#   Matched GT: True (if this file is in ground_truth.xlsx)
#   Each field_eval shows score=1.0 or 0.0 with a clear comment
# ❌ Failure: Matched GT=False when it should be True → name resolver or GT key mismatch
# ❌ Failure: "Rivera" appears anywhere in output → PHI leak

# 3.2 Reporting writes paper table
uv run python -c "
from src.reporting import generate_summary
# ... (after running evaluation on multiple rows)
# Check that output/run_id/summary/paper_table.md exists and contains a markdown table
"
# ✅ Expected: paper_table.md has a row for band_crop_vlm_cloud with percentage values
```

---

### Phase 4: LangGraph Agent

**What you build:** `src/state.py`, `src/nodes.py`, `src/graph.py`, `scripts/run_benchmark.py`

**How you know it's working:**

```bash
# 4.1 Graph compiles without error
uv run python -c "
from src.graph import build_graph
g = build_graph()
print(f'Graph nodes: {list(g.get_graph().nodes.keys())}')
print('Graph compiled OK')
"
# ✅ Expected: Nodes list includes: __start__, ingest, normalize, evaluate, human_review, report, __end__
# ❌ Failure: ImportError or missing node → check src/nodes.py imports

# 4.2 Full CLI invocation for one file — clean case (no HITL trigger)
uv run python scripts/run_benchmark.py --method band_crop_vlm_cloud --file patient_a_week1
# ✅ Expected output:
#   [info] Discovered method: band_crop_vlm_cloud
#   [info] Ingested 5 rows from patient_a_week1.pdf        ← number of rows for that file
#   [info] Normalized 5 rows
#   [info] Evaluated 5 rows (X matched GT, Y unmatched)
#   [info] No ambiguous rows — skipping human review
#   [info] Summary written to output/run_YYYYMMDD_HHMMSS/summary/run_summary.json
#   [info] Paper table written to output/run_YYYYMMDD_HHMMSS/summary/paper_table.md

# 4.3 Verify output artifacts exist and contain expected content
cat output/run_*/summary/paper_table.md
# ✅ Expected: A markdown table with one row:
#   | Method | GT Hours Acc (±15m) | ... |
#   | band_crop_vlm_cloud | XX.X% | ... |

cat output/run_*/band_crop_vlm_cloud/band_crop_vlm_cloud_eval.json | python3 -m json.tool | head -30
# ✅ Expected: JSON array of RowEvalResult dicts with field_evals
#   Every source_file value must be anonymized (patient_*, never real name)

cat output/run_*/run_config.json | python3 -m json.tool | head -10
# ✅ Expected: Full config snapshot showing hours_tolerance_minutes: 15, etc.

# 4.4 Verify no PHI in any output file
grep -ri "Rivera\|Leal\|Jackson\|Derricott\|Elliott\|Bussa\|Hanton\|Pegram\|Drewry\|Moran" output/
# ✅ Expected: NO matches (zero lines). Any match = PHI leak = must fix before proceeding.
```

---

### Phase 5: Testing Layers

**What you build:** `tests/test_unit.py`, `tests/test_integration.py`, `tests/test_hitl.py`, `tests/test_evaluation.py`, `tests/fixtures/`

**How you know it's working:**

```bash
# 5.1 Layer 1 — Unit tests
uv run pytest tests/test_unit.py -v
# ✅ Expected: All tests PASSED. Specifically check for:
#   test_hours_at_tolerance_boundary PASSED
#   test_hours_over_tolerance PASSED
#   test_normalize_handles_malformed_time PASSED
#   test_triage_flags_ambiguous_rows PASSED
#   test_triage_skips_review_when_clean PASSED
#   test_name_resolver_never_leaks_phi PASSED

# 5.2 Layer 2 — Integration tests
uv run pytest tests/test_integration.py -v
# ✅ Expected:
#   test_clean_file_completes_without_review PASSED
#   test_state_flows_through_all_nodes PASSED
#   test_output_contains_only_anonymized_filenames PASSED

# 5.3 Layer 3 — HITL tests
uv run pytest tests/test_hitl.py -v
# ✅ Expected:
#   test_ambiguous_rows_trigger_interrupt PASSED
#   test_resume_after_human_decision PASSED
#   test_report_includes_human_decisions PASSED

# 5.4 Layer 4 — Evaluation tests
uv run pytest tests/test_evaluation.py -v
# ✅ Expected:
#   test_gt_hours_accuracy_above_threshold PASSED
#   test_per_field_evaluators_score_correctly PASSED

# 5.5 All layers together
uv run pytest tests/ -v
# ✅ Expected: ALL tests pass. Zero failures. The summary line shows something like:
#   "X passed in Y.YYs"
# ❌ Failure: Any FAILED test → fix before moving to Phase 6
```

---

### Phase 6: Staged Execution

**What you build:** Nothing new — this phase validates the existing pipeline at increasing scale.

**How you know it's working:**

```bash
# Stage 1: Smoke test (1 file)
uv run python scripts/run_benchmark.py --method band_crop_vlm_cloud --file patient_a_week1
# ✅ Verify: paper_table.md exists, has one data row, percentages are numbers (not NaN or "—")

# Stage 2: Two files
uv run python scripts/run_benchmark.py --method band_crop_vlm_cloud --limit 2
# ✅ Verify: paper_table.md still has one row (same method, aggregated)
# ✅ Verify: eval JSON has rows from TWO different source files
# ✅ Verify: Hours accuracy in paper_table.md is within ~5% of Stage 1
#    (If it swings wildly, there may be state leakage between files)

# Stage 3: Five files
uv run python scripts/run_benchmark.py --method band_crop_vlm_cloud --limit 5
# ✅ Verify: Same checks as Stage 2. Numbers should be stabilizing.
# ✅ Verify: failures.json shows any rows that didn't match GT (expected — some files
#    may not be in ground_truth.xlsx). Count should be explainable.

# Stage 4: Twenty-five files
uv run python scripts/run_benchmark.py --method band_crop_vlm_cloud --limit 25
# ✅ Verify: Numbers should be very close to final. No crashes, no memory issues.

# Stage 5: All files
uv run python scripts/run_benchmark.py --method band_crop_vlm_cloud --all
# ✅ Verify: paper_table.md contains final numbers for the paper.
# ✅ Verify: run_summary.json shows total_rows ≈ 225, gt_matched_rows ≈ 210
# ✅ Verify: No PHI in output (run the grep check from Phase 4.4 again)

# KEY STABILITY CHECK across stages:
# Hours accuracy should converge:
#   Stage 1: ~85% (high variance, only 5 rows)
#   Stage 2: ~87%
#   Stage 3: ~88%
#   Stage 5: ~89% (final)
# If accuracy DROPS significantly between stages, investigate which files caused the drop
# using failures.json
```

---

### Phase 7: Multi-Method (After User Provides More Data)

**What you build:** Nothing new — user adds `input/{method}/merged_results.xlsx` + `name_mapping.db` for each additional method.

**How you know it's working:**

```bash
# 7.1 After adding a second method (e.g., ocr_only)
uv run python scripts/run_benchmark.py --method ocr_only --file patient_a_week1
# ✅ Verify: Works exactly like band_crop_vlm_cloud did in Phase 4

# 7.2 Comparative run across two methods
uv run python scripts/run_benchmark.py --all
# ✅ Verify: paper_table.md now has TWO rows:
#   | Method                | GT Hours Acc | ... |
#   | band_crop_vlm_cloud   | 89.0%       | ... |
#   | ocr_only              | 72.3%       | ... |
# The numbers should be different between methods (that's the point of benchmarking)

# 7.3 After all 6 methods are added
uv run python scripts/run_benchmark.py --all
# ✅ Verify: paper_table.md has 6 rows. This is the final table for the IEEE paper.
# ✅ Verify: run_summary.json has per_method entries for all 6 methods.
# ✅ Verify: Zero PHI in any output file.
```

---

### Quick Reference: Red Flags at Each Phase

| Phase | Red Flag | What It Means |
|---|---|---|
| 1 | `uv sync` fails | Dependency conflict. Check Python version ≥ 3.11 |
| 2 | Ingestion returns 0 rows | Column name mapping doesn't match xlsx headers |
| 2 | GT loads but `time_in` is a string | 12h → 24h time parsing not implemented |
| 2 | Name resolver returns None for all files | DB table name or column name wrong |
| 3 | All rows have `matched_gt=False` | Name resolution → GT key mismatch. Most common bug. |
| 3 | All scores are 0.0 | Tolerance units wrong (minutes vs hours) |
| 4 | Graph compiles but invoke crashes | Node function signature doesn't match state schema |
| 4 | Real names appear in output | PHI leak. `name_resolver` result is being stored instead of discarded |
| 5 | HITL test can't trigger interrupt | `needs_review` never becomes True. Check triage criteria. |
| 6 | Accuracy swings wildly between stages | State leakage between files, or GT coverage is uneven |

---

## 11. PHI/PII Safety Rules

These are hard constraints. Violation = broken build.

1. `name_resolver.py` is the ONLY module that handles real filenames
2. Real filenames exist in-memory only, inside `evaluate_node`, for GT lookup
3. All output JSON, logs, `paper_table.md`, `failures.json` use anonymized IDs
4. `NormalizedRow.source_file` is always the anonymized filename
5. `RowEvalResult.source_file` is always the anonymized filename
6. `ground_truth.xlsx` is in `.gitignore` (contains real names)
7. `name_mapping.db` is in `.gitignore` (contains real ↔ anon mapping)
8. Unit tests verify PHI never leaks into output structures
9. `input/` directory is already in `.gitignore`

---

## 12. Dependencies

```toml
[project]
requires-python = ">=3.11"
dependencies = [
    "langgraph>=0.4",
    "langchain-core>=0.3",
    "pydantic>=2.0",
    "openpyxl>=3.1",
    "pyyaml>=6.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
]
```

Managed exclusively with `uv`. No `requirements.txt`. No `pip install`.

---

## 13. Key Design Decisions

**Why LangGraph instead of plain Python?**
The IEEE paper needs to demonstrate that the four-layer testing methodology works for
document extraction. Without a graph, layers 2 (integration) and 3 (HITL) have nothing
to test. The graph makes the triage routing and human review boundary explicit and testable.

**Why a HITL review gate in a benchmark?**
Benchmarks assume GT is perfect. It isn't. Some GT annotations may be wrong (e.g., the
annotator wrote 7.0 hours but the actual timesheet shows 7.25). The review gate lets a
human confirm ambiguous cases before the final paper numbers are published. This makes
the benchmark more trustworthy than a batch script.

**Why anonymized output in a research paper?**
HIPAA. The timesheets contain real patient names, employee names, and dates of service.
The pipeline can produce publishable results (accuracy percentages, failure counts)
without exposing any PHI. The anonymization was done during extraction; this pipeline
preserves it end-to-end.

**Why staged execution?**
Debugging 225 rows when something is broken wastes time. Starting with 1 file catches
schema errors. 2 files catches state leakage. 5 files catches edge cases. The numbers
must be stable from stage to stage — if accuracy changes between 5 and 25 files, there
is a bug, not a statistical effect.

**One-way dependency: nodes → state, graph → nodes**
`src/state.py` depends on nothing. `src/nodes.py` imports state and data layer modules.
`src/graph.py` imports nodes. Tests import nodes directly without graph. This is the
same dependency pattern from the `langgraph-agent-testing` reference repo.
