# LangSmith Tracing

This project supports three tracing modes controlled by a single environment variable. The API key is already configured in `.env`.

## Quick reference

| Mode | What gets traced | How to activate |
|---|---|---|
| `off` | Nothing | `LANGSMITH_TRACE_MODE=off` |
| `evaluation_only` | Each `evaluate_file` call per source file | `LANGSMITH_TRACE_MODE=evaluation_only` (default) |
| `all_tests` | Entire pytest session + evaluation | `LANGSMITH_TRACE_MODE=all_tests` |

## Running with tracing off

```bash
LANGSMITH_TRACE_MODE=off uv run python scripts/run_benchmark.py --method band_crop_vlm_cloud --all
```

Or add `LANGSMITH_TRACE_MODE=off` to your `.env`.

## Running with evaluation-only tracing (default)

This is the default. Each call to `evaluate_file` appears as a separate run in LangSmith with the source file name, method, and row count attached as metadata.

```bash
uv run python scripts/run_benchmark.py --method band_crop_vlm_cloud --all --skip-review
```

Or explicitly:

```bash
LANGSMITH_TRACE_MODE=evaluation_only uv run python scripts/run_benchmark.py --method band_crop_vlm_cloud --all
```

You will see one trace per anonymized source file in the `visit-triage-agent-test` project on LangSmith.

## Running with all-tests tracing

This enables tracing across the entire pytest session. Every test that invokes LangGraph or evaluation logic will appear in LangSmith.

```bash
LANGSMITH_TRACE_MODE=all_tests uv run pytest tests/
```

## Using the tracing utilities in code

```python
from src.tracing import tracing_ctx, traceable_evaluation

# Wrap a block — no-op if tracing is off
with tracing_ctx("my_step", tags=["layer:4"], metadata={"method": "band_crop"}):
    result = evaluate_file(...)

# Or decorate a function
@traceable_evaluation(name="score_row", tags=["unit"])
def score_row(row, gt):
    ...
```

## Adding LANGSMITH_TRACE_MODE to .env

```
LANGSMITH_TRACE_MODE=evaluation_only   # or: off, all_tests
```

## How it works

The `src/tracing.py` module reads `LANGSMITH_TRACE_MODE` and gates the `tracing_context` call from the LangSmith SDK. When mode is `off` or the required mode is not met, the context manager is a pure passthrough with zero overhead. The evaluation node in `src/nodes.py` uses `tracing_ctx` around each `evaluate_file` call. The test session uses `pytest_configure` in `conftest.py` to enable background tracing when mode is `all_tests`.
