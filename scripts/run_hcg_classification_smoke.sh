#!/usr/bin/env bash
set -euo pipefail

PYTHONPATH=src python3 scripts/train_hcg_classifiers.py \
  --dataset-dir data/features/hcg/classification/datasets \
  --output-dir data/features/hcg/classification/results_smoke \
  --runs-dir runs/hcg_classification_smoke \
  --feature-groups A,B,C \
  --models dummy,logistic_sgd,decision_tree,lightgbm,knn_sample \
  --sample-train 100000 \
  --sample-valid 20000 \
  --sample-test 20000 \
  --knn-train-sample 50000 \
  --knn-test-sample 20000 \
  --tensorboard \
  --progress \
  --render-figures \
  --seed 20260525 \
  --resume
