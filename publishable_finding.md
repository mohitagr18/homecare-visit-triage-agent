# Publishable Finding: Unsupervised Detection of Date Extraction Anomalies

One of the significant advantages of the four-layer benchmarking architecture implemented in this project is its ability to surface critical data quality anomalies without relying on perfect, 100% complete ground truth coverage.

## The Observation
During pipeline evaluation across a dataset containing sparse ground truth labels, we observed a scenario where a specific patient (`H.Leal`) successfully resolved via the PHI-anonymization bridge (`NameResolver`), yet zero of the extracted rows matched any ground truth records. 

The extracted dates were:
- `2025-01-14`
- `2025-01-15`
- `2025-12-03`

However, the known ground truth temporal bounds for this patient were:
- `2025-12-24` to `2025-12-30`
- `2025-12-31` to `2026-01-06`

## The Significance
The pipeline automatically detected that while the *patient identity* was correctly extracted and mapped, the temporal data completely disjointed from the known periods of care. Instead of silently reporting `0% Accuracy` or a benign `No Ground Truth Match`, the benchmarker raised a **Data Anomaly Warning**:

> `DATA ANOMALY: patient_c_week3.pdf resolved to a known patient, but 0/3 extracted dates matched GT. Extracted dates: ['2025-01-14', '2025-01-15', '2025-12-03']. This likely indicates an extraction pipeline error (e.g., misread year/month).`

## Why This Matters for IEEE
This behavior highlights a **key methodological contribution** for the IEEE paper:

1. **Defensive Evaluation**: Traditional benchmarkers assume that if a row doesn't match GT, it's merely a coverage gap. This pipeline implements *defensive evaluation*, utilizing temporal constraints to probabilistically distinguish between a "coverage gap" and a "hallucination/OCR failure".
2. **Partial Ground Truth Utility**: It proves that ground truth is useful even for rows it doesn't explicitly label. The *existence* of temporal bounds in the GT metadata provides a constraint mechanism to audit un-annotated rows.
3. **Early Warning System for Upstream Failure**: Misreading a year (e.g., 2026 read as 2025) is a common failure mode in LLM/VLM extraction. This benchmark structure catches these systemic extraction biases deterministically before they pollute downstream medical billing systems.
