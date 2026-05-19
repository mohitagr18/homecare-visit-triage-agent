# The Four-Layer Testing Architecture

Evaluating non-deterministic Large Vision Models (VLMs) on healthcare data requires strict privacy constraints and careful handling of ambiguity. Traditional unit testing is insufficient because the models themselves act as black boxes.

To ensure the evaluation metrics reported in the paper are structurally sound and reproducible, this repository uses a Four-Layer Testing Architecture. This structure guarantees that the evaluation engine is deterministic and trustworthy, independent of whichever LLM is being benchmarked.

## Layer 1: Component Unit Testing (The Business Logic)
This layer proves that the fundamental evaluation arithmetic, parsing rules, and routing decisions are strictly deterministic. It tests isolated functions without invoking the LangGraph state machine. Any failure here indicates a broken mathematical rule (such as flawed tolerance arithmetic), preventing the pipeline from blindly trusting upstream metrics.

## Layer 2: Graph Integration Testing (The State Machine)
This layer proves the entire LangGraph workflow correctly propagates state and writes secure artifacts across the entire pipeline. It runs end-to-end on synthetic data to verify that clean data flows seamlessly to the final report, that malformed data is gracefully handled, and that zero PHI leaks into the final `.json` or `.md` outputs.

## Layer 3: Human-in-the-Loop Testing (The Trust Boundary)
This layer proves that ambiguous or borderline extractions are surfaced to human operators instead of being silently accepted or hallucinated away by the agent. By simulating an execution pause and a human resume payload, this layer mechanically guarantees the LangGraph halts and asks for help when conflicting signals are detected.

## Layer 4: Dataset Evaluation Testing (The Continuous Benchmark)
This layer treats the benchmarking metrics themselves as regression tests against the actual dataset. It acts as a continuous quality guard against model degradation. If a new extraction method or LLM prompt change causes the total accuracy to drop below a conservative baseline, or if temporal hallucinations trigger data anomalies, the evaluation test suite physically fails.
