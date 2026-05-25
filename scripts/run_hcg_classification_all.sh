#!/usr/bin/env bash
set -euo pipefail

PYTHONPATH=src python3 scripts/train_hcg_classifiers.py \
  --dataset-dir data/features/hcg/classification/datasets \
  --output-dir data/features/hcg/classification/results \
  --runs-dir runs/hcg_classification \
  --feature-groups A,B,C \
  --models dummy,logistic_sgd,decision_tree,lightgbm,knn_sample \
  --sample-train 0 \
  --sample-valid 0 \
  --sample-test 0 \
  --knn-train-sample 200000 \
  --knn-test-sample 100000 \
  --tensorboard \
  --progress \
  --render-figures \
  --seed 20260525 \
  --resume
