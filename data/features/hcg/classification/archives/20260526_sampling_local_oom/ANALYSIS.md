# HCG Classification Sampling Result Archive

Archive time: 2026-05-26

Archived report:

```text
data/features/hcg/classification/archives/20260526_sampling_local_oom/ANALYSIS.md
```

Source results directory, ignored by Git:

```text
data/features/hcg/classification/results/
```

## Scope

This concise archive report summarizes the local sampling / limited classification run executed on the
low-memory `marktom` machine. The run used the full A/B/C parquet inputs, but the
actual completed model metrics are only available for feature group A.

The completed A tasks used:

| Split | Rows |
| --- | ---: |
| train | 200,000 |
| valid | 100,000 |
| test | 100,000 |

The B and C tasks attempted the same sampled scale, but the worker processes were
killed while loading data. LightGBM tasks were skipped by the memory guard.

## Result Integrity

Result check:

```bash
PYTHONPATH=src python3 scripts/check_hcg_classifier_results.py \
  --results-dir data/features/hcg/classification/results \
  --expected-feature-groups A,B,C \
  --expected-models dummy_most_frequent,dummy_stratified,logistic_sgd,decision_tree,lightgbm,knn_sample \
  --allow-failed \
  --report data/features/hcg/classification/results/check_report.md \
  --json-report data/features/hcg/classification/results/check_report.json
```

Check status: PASS. The completed A outputs are structurally complete, and B/C
failed or skipped tasks are explicitly recorded in `task_status.json`.

## Completed Metrics

| Feature | Model | Status | Macro-F1 | Weighted-F1 | Accuracy |
| --- | --- | --- | ---: | ---: | ---: |
| A | knn_sample | completed | 0.248841 | 0.609144 | 0.619830 |
| A | decision_tree | completed | 0.187873 | 0.666471 | 0.690470 |
| A | logistic_sgd | completed | 0.106740 | 0.486722 | 0.518300 |
| A | dummy_stratified | completed | 0.015424 | 0.162350 | 0.162290 |
| A | dummy_most_frequent | completed | 0.007791 | 0.112072 | 0.266390 |
| A | lightgbm | skipped | | | |
| B | all non-LightGBM models | failed | | | |
| B | lightgbm | skipped | | | |
| C | all non-LightGBM models | failed | | | |
| C | lightgbm | skipped | | | |

## Analysis

The only valid performance comparison inside this archive is among A-group raw
feature models. `A/knn_sample` has the highest Macro-F1 at 0.248841, while
`A/decision_tree` has the highest Weighted-F1 at 0.666471 and Accuracy at
0.690470. This indicates strong class imbalance: weighted metrics are dominated
by frequent protocol classes, while Macro-F1 remains low.

This archive cannot answer whether HCG embedding features help classification.
Feature group B and feature group C produced no completed model metrics because
the local 7.7 GiB memory environment killed workers during parquet loading for
the 258-feature and 349-feature sampled matrices. The failures are environment
capacity signals, not model-quality signals.

LightGBM was not evaluated in this archive. Its tasks were skipped by memory
guard before loading data:

| Task | Memory guard reason |
| --- | --- |
| A/lightgbm | estimated_peak_gb=4.57 exceeds safe_limit_gb=3.18 |
| B/lightgbm | estimated_peak_gb=5.61 exceeds safe_limit_gb=4.94 |
| C/lightgbm | estimated_peak_gb=6.18 exceeds safe_limit_gb=4.78 |

## Conclusion

Use this archive as evidence that the training pipeline, reporting, plotting and
failure recording work on the local machine. Do not use it as the final A/B/C
classification conclusion. Final HCG embedding effectiveness requires a
high-memory run where B and C complete, preferably on the 98 GiB / RTX 4090
environment already documented in `docs/experiment_record.md`.
