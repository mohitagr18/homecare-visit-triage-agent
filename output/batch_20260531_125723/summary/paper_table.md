# Benchmark Results

Run ID: `batch_20260531_125723`  
Timestamp: 2026-05-31T16:57:24.355487Z  
Hours tolerance: ±15 min  
Time tolerance: ±30 min

| Method | GT Hours Acc (±15m) | GT Time-In Acc (±30m) | GT Time-Out Acc (±30m) | Fully Correct | Hours Mismatch | Files | GT Rows |
|---|---|---|---|---|---|---|---|
| band_crop_vlm_cloud | 85.4% | 75.1% | 75.2% | 75.5% | 10.7% | 30 | 171 |
| layout_guided_vlm_cloud | 79.2% | 69.2% | 68.3% | 68.8% | 10.2% | 30 | 155 |
| layout_guided_vlm_local | 58.5% | 59.3% | 54.9% | 50.0% | 27.0% | 21 | 108 |
| ocr_only | 42.7% | 36.0% | 41.7% | 13.3% | 88.3% | 10 | 29 |
| ppocr_grid | 44.6% | 38.3% | 34.7% | 19.4% | 73.1% | 13 | 36 |
| vlm_full_page | 67.2% | 61.1% | 50.4% | 48.4% | 26.2% | 20 | 85 |

> **Primary metric:** GT Hours Accuracy (±15 min)
> All source files use anonymized identifiers (PHI-safe output).
