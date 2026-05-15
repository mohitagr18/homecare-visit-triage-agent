# Homecare Visit Triage Agent — Architecture & Implementation Plan

> **Purpose:** This document is the single source of truth for building this project.
> Any engineer or AI agent should be able to read this file and implement the full system
> without additional context.

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

## 10. Implementation Plan

**Every step must pass before moving to the next.** This is the staged execution model.

### Phase 1: Project Scaffolding
```
Step 1.1: Create pyproject.toml with deps: langgraph, pydantic, openpyxl, pyyaml, pytest
Step 1.2: Run `uv sync` — verify clean install
Step 1.3: Create config.yaml with default settings
Step 1.4: Create src/__init__.py, src/config.py — verify config loads
Step 1.5: Create langgraph.json pointing to src/graph.py
```
**Gate:** `uv sync` succeeds, `uv run python -c "from src.config import load_config; load_config()"` works.

### Phase 2: Data Layer (Models + Ingestion + GT)
```
Step 2.1: Create src/models.py — all Pydantic types
Step 2.2: Create src/ingestion.py — reads merged_results.xlsx → list[ExtractionRow]
Step 2.3: Create src/ground_truth.py — reads ground_truth.xlsx → lookup dict
Step 2.4: Create src/name_resolver.py — reads name_mapping.db, maps anon → real
Step 2.5: Create src/normalization.py — ExtractionRow → NormalizedRow
Step 2.6: Create src/metrics.py — hours_match, time_match, exact_match
```
**Gate:** Unit tests for each module pass:
```bash
uv run pytest tests/test_unit.py -v  # metrics, normalization, GT loading, name resolver
```

### Phase 3: Evaluation Logic
```
Step 3.1: Create src/evaluation.py — evaluate_row, eval_hours, eval_time_in, eval_time_out
Step 3.2: Create src/reporting.py — generate_summary, write paper_table.md
```
**Gate:** Can evaluate one file from `band_crop_vlm_cloud` against GT and print scores.

### Phase 4: LangGraph Agent
```
Step 4.1: Create src/state.py — BenchmarkState TypedDict
Step 4.2: Create src/nodes.py — all 5 node functions wrapping the data layer
Step 4.3: Create src/graph.py — wire nodes + conditional edge + HITL interrupt
Step 4.4: Create scripts/run_benchmark.py — CLI entry point that invokes the graph
```
**Gate:** Full graph invocation works for one file:
```bash
uv run python scripts/run_benchmark.py --method band_crop_vlm_cloud --file patient_a_week1
# → output/{run_id}/summary/paper_table.md exists with scores
```

### Phase 5: Testing Layers
```
Step 5.1: Create tests/test_unit.py — metric boundaries, normalization edge cases,
          triage routing, PHI leak prevention
Step 5.2: Create tests/test_integration.py — full graph routing with fixture files
Step 5.3: Create tests/test_hitl.py — interrupt/resume at human_review node
Step 5.4: Create tests/test_evaluation.py — scored against GT dataset
Step 5.5: Create tests/fixtures/ — synthetic xlsx and db files for deterministic tests
```
**Gate:** All 4 test layers pass:
```bash
uv run pytest tests/ -v
```

### Phase 6: Staged Execution
```
Step 6.1: --file patient_a_week1  (1 file smoke test)
Step 6.2: --limit 2               (verify no state leakage between files)
Step 6.3: --limit 5               (edge cases at scale)
Step 6.4: --limit 25              (near-full)
Step 6.5: --all                   (final paper numbers)
```
**Gate:** Numbers are stable across stages. Paper table is generated.

### Phase 7: Multi-Method (After User Provides More Data)
```
Step 7.1: User adds input/{method_2}/merged_results.xlsx + name_mapping.db
Step 7.2: Run --method {method_2} --file patient_a_week1
Step 7.3: Repeat for all 6 methods
Step 7.4: Run --all to generate comparative paper table
```

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
