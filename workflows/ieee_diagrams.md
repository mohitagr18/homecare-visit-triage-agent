# IEEE Paper Diagrams: Document Extraction Benchmark

The following Mermaid diagrams visualize the core methodology and architectural achievements of the benchmarking pipeline. They are formatted specifically for inclusion in academic IEEE papers.

---

## 1. The Stateful LangGraph Workflow
This diagram illustrates the state machine transitioning data from raw extraction through normalization, evaluation, and conditionally halting for human review (HITL) before final reporting.

```mermaid
stateDiagram-v2
    direction TB
    
    [*] --> IngestNode: Start Batch
    
    IngestNode --> NormalizeNode: Raw Extraction Rows
    note right of NormalizeNode: Enforce Typing (Dates/Times)\nDrop Malformed Rows
    
    NormalizeNode --> EvaluateNode: Normalized Rows
    note right of EvaluateNode: Score vs Ground Truth\nApply ±15m / ±30m Tolerances
    
    EvaluateNode --> TriageDecision: EvalResults & Flags
    
    state TriageDecision <<choice>>
    TriageDecision --> HumanReviewNode: if needs_review == True
    TriageDecision --> ReportNode: if needs_review == False
    
    HumanReviewNode --> ReportNode: Inject Human Decisions (Resume)
    
    ReportNode --> [*]: Write Final Artifacts
    note right of ReportNode: IEEE Table (paper_table.md)\nAggregate JSON
```

---

## 2. PHI Isolation & The One-Way NameResolver
This diagram proves to reviewers how the pipeline handles real patient data (PHI) mathematically without ever leaking it into the final public artifacts.

```mermaid
flowchart TD
    subgraph Input ["Untrusted Domain LLM Outputs"]
        A[Extracted Row] -->|Source: patient_c_week3.pdf| B(Normalize Node)
    end
    
    subgraph SecureEngine ["Secure Memory Domain"]
        C[(name_mapping.db)] -.->|Yields: H.Leal| D{Name Resolver}
        B -->|Queries: patient_c| D
        
        D -->|Lookup Key: H.Leal, Date| E[Ground Truth Map]
        F[(ground_truth.xlsx)] -.-> E
        
        E -->|Yields GT Row| G(Evaluate Node)
        B -->|Yields Anon Row| G
        G -->|Matches Math| H[RowEvalResult]
    end
    
    subgraph Output ["Anonymized Public Domain"]
        H -->|Strictly patient_c_week3.pdf| I[run_summary.json]
        H -->|Strictly patient_c_week3.pdf| J[failures.json]
    end
    
    style SecureEngine fill:#f9f2f4,stroke:#333,stroke-width:2px
    style Output fill:#f4f9f4,stroke:#333,stroke-width:2px
```

---

## 3. The Four-Layer Testing Methodology
This diagram illustrates the cascading safety guarantees of the pipeline. If any layer fails, the pipeline halts, preventing flawed metrics from reaching the IEEE results table.

```mermaid
flowchart LR
    subgraph Layer1 ["Layer 1: Unit Testing"]
        direction TB
        L1A[Tolerance Boundaries] --> L1B[Scoring Arithmetic]
    end
    
    subgraph Layer2 ["Layer 2: Integration Testing"]
        direction TB
        L2A[State Consistency] --> L2B[Zero PHI Leakage]
    end
    
    subgraph Layer3 ["Layer 3: HITL Testing"]
        direction TB
        L3A[Interrupt on Ambiguity] --> L3B[Wait for Human State]
    end
    
    subgraph Layer4 ["Layer 4: Evaluation Testing"]
        direction TB
        L4A[Baseline Accuracy Floors] --> L4B[Temporal Hallucination Catch]
    end
    
    Layer1 ==>|Mathematical Proof| Layer2
    Layer2 ==>|Architectural Proof| Layer3
    Layer3 ==>|Safety Proof| Layer4
    Layer4 ==>|Final Output| Pub((IEEE Paper Table))
    
    style Layer1 fill:#e1f5fe,stroke:#0288d1
    style Layer2 fill:#e8f5e9,stroke:#388e3c
    style Layer3 fill:#fff3e0,stroke:#f57c00
    style Layer4 fill:#fce4ec,stroke:#c2185b
    style Pub fill:#ede7f6,stroke:#512da8,stroke-width:4px
```

---

## 4. Pipeline Execution (Automated vs. Manual Run)
A sequence diagram demonstrating how the CLI handles batch automation compared to a single-file manual review scenario.

```mermaid
sequenceDiagram
    participant CLI as run_benchmark.py
    participant Graph as LangGraph Engine
    participant Eval as Evaluate Node
    participant User as Human Reviewer
    
    CLI->>Graph: invoke(method="vlm_full_page", all=True)
    Graph->>Eval: Score all 30 files
    Eval-->>Graph: Found 1 flagged row
    
    alt --skip-review flag is NOT provided
        Graph->>CLI: Interrupt! Yields snapshot.next
        CLI->>User: "Graph paused. Review required."
        User->>CLI: Sends accept decision
        CLI->>Graph: invoke(Command(resume=decision))
    else --skip-review flag IS provided (CI/CD)
        Graph->>CLI: Interrupt! Yields snapshot.next
        CLI->>Graph: Auto-inject accept decision
    end
    
    Graph->>CLI: Write artifacts & finish
```
