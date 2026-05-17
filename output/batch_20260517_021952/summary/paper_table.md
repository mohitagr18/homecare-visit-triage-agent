# Benchmark Results

Run ID: `batch_20260517_021952`  
Timestamp: 2026-05-17T06:19:52.634209Z  
Hours tolerance: ±15 min  
Time tolerance: ±30 min

| Method | GT Hours Acc (±15m) | GT Time-In Acc (±30m) | GT Time-Out Acc (±30m) | Fully Correct | Hours Mismatch | Files | GT Rows |
|---|---|---|---|---|---|---|---|
| band_crop_vlm_cloud | 83.3% | 65.5% | 68.3% | 65.5% | 10.7% | 30 | 26 |
| layout_guided_vlm_cloud | 76.0% | 52.1% | 55.0% | 52.1% | 10.2% | 30 | 23 |
| layout_guided_vlm_local | 69.4% | 48.8% | 53.6% | 44.0% | 27.0% | 21 | 14 |
| ocr_only | 80.0% | 80.0% | 50.0% | 50.0% | 88.3% | 10 | 8 |
| ppocr_grid | 80.0% | 80.0% | 50.0% | 50.0% | 73.1% | 13 | 8 |
| vlm_full_page | 69.4% | 48.8% | 41.1% | 31.5% | 26.2% | 20 | 18 |

> **Primary metric:** GT Hours Accuracy (±15 min)
> All source files use anonymized identifiers (PHI-safe output).
