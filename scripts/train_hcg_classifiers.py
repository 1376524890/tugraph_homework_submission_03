#!/usr/bin/env python3
"""Train and evaluate HCG classification baselines for feature groups A/B/C."""

from __future__ import annotations

import argparse
import csv
import gc
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
import traceback
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from tugraph_homework.common import ROOT
from tugraph_homework.experiment_monitor import (
    EventLogger,
    ProgressDisplay,
    StatusBoard,
    append_csv_row,
    atomic_write_json,
    atomic_write_text,
    elapsed,
    iter_batches,
    read_json,
    utc_now_iso,
)


DATASET_FILES = {
    "A": "A_raw_flow_features.parquet",
    "B": "B_hcg_flow_emb_256.parquet",
    "C": "C_raw_plus_hcg_flow_emb.parquet",
}
META_COLUMNS = {"record_id", "target", "split", "src_endpoint", "dst_endpoint"}
DEFAULT_MODEL_ALIASES = {
    "dummy": ["dummy_most_frequent", "dummy_stratified"],
    "dummy_most_frequent": ["dummy_most_frequent"],
    "dummy_stratified": ["dummy_stratified"],
    "logistic_sgd": ["logistic_sgd"],
    "decision_tree": ["decision_tree"],
    "lightgbm": ["lightgbm"],
    "knn_sample": ["knn_sample"],
}
STAGES = [
    "init",
    "load_data",
    "prepare_xy",
    "fit_preprocessor",
    "train",
    "predict_valid",
    "predict_test",
    "evaluate",
    "save_outputs",
    "completed",
    "failed",
]
METRICS_LIVE_FIELDS = [
    "task_id",
    "feature_group",
    "model_name",
    "status",
    "accuracy",
    "macro_precision",
    "macro_recall",
    "macro_f1",
    "weighted_precision",
    "weighted_recall",
    "weighted_f1",
    "train_seconds",
    "inference_seconds",
    "train_rows",
    "valid_rows",
    "test_rows",
    "feature_count",
    "target_class_count",
    "model_path",
    "metrics_path",
    "tensorboard_logdir",
    "completed_at",
    "error_message",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train HCG classifiers for A/B/C classification features.")
    parser.add_argument("--dataset-dir", type=Path, default=ROOT / "data/features/hcg/classification/datasets")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "data/features/hcg/classification/results")
    parser.add_argument("--runs-dir", type=Path, default=ROOT / "runs/hcg_classification")
    parser.add_argument("--feature-groups", default="A,B,C")
    parser.add_argument("--models", default="dummy,logistic_sgd,decision_tree,lightgbm,knn_sample")
    parser.add_argument("--target-col", default="target")
    parser.add_argument("--split-col", default="split")
    parser.add_argument("--seed", type=int, default=20260525)
    parser.add_argument("--sample-train", type=int, default=0)
    parser.add_argument("--sample-valid", type=int, default=0)
    parser.add_argument("--sample-test", type=int, default=0)
    parser.add_argument("--knn-train-sample", type=int, default=200_000)
    parser.add_argument("--knn-test-sample", type=int, default=100_000)
    parser.add_argument("--knn-predict-batch-size", type=int, default=10_000)
    parser.add_argument("--allow-full-knn", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--only-missing", action="store_true")
    parser.add_argument("--tensorboard", dest="tensorboard", action="store_true", default=False)
    parser.add_argument("--no-tensorboard", dest="tensorboard", action="store_false")
    parser.add_argument("--progress", dest="progress", action="store_true", default=True)
    parser.add_argument("--no-progress", dest="progress", action="store_false")
    parser.add_argument("--render-figures", action="store_true")
    parser.add_argument("--overwrite-summary", action="store_true")
    parser.add_argument("--fail-fast", action="store_true")
    parser.add_argument("--logistic-max-epochs", type=int, default=20)
    parser.add_argument("--logistic-batch-size", type=int, default=100_000)
    parser.add_argument("--lightgbm-n-estimators", type=int, default=3000)
    parser.add_argument("--lightgbm-early-stopping-rounds", type=int, default=100)
    parser.add_argument("--isolate-tasks", dest="isolate_tasks", action="store_true", default=True)
    parser.add_argument("--no-isolate-tasks", dest="isolate_tasks", action="store_false")
    parser.add_argument("--memory-guard", dest="memory_guard", action="store_true", default=True)
    parser.add_argument("--no-memory-guard", dest="memory_guard", action="store_false")
    parser.add_argument("--max-estimated-memory-gb", type=float, default=0.0)
    parser.add_argument("--min-available-memory-gb", type=float, default=2.0)
    parser.add_argument("--worker-feature-group", default="", help=argparse.SUPPRESS)
    parser.add_argument("--worker-model", default="", help=argparse.SUPPRESS)
    return parser.parse_args()


def resolve_path(path: Path) -> Path:
    return path if path.is_absolute() else ROOT / path


def require_dependencies(model_names: list[str]) -> None:
    missing = []
    for module in ["sklearn", "joblib"]:
        if importlib.util.find_spec(module) is None:
            missing.append(module)
    if "lightgbm" in model_names and importlib.util.find_spec("lightgbm") is None:
        missing.append("lightgbm")
    if missing:
        install = "python3 -m pip install scikit-learn joblib lightgbm matplotlib"
        raise RuntimeError(f"Missing required training dependencies: {', '.join(sorted(set(missing)))}. Install with: {install}")


def parse_csv_list(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def expand_models(models_arg: str) -> list[str]:
    expanded: list[str] = []
    for item in parse_csv_list(models_arg):
        if item not in DEFAULT_MODEL_ALIASES:
            raise ValueError(f"Unknown model `{item}`. Valid values: {', '.join(DEFAULT_MODEL_ALIASES)}")
        expanded.extend(DEFAULT_MODEL_ALIASES[item])
    return list(dict.fromkeys(expanded))


def task_id(feature_group: str, model_name: str) -> str:
    return f"{feature_group}__{model_name}"


def task_dir(output_dir: Path, feature_group: str, model_name: str) -> Path:
    return output_dir / feature_group / model_name


def completed_outputs_exist(directory: Path) -> bool:
    status = read_json(directory / "task_status.json", {})
    required = ["metrics.json", "classification_report.csv", "confusion_matrix.csv"]
    return status.get("status") == "completed" and all((directory / name).exists() for name in required)


def available_memory_gb() -> float:
    try:
        import psutil  # type: ignore

        return float(psutil.virtual_memory().available / (1024**3))
    except Exception:
        pass
    try:
        with Path("/proc/meminfo").open("r", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("MemAvailable:"):
                    return float(line.split()[1]) / (1024**2)
    except OSError:
        pass
    return 0.0


def parquet_profile(path: Path, args: argparse.Namespace, model_name: str) -> dict[str, Any]:
    import pyarrow.parquet as pq

    pf = pq.ParquetFile(path)
    columns = pf.schema_arrow.names
    feature_count = len([col for col in columns if col not in META_COLUMNS and col not in {args.target_col, args.split_col}])
    total_rows = int(pf.metadata.num_rows)
    if any(n > 0 for n in (args.sample_train, args.sample_valid, args.sample_test)):
        rows = min(total_rows, sum(n for n in (args.sample_train, args.sample_valid, args.sample_test) if n > 0))
    elif model_name == "knn_sample" and not args.allow_full_knn:
        rows = total_rows
    else:
        rows = total_rows
    matrix_gb = rows * feature_count * 4 / (1024**3)
    model_factor = {
        "dummy_most_frequent": 2.2,
        "dummy_stratified": 2.2,
        "logistic_sgd": 3.4,
        "decision_tree": 3.0,
        "lightgbm": 4.2,
        "knn_sample": 2.8,
    }.get(model_name, 3.0)
    fixed_gb = {
        "dummy_most_frequent": 1.0,
        "dummy_stratified": 1.0,
        "logistic_sgd": 2.0,
        "decision_tree": 2.0,
        "lightgbm": 4.0,
        "knn_sample": 2.0,
    }.get(model_name, 2.0)
    estimated_gb = matrix_gb * model_factor + fixed_gb
    return {
        "rows": rows,
        "total_rows": total_rows,
        "feature_count": feature_count,
        "matrix_gb": matrix_gb,
        "estimated_peak_gb": estimated_gb,
        "parquet_size_gb": path.stat().st_size / (1024**3),
    }


def memory_limit_gb(args: argparse.Namespace) -> float:
    if args.max_estimated_memory_gb > 0:
        return args.max_estimated_memory_gb
    avail = available_memory_gb()
    if avail <= 0:
        return 0.0
    return max(0.0, avail - args.min_available_memory_gb)


def should_skip_for_memory(dataset_path: Path, model_name: str, args: argparse.Namespace) -> tuple[bool, dict[str, Any], str]:
    profile = parquet_profile(dataset_path, args, model_name)
    if not args.memory_guard:
        return False, profile, ""
    limit = memory_limit_gb(args)
    if limit <= 0:
        return False, profile, "memory availability unknown"
    if profile["estimated_peak_gb"] > limit:
        message = (
            f"estimated_peak_gb={profile['estimated_peak_gb']:.2f} exceeds safe_limit_gb={limit:.2f}; "
            f"rows={profile['rows']}, features={profile['feature_count']}, matrix_gb={profile['matrix_gb']:.2f}"
        )
        return True, profile, message
    return False, profile, ""


def initial_status(tid: str, feature_group: str, model_name: str) -> dict[str, Any]:
    now = utc_now_iso()
    return {
        "task_id": tid,
        "feature_group": feature_group,
        "model_name": model_name,
        "status": "pending",
        "created_at": now,
        "started_at": "",
        "updated_at": now,
        "finished_at": "",
        "elapsed_seconds": 0.0,
        "stage": "init",
        "completed_stages": [],
        "failed_stage": "",
        "error_message": "",
        "train_rows": 0,
        "valid_rows": 0,
        "test_rows": 0,
        "feature_count": 0,
        "metrics_path": "",
        "model_path": "",
        "tensorboard_status": "disabled",
        "memory_guard": {},
    }


def update_status(path: Path, status: dict[str, Any], stage: str | None = None, state: str | None = None, started: float | None = None) -> None:
    if stage:
        status["stage"] = stage
        if stage not in ("failed", "completed") and stage not in status["completed_stages"]:
            status["completed_stages"].append(stage)
    if state:
        status["status"] = state
    status["updated_at"] = utc_now_iso()
    if started is not None:
        status["elapsed_seconds"] = elapsed(started)
    atomic_write_json(path, status)


def append_status_row(args: argparse.Namespace, row: dict[str, Any]) -> None:
    append_csv_row(args.output_dir / "metrics_live.csv", METRICS_LIVE_FIELDS, row)


def mark_task_skipped(
    directory: Path,
    args: argparse.Namespace,
    status: dict[str, Any],
    started: float,
    reason: str,
    event_logger: EventLogger,
    status_board: StatusBoard,
    display: ProgressDisplay,
) -> dict[str, Any]:
    status.update(
        {
            "status": "skipped",
            "stage": "completed",
            "finished_at": utc_now_iso(),
            "elapsed_seconds": elapsed(started),
            "error_message": reason,
        }
    )
    atomic_write_json(directory / "task_status.json", status)
    row = {
        "task_id": status["task_id"],
        "feature_group": status["feature_group"],
        "model_name": status["model_name"],
        "status": "skipped",
        "train_rows": status.get("train_rows", 0),
        "valid_rows": status.get("valid_rows", 0),
        "test_rows": status.get("test_rows", 0),
        "feature_count": status.get("feature_count", 0),
        "metrics_path": "",
        "model_path": "",
        "tensorboard_logdir": "",
        "completed_at": status["finished_at"],
        "error_message": reason,
    }
    append_status_row(args, row)
    event_logger.emit(
        "task_failed",
        status["task_id"],
        status["feature_group"],
        status["model_name"],
        "memory_guard",
        "skipped",
        elapsed(started),
        status.get("train_rows", 0),
        status.get("valid_rows", 0),
        status.get("test_rows", 0),
        status.get("feature_count", 0),
        message=reason,
    )
    status_board.mark_failed(row)
    display.update(f"{status['task_id']} skipped memory guard", advance=1)
    return row


def sample_split(df: pd.DataFrame, split_col: str, split: str, n: int, seed: int) -> pd.DataFrame:
    part = df[df[split_col] == split]
    if n and len(part) > n:
        return part.sample(n=n, random_state=seed)
    return part


def load_dataset(path: Path, args: argparse.Namespace, seed: int) -> tuple[pd.DataFrame, list[str]]:
    df = pd.read_parquet(path)
    feature_cols = [col for col in df.columns if col not in META_COLUMNS and col not in {args.target_col, args.split_col}]
    if any(n > 0 for n in (args.sample_train, args.sample_valid, args.sample_test)):
        parts = [
            sample_split(df, args.split_col, "train", args.sample_train, seed),
            sample_split(df, args.split_col, "valid", args.sample_valid, seed + 1),
            sample_split(df, args.split_col, "test", args.sample_test, seed + 2),
        ]
        df = pd.concat(parts, ignore_index=True)
    return df, feature_cols


def make_xy(df: pd.DataFrame, feature_cols: list[str], args: argparse.Namespace) -> dict[str, Any]:
    from sklearn.preprocessing import LabelEncoder

    labels = df[args.target_col].astype(str).to_numpy()
    encoder = LabelEncoder()
    encoder.fit(labels)
    mapping = {str(label): int(idx) for idx, label in enumerate(encoder.classes_)}
    data: dict[str, Any] = {"label_mapping": mapping, "classes": encoder.classes_.tolist()}
    for split in ("train", "valid", "test"):
        part = df[df[args.split_col] == split]
        data[f"X_{split}"] = part[feature_cols].to_numpy(dtype=np.float32, copy=True)
        data[f"y_{split}"] = encoder.transform(part[args.target_col].astype(str).to_numpy()).astype(np.int64, copy=False)
        data[f"record_{split}"] = part["record_id"].astype(str).to_numpy() if "record_id" in part.columns else np.arange(len(part)).astype(str)
    return data


def get_summary_writer(enabled: bool, model_name: str, logdir: Path) -> tuple[Any, str]:
    if not enabled or model_name not in {"logistic_sgd", "lightgbm"}:
        return None, "disabled"
    try:
        from torch.utils.tensorboard import SummaryWriter  # type: ignore

        return SummaryWriter(str(logdir)), "enabled"
    except Exception:
        try:
            from tensorboardX import SummaryWriter  # type: ignore

            return SummaryWriter(str(logdir)), "enabled"
        except Exception:
            return None, "unavailable"


def classification_metrics(y_true: np.ndarray, y_pred: np.ndarray, classes: list[str]) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, precision_recall_fscore_support

    accuracy = float(accuracy_score(y_true, y_pred))
    macro = precision_recall_fscore_support(y_true, y_pred, average="macro", zero_division=0)
    weighted = precision_recall_fscore_support(y_true, y_pred, average="weighted", zero_division=0)
    metrics = {
        "accuracy": accuracy,
        "macro_precision": float(macro[0]),
        "macro_recall": float(macro[1]),
        "macro_f1": float(macro[2]),
        "weighted_precision": float(weighted[0]),
        "weighted_recall": float(weighted[1]),
        "weighted_f1": float(weighted[2]),
    }
    labels = np.arange(len(classes))
    report = pd.DataFrame(
        classification_report(y_true, y_pred, labels=labels, target_names=classes, output_dict=True, zero_division=0)
    ).T
    matrix = pd.DataFrame(confusion_matrix(y_true, y_pred, labels=labels), index=classes, columns=classes)
    return metrics, report, matrix


def save_predictions_sample(path: Path, records: np.ndarray, y_true: np.ndarray, y_pred: np.ndarray, classes: list[str], n: int = 5000) -> None:
    count = min(n, len(y_true))
    rows = pd.DataFrame(
        {
            "record_id": records[:count],
            "y_true": [classes[int(v)] for v in y_true[:count]],
            "y_pred": [classes[int(v)] for v in y_pred[:count]],
        }
    )
    rows.to_csv(path, index=False)


def plot_task_figures(directory: Path, model_name: str) -> None:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import pandas as pd
    except ImportError:
        return
    fig_dir = directory / "figures"
    fig_dir.mkdir(parents=True, exist_ok=True)
    eval_path = directory / "eval_history.csv"
    if eval_path.exists():
        hist = pd.read_csv(eval_path)
        if not hist.empty:
            plt.figure(figsize=(8, 4.8))
            x = hist["iteration"] if "iteration" in hist.columns else hist.index + 1
            for col in ("valid_multi_logloss", "valid_macro_f1", "valid_weighted_f1", "valid_accuracy"):
                if col in hist.columns:
                    plt.plot(x, hist[col], label=col)
            plt.xlabel("Iteration")
            plt.ylabel("Metric")
            plt.title(f"{model_name} learning curve")
            plt.legend()
            plt.tight_layout()
            plt.savefig(fig_dir / "learning_curve.png", dpi=180)
            plt.close()
    cm_path = directory / "confusion_matrix.csv"
    if cm_path.exists():
        cm = pd.read_csv(cm_path, index_col=0)
        top = cm.sum(axis=1).sort_values(ascending=False).head(20).index
        sub = cm.loc[top, top].astype(float)
        denom = sub.sum(axis=1).replace(0, 1)
        norm = sub.div(denom, axis=0)
        plt.figure(figsize=(10, 8))
        plt.imshow(norm.to_numpy(), aspect="auto", cmap="Blues")
        plt.xticks(range(len(top)), top, rotation=90, fontsize=7)
        plt.yticks(range(len(top)), top, fontsize=7)
        plt.colorbar(label="Row-normalized count")
        plt.title(f"{model_name} confusion matrix top 20")
        plt.tight_layout()
        plt.savefig(fig_dir / "confusion_matrix.png", dpi=180)
        plt.close()
    imp_path = directory / "feature_importance_gain.csv"
    if imp_path.exists():
        imp = pd.read_csv(imp_path).sort_values("importance", ascending=False).head(30)
        if not imp.empty:
            plt.figure(figsize=(9, 7))
            plt.barh(imp["feature"][::-1], imp["importance"][::-1])
            plt.xlabel("Gain importance")
            plt.title("Feature importance top 30")
            plt.tight_layout()
            plt.savefig(fig_dir / "feature_importance.png", dpi=180)
            plt.close()


def train_dummy(model_name: str, xy: dict[str, Any], seed: int) -> tuple[Any, np.ndarray, np.ndarray, float, float, pd.DataFrame | None, dict[str, Any]]:
    from sklearn.dummy import DummyClassifier

    strategy = "most_frequent" if model_name == "dummy_most_frequent" else "stratified"
    clf = DummyClassifier(strategy=strategy, random_state=seed)
    started = time.perf_counter()
    clf.fit(xy["X_train"], xy["y_train"])
    train_seconds = elapsed(started)
    pred_started = time.perf_counter()
    y_valid_pred = clf.predict(xy["X_valid"])
    y_test_pred = clf.predict(xy["X_test"])
    inference_seconds = elapsed(pred_started)
    return clf, y_valid_pred, y_test_pred, train_seconds, inference_seconds, None, {"sampled": False}


def train_decision_tree(model_name: str, xy: dict[str, Any], seed: int) -> tuple[Any, np.ndarray, np.ndarray, float, float, pd.DataFrame | None, dict[str, Any]]:
    from sklearn.tree import DecisionTreeClassifier

    clf = DecisionTreeClassifier(max_depth=40, min_samples_leaf=100, random_state=seed, class_weight=None)
    started = time.perf_counter()
    clf.fit(xy["X_train"], xy["y_train"])
    train_seconds = elapsed(started)
    pred_started = time.perf_counter()
    y_valid_pred = clf.predict(xy["X_valid"])
    y_test_pred = clf.predict(xy["X_test"])
    inference_seconds = elapsed(pred_started)
    return clf, y_valid_pred, y_test_pred, train_seconds, inference_seconds, None, {"sampled": False}


def train_logistic(
    xy: dict[str, Any],
    args: argparse.Namespace,
    writer: Any,
    event_logger: EventLogger,
    tid: str,
    feature_group: str,
    status_board: StatusBoard,
) -> tuple[Any, Any, np.ndarray, np.ndarray, float, float, pd.DataFrame, dict[str, Any]]:
    from sklearn.linear_model import SGDClassifier
    from sklearn.metrics import accuracy_score, precision_recall_fscore_support
    from sklearn.preprocessing import StandardScaler

    scaler = StandardScaler()
    clf = SGDClassifier(
        loss="log_loss",
        penalty="l2",
        alpha=0.0001,
        max_iter=1,
        tol=None,
        random_state=args.seed,
        n_jobs=-1,
        class_weight=None,
    )
    X_train = xy["X_train"]
    y_train = xy["y_train"]
    classes = np.arange(len(xy["classes"]))
    for batch in iter_batches(len(X_train), args.logistic_batch_size):
        scaler.partial_fit(X_train[batch])
    history: list[dict[str, Any]] = []
    train_started = time.perf_counter()
    for epoch in range(1, args.logistic_max_epochs + 1):
        epoch_started = time.perf_counter()
        rng = np.random.default_rng(args.seed + epoch)
        order = rng.permutation(len(X_train))
        for batch in iter_batches(len(order), args.logistic_batch_size):
            idx = order[batch]
            xb = scaler.transform(X_train[idx])
            clf.partial_fit(xb, y_train[idx], classes=classes)
        valid_pred = clf.predict(scaler.transform(xy["X_valid"]))
        macro = precision_recall_fscore_support(xy["y_valid"], valid_pred, average="macro", zero_division=0)
        weighted = precision_recall_fscore_support(xy["y_valid"], valid_pred, average="weighted", zero_division=0)
        row = {
            "iteration": epoch,
            "epoch": epoch,
            "valid_accuracy": float(accuracy_score(xy["y_valid"], valid_pred)),
            "valid_macro_f1": float(macro[2]),
            "valid_weighted_f1": float(weighted[2]),
            "valid_macro_recall": float(macro[1]),
            "epoch_seconds": elapsed(epoch_started),
        }
        history.append(row)
        if writer is not None:
            writer.add_scalar("valid/accuracy", row["valid_accuracy"], epoch)
            writer.add_scalar("valid/macro_f1", row["valid_macro_f1"], epoch)
            writer.add_scalar("valid/weighted_f1", row["valid_weighted_f1"], epoch)
            writer.add_scalar("valid/macro_recall", row["valid_macro_recall"], epoch)
            writer.add_scalar("time/epoch_seconds", row["epoch_seconds"], epoch)
        event_logger.emit(
            "iteration_update",
            task_id=tid,
            feature_group=feature_group,
            model_name="logistic_sgd",
            stage="train",
            status="running",
            current_step=epoch,
            total_steps=args.logistic_max_epochs,
            metrics={"valid_macro_f1": row["valid_macro_f1"], "valid_weighted_f1": row["valid_weighted_f1"]},
        )
        status_board.update_current(tid, "train", {"valid_macro_f1": row["valid_macro_f1"], "valid_weighted_f1": row["valid_weighted_f1"]})
    train_seconds = elapsed(train_started)
    pred_started = time.perf_counter()
    y_valid_pred = clf.predict(scaler.transform(xy["X_valid"]))
    y_test_pred = clf.predict(scaler.transform(xy["X_test"]))
    inference_seconds = elapsed(pred_started)
    return clf, scaler, y_valid_pred, y_test_pred, train_seconds, inference_seconds, pd.DataFrame(history), {"sampled": False}


def train_lightgbm(
    xy: dict[str, Any],
    feature_cols: list[str],
    args: argparse.Namespace,
    writer: Any,
    event_logger: EventLogger,
    tid: str,
    feature_group: str,
    status_board: StatusBoard,
) -> tuple[Any, np.ndarray, np.ndarray, float, float, pd.DataFrame, dict[str, Any], pd.DataFrame, pd.DataFrame]:
    import lightgbm as lgb
    from sklearn.metrics import accuracy_score, precision_recall_fscore_support

    clf = lgb.LGBMClassifier(
        objective="multiclass",
        num_class=len(xy["classes"]),
        n_estimators=args.lightgbm_n_estimators,
        learning_rate=0.05,
        num_leaves=63,
        min_child_samples=100,
        subsample=0.8,
        colsample_bytree=0.8,
        reg_lambda=1.0,
        random_state=args.seed,
        n_jobs=-1,
    )
    evals_result: dict[str, Any] = {}
    history: list[dict[str, Any]] = []

    def progress_callback(env: Any) -> None:
        iteration = int(env.iteration) + 1
        row = {"iteration": iteration}
        for data_name, eval_name, result, _higher_better in env.evaluation_result_list:
            key = f"{data_name}_{eval_name}"
            row[key] = float(result)
        if iteration == 1 or iteration % 50 == 0:
            valid_prob = env.model.predict(xy["X_valid"], num_iteration=iteration)
            valid_pred = np.argmax(valid_prob, axis=1)
            macro = precision_recall_fscore_support(xy["y_valid"], valid_pred, average="macro", zero_division=0)
            weighted = precision_recall_fscore_support(xy["y_valid"], valid_pred, average="weighted", zero_division=0)
            row["valid_accuracy"] = float(accuracy_score(xy["y_valid"], valid_pred))
            row["valid_macro_f1"] = float(macro[2])
            row["valid_weighted_f1"] = float(weighted[2])
            if writer is not None:
                writer.add_scalar("valid/accuracy", row["valid_accuracy"], iteration)
                writer.add_scalar("valid/macro_f1", row["valid_macro_f1"], iteration)
                writer.add_scalar("valid/weighted_f1", row["valid_weighted_f1"], iteration)
                writer.add_scalar("best_iteration", getattr(clf, "best_iteration_", 0) or 0, iteration)
            event_logger.emit(
                "iteration_update",
                task_id=tid,
                feature_group=feature_group,
                model_name="lightgbm",
                stage="train",
                status="running",
                current_step=iteration,
                total_steps=args.lightgbm_n_estimators,
                metrics={"valid_macro_f1": row["valid_macro_f1"], "valid_weighted_f1": row["valid_weighted_f1"]},
            )
            status_board.update_current(
                tid,
                "train",
                {"valid_macro_f1": row["valid_macro_f1"], "valid_weighted_f1": row["valid_weighted_f1"]},
            )
        history.append(row)

    callbacks = [
        lgb.early_stopping(args.lightgbm_early_stopping_rounds, verbose=True),
        lgb.record_evaluation(evals_result),
        progress_callback,
    ]
    train_started = time.perf_counter()
    clf.fit(
        xy["X_train"],
        xy["y_train"],
        eval_set=[(xy["X_valid"], xy["y_valid"])],
        eval_names=["valid"],
        eval_metric="multi_logloss",
        callbacks=callbacks,
    )
    train_seconds = elapsed(train_started)
    pred_started = time.perf_counter()
    y_valid_pred = clf.predict(xy["X_valid"])
    y_test_pred = clf.predict(xy["X_test"])
    inference_seconds = elapsed(pred_started)
    gain = pd.DataFrame({"feature": feature_cols, "importance": clf.booster_.feature_importance(importance_type="gain")})
    split = pd.DataFrame({"feature": feature_cols, "importance": clf.booster_.feature_importance(importance_type="split")})
    return clf, y_valid_pred, y_test_pred, train_seconds, inference_seconds, pd.DataFrame(history), {"sampled": False}, gain, split


def train_knn_sample(
    xy: dict[str, Any],
    args: argparse.Namespace,
    event_logger: EventLogger,
    tid: str,
    feature_group: str,
    status_board: StatusBoard,
) -> tuple[Any, Any, np.ndarray, np.ndarray, float, float, pd.DataFrame | None, dict[str, Any]]:
    from sklearn.neighbors import KNeighborsClassifier
    from sklearn.preprocessing import StandardScaler

    if not args.allow_full_knn and (args.knn_train_sample <= 0 or args.knn_test_sample <= 0):
        raise ValueError("KNN requires sampling unless --allow-full-knn is explicitly set.")
    rng = np.random.default_rng(args.seed)
    train_n = len(xy["X_train"]) if args.allow_full_knn and args.knn_train_sample <= 0 else min(args.knn_train_sample, len(xy["X_train"]))
    valid_n = min(args.knn_test_sample, len(xy["X_valid"]))
    test_n = len(xy["X_test"]) if args.allow_full_knn and args.knn_test_sample <= 0 else min(args.knn_test_sample, len(xy["X_test"]))
    train_idx = rng.choice(len(xy["X_train"]), train_n, replace=False)
    valid_idx = rng.choice(len(xy["X_valid"]), valid_n, replace=False)
    test_idx = rng.choice(len(xy["X_test"]), test_n, replace=False)
    for split, idx in (("valid", valid_idx), ("test", test_idx)):
        xy[f"X_{split}"] = xy[f"X_{split}"][idx]
        xy[f"y_{split}"] = xy[f"y_{split}"][idx]
        xy[f"record_{split}"] = xy[f"record_{split}"][idx]
    X_train = xy["X_train"][train_idx]
    y_train = xy["y_train"][train_idx]
    scaler = StandardScaler()
    train_started = time.perf_counter()
    X_train_scaled = scaler.fit_transform(X_train)
    clf = KNeighborsClassifier(n_neighbors=5, weights="distance", metric="euclidean")
    clf.fit(X_train_scaled, y_train)
    train_seconds = elapsed(train_started)

    def predict_batches(X: np.ndarray, split_name: str) -> np.ndarray:
        preds = []
        total = len(X)
        for slc in iter_batches(total, args.knn_predict_batch_size):
            preds.append(clf.predict(scaler.transform(X[slc])))
            event_logger.emit(
                "iteration_update",
                task_id=tid,
                feature_group=feature_group,
                model_name="knn_sample",
                stage=f"predict_{split_name}",
                status="running",
                current_step=min(slc.stop, total),
                total_steps=total,
                message=f"predicted {min(slc.stop, total)} / {total}",
            )
            status_board.update_current(tid, f"predict_{split_name}")
        return np.concatenate(preds) if preds else np.array([], dtype=np.int64)

    pred_started = time.perf_counter()
    y_valid_pred = predict_batches(xy["X_valid"], "valid")
    y_test_pred = predict_batches(xy["X_test"], "test")
    inference_seconds = elapsed(pred_started)
    return (
        clf,
        scaler,
        y_valid_pred,
        y_test_pred,
        train_seconds,
        inference_seconds,
        None,
        {"sampled": True, "knn_train_sample": train_n, "knn_test_sample": test_n},
    )


def save_outputs(
    directory: Path,
    model_name: str,
    model: Any,
    scaler: Any,
    xy: dict[str, Any],
    feature_cols: list[str],
    y_valid_pred: np.ndarray,
    y_test_pred: np.ndarray,
    train_seconds: float,
    inference_seconds: float,
    total_elapsed_seconds: float,
    extra: dict[str, Any],
    eval_history: pd.DataFrame | None,
    tensorboard_status: str,
    tensorboard_logdir: Path,
    gain_importance: pd.DataFrame | None = None,
    split_importance: pd.DataFrame | None = None,
) -> tuple[dict[str, Any], str]:
    import joblib

    classes = xy["classes"]
    valid_metrics, _, _ = classification_metrics(xy["y_valid"], y_valid_pred, classes)
    test_metrics, report, matrix = classification_metrics(xy["y_test"], y_test_pred, classes)
    directory.mkdir(parents=True, exist_ok=True)
    model_path = directory / ("lightgbm_model.txt" if model_name == "lightgbm" else "model.pkl")
    if model_name == "lightgbm":
        model.booster_.save_model(str(model_path))
    else:
        joblib.dump(model, model_path)
    if scaler is not None:
        joblib.dump(scaler, directory / "scaler.pkl")
    report.to_csv(directory / "classification_report.csv")
    matrix.to_csv(directory / "confusion_matrix.csv")
    save_predictions_sample(directory / "predictions_sample.csv", xy["record_test"], xy["y_test"], y_test_pred, classes)
    atomic_write_json(directory / "feature_columns.json", feature_cols)
    atomic_write_json(directory / "label_mapping.json", xy["label_mapping"])
    if eval_history is not None and not eval_history.empty:
        eval_history.to_csv(directory / "eval_history.csv", index=False)
    if gain_importance is not None:
        gain_importance.to_csv(directory / "feature_importance_gain.csv", index=False)
    if split_importance is not None:
        split_importance.to_csv(directory / "feature_importance_split.csv", index=False)
    metrics = {
        **test_metrics,
        "valid_accuracy": valid_metrics["accuracy"],
        "valid_macro_f1": valid_metrics["macro_f1"],
        "valid_weighted_f1": valid_metrics["weighted_f1"],
        "train_seconds": train_seconds,
        "inference_seconds": inference_seconds,
        "total_elapsed_seconds": total_elapsed_seconds,
        "train_rows": int(len(xy["y_train"])),
        "valid_rows": int(len(xy["y_valid"])),
        "test_rows": int(len(xy["y_test"])),
        "feature_count": int(len(feature_cols)),
        "target_class_count": int(len(classes)),
        "model_path": str(model_path),
        "tensorboard_status": tensorboard_status,
        "tensorboard_logdir": str(tensorboard_logdir) if tensorboard_status == "enabled" else "",
        **extra,
    }
    atomic_write_json(directory / "metrics.json", metrics)
    plot_task_figures(directory, model_name)
    return metrics, str(model_path)


def run_task(
    feature_group: str,
    model_name: str,
    args: argparse.Namespace,
    event_logger: EventLogger,
    status_board: StatusBoard,
    display: ProgressDisplay,
) -> dict[str, Any]:
    tid = task_id(feature_group, model_name)
    directory = task_dir(args.output_dir, feature_group, model_name)
    status_path = directory / "task_status.json"
    if args.force and directory.exists():
        shutil.rmtree(directory)
    if not args.force and (args.skip_existing or args.resume or args.only_missing) and completed_outputs_exist(directory):
        display.update(f"{tid} skipped completed", advance=1)
        return {"task_id": tid, "feature_group": feature_group, "model_name": model_name, "status": "skipped"}
    if args.only_missing and (directory / "metrics.json").exists():
        display.update(f"{tid} skipped existing metrics", advance=1)
        return {"task_id": tid, "feature_group": feature_group, "model_name": model_name, "status": "skipped"}

    directory.mkdir(parents=True, exist_ok=True)
    status = initial_status(tid, feature_group, model_name)
    started = time.perf_counter()
    status["status"] = "running"
    status["started_at"] = utc_now_iso()
    update_status(status_path, status, "init", "running", started)
    task_config = vars(args).copy()
    task_config.update({"task_id": tid, "feature_group": feature_group, "model_name": model_name})
    atomic_write_json(directory / "task_config.json", {k: str(v) if isinstance(v, Path) else v for k, v in task_config.items()})
    event_logger.emit("task_start", tid, feature_group, model_name, "init", "running")
    status_board.update_current(tid, "init")
    writer = None
    tensorboard_logdir = args.runs_dir / feature_group / model_name
    tensorboard_status = "disabled"
    try:
        dataset_path = args.dataset_dir / DATASET_FILES[feature_group]
        skip_memory, memory_profile, memory_message = should_skip_for_memory(dataset_path, model_name, args)
        status["memory_guard"] = {
            **memory_profile,
            "available_memory_gb": available_memory_gb(),
            "safe_limit_gb": memory_limit_gb(args),
            "enabled": bool(args.memory_guard),
            "message": memory_message,
        }
        status["train_rows"] = int(memory_profile.get("rows", 0))
        status["valid_rows"] = 0
        status["test_rows"] = 0
        status["feature_count"] = int(memory_profile.get("feature_count", 0))
        atomic_write_json(status_path, status)
        event_logger.emit(
            "stage_done",
            tid,
            feature_group,
            model_name,
            "memory_guard",
            "skipped" if skip_memory else "running",
            elapsed(started),
            status.get("train_rows", 0),
            status.get("valid_rows", 0),
            status.get("test_rows", 0),
            status.get("feature_count", 0),
            metrics=status["memory_guard"],
            message=memory_message,
        )
        if skip_memory:
            return mark_task_skipped(directory, args, status, started, memory_message, event_logger, status_board, display)
        for stage in ("load_data", "prepare_xy"):
            display.update(f"{tid} {stage}")
            event_logger.emit("stage_start", tid, feature_group, model_name, stage, "running", elapsed(started))
            update_status(status_path, status, stage, "running", started)
            status_board.update_current(tid, stage)
            if stage == "load_data":
                df, feature_cols = load_dataset(dataset_path, args, args.seed)
            else:
                xy = make_xy(df, feature_cols, args)
                del df
                status.update(
                    {
                        "train_rows": int(len(xy["y_train"])),
                        "valid_rows": int(len(xy["y_valid"])),
                        "test_rows": int(len(xy["y_test"])),
                        "feature_count": int(len(feature_cols)),
                    }
                )
            event_logger.emit(
                "stage_done",
                tid,
                feature_group,
                model_name,
                stage,
                "running",
                elapsed(started),
                status.get("train_rows", 0),
                status.get("valid_rows", 0),
                status.get("test_rows", 0),
                status.get("feature_count", 0),
            )
        writer, tensorboard_status = get_summary_writer(args.tensorboard, model_name, tensorboard_logdir)
        status["tensorboard_status"] = tensorboard_status
        atomic_write_json(status_path, status)
        display.update(f"{tid} train")
        update_status(status_path, status, "train", "running", started)
        event_logger.emit("stage_start", tid, feature_group, model_name, "train", "running", elapsed(started))
        scaler = None
        eval_history = None
        gain_importance = None
        split_importance = None
        if model_name.startswith("dummy_"):
            model, y_valid_pred, y_test_pred, train_seconds, inference_seconds, eval_history, extra = train_dummy(model_name, xy, args.seed)
        elif model_name == "decision_tree":
            model, y_valid_pred, y_test_pred, train_seconds, inference_seconds, eval_history, extra = train_decision_tree(model_name, xy, args.seed)
        elif model_name == "logistic_sgd":
            model, scaler, y_valid_pred, y_test_pred, train_seconds, inference_seconds, eval_history, extra = train_logistic(
                xy, args, writer, event_logger, tid, feature_group, status_board
            )
        elif model_name == "lightgbm":
            model, y_valid_pred, y_test_pred, train_seconds, inference_seconds, eval_history, extra, gain_importance, split_importance = train_lightgbm(
                xy, feature_cols, args, writer, event_logger, tid, feature_group, status_board
            )
        elif model_name == "knn_sample":
            model, scaler, y_valid_pred, y_test_pred, train_seconds, inference_seconds, eval_history, extra = train_knn_sample(
                xy, args, event_logger, tid, feature_group, status_board
            )
        else:
            raise ValueError(f"Unsupported model: {model_name}")
        if writer is not None:
            writer.flush()
            writer.close()
        event_logger.emit("stage_done", tid, feature_group, model_name, "train", "running", elapsed(started), metrics={"train_seconds": train_seconds})
        display.update(f"{tid} evaluate")
        update_status(status_path, status, "evaluate", "running", started)
        metrics, model_path = save_outputs(
            directory,
            model_name,
            model,
            scaler,
            xy,
            feature_cols,
            y_valid_pred,
            y_test_pred,
            train_seconds,
            inference_seconds,
            elapsed(started),
            extra,
            eval_history,
            tensorboard_status,
            tensorboard_logdir,
            gain_importance,
            split_importance,
        )
        status.update(
            {
                "status": "completed",
                "stage": "completed",
                "finished_at": utc_now_iso(),
                "elapsed_seconds": elapsed(started),
                "metrics_path": str(directory / "metrics.json"),
                "model_path": model_path,
                "tensorboard_status": tensorboard_status,
                "train_rows": metrics["train_rows"],
                "valid_rows": metrics["valid_rows"],
                "test_rows": metrics["test_rows"],
                "feature_count": metrics["feature_count"],
            }
        )
        atomic_write_json(status_path, status)
        row = {
            "task_id": tid,
            "feature_group": feature_group,
            "model_name": model_name,
            "status": "completed",
            "accuracy": metrics.get("accuracy", ""),
            "macro_precision": metrics.get("macro_precision", ""),
            "macro_recall": metrics.get("macro_recall", ""),
            "macro_f1": metrics.get("macro_f1", ""),
            "weighted_precision": metrics.get("weighted_precision", ""),
            "weighted_recall": metrics.get("weighted_recall", ""),
            "weighted_f1": metrics.get("weighted_f1", ""),
            "train_seconds": metrics.get("train_seconds", ""),
            "inference_seconds": metrics.get("inference_seconds", ""),
            "train_rows": metrics.get("train_rows", ""),
            "valid_rows": metrics.get("valid_rows", ""),
            "test_rows": metrics.get("test_rows", ""),
            "feature_count": metrics.get("feature_count", ""),
            "target_class_count": metrics.get("target_class_count", ""),
            "model_path": model_path,
            "metrics_path": str(directory / "metrics.json"),
            "tensorboard_logdir": metrics.get("tensorboard_logdir", ""),
            "tensorboard_status": metrics.get("tensorboard_status", ""),
            "completed_at": status["finished_at"],
        }
        append_csv_row(args.output_dir / "metrics_live.csv", METRICS_LIVE_FIELDS, row)
        event_logger.emit("metric_update", tid, feature_group, model_name, "evaluate", "completed", elapsed(started), metrics=metrics)
        event_logger.emit("task_done", tid, feature_group, model_name, "completed", "completed", elapsed(started), metrics=metrics)
        status_board.mark_completed(row)
        display.update(f"{tid} done macro_f1={metrics['macro_f1']:.4f}", advance=1)
        del model, scaler, xy, y_valid_pred, y_test_pred
        gc.collect()
        return row
    except Exception as exc:
        if writer is not None:
            writer.close()
        error = f"{type(exc).__name__}: {exc}"
        status.update(
            {
                "status": "failed",
                "stage": "failed",
                "failed_stage": status.get("stage", ""),
                "error_message": error,
                "finished_at": utc_now_iso(),
                "elapsed_seconds": elapsed(started),
            }
        )
        atomic_write_json(status_path, status)
        atomic_write_text(directory / "error_traceback.txt", traceback.format_exc())
        row = {
            "task_id": tid,
            "feature_group": feature_group,
            "model_name": model_name,
            "status": "failed",
            "train_rows": status.get("train_rows", 0),
            "valid_rows": status.get("valid_rows", 0),
            "test_rows": status.get("test_rows", 0),
            "feature_count": status.get("feature_count", 0),
            "metrics_path": "",
            "model_path": "",
            "tensorboard_logdir": "",
            "completed_at": status["finished_at"],
            "error_message": error,
        }
        append_csv_row(args.output_dir / "metrics_live.csv", METRICS_LIVE_FIELDS, row)
        event_logger.emit("task_failed", tid, feature_group, model_name, "failed", "failed", elapsed(started), message=error)
        status_board.mark_failed(row)
        display.update(f"{tid} failed", advance=1)
        gc.collect()
        if args.fail_fast:
            raise
        return row


def collect_task_rows(output_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for metrics_path in sorted(output_dir.glob("*/*/metrics.json")):
        status_path = metrics_path.with_name("task_status.json")
        status = read_json(status_path, {})
        metrics = read_json(metrics_path, {})
        if not metrics:
            continue
        rows.append(
            {
                "feature_group": status.get("feature_group", metrics_path.parents[1].name),
                "model_name": status.get("model_name", metrics_path.parent.name),
                "status": status.get("status", "completed"),
                **metrics,
                "metrics_path": str(metrics_path),
                "model_path": metrics.get("model_path", status.get("model_path", "")),
            }
        )
    for status_path in sorted(output_dir.glob("*/*/task_status.json")):
        status = read_json(status_path, {})
        if status.get("status") in {"failed", "skipped"}:
            rows.append(
                {
                    "feature_group": status.get("feature_group", status_path.parents[1].name),
                    "model_name": status.get("model_name", status_path.parent.name),
                    "status": status.get("status"),
                    "metrics_path": "",
                    "model_path": "",
                }
            )
    return rows


def write_summary(output_dir: Path) -> None:
    rows = collect_task_rows(output_dir)
    fields = [
        "feature_group",
        "model_name",
        "status",
        "accuracy",
        "macro_precision",
        "macro_recall",
        "macro_f1",
        "weighted_precision",
        "weighted_recall",
        "weighted_f1",
        "train_seconds",
        "inference_seconds",
        "train_rows",
        "valid_rows",
        "test_rows",
        "feature_count",
        "target_class_count",
        "sampled",
        "tensorboard_status",
        "tensorboard_logdir",
        "metrics_path",
        "model_path",
    ]
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "figures").mkdir(parents=True, exist_ok=True)
    with (output_dir / "classifier_summary.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})
    atomic_write_json(output_dir / "classifier_summary.json", rows)
    completed = [row for row in rows if row.get("status") == "completed"]
    lines = ["# HCG Classifier Summary", ""]
    if completed:
        best_macro = max(completed, key=lambda row: float(row.get("macro_f1", -1)))
        best_weighted = max(completed, key=lambda row: float(row.get("weighted_f1", -1)))
        lines.append(f"- Macro-F1 best: `{best_macro['feature_group']}/{best_macro['model_name']}` = `{float(best_macro['macro_f1']):.6f}`")
        lines.append(f"- Weighted-F1 best: `{best_weighted['feature_group']}/{best_weighted['model_name']}` = `{float(best_weighted['weighted_f1']):.6f}`")
        by_model = {(row["feature_group"], row["model_name"]): row for row in completed}
        for model in sorted({row["model_name"] for row in completed}):
            a = by_model.get(("A", model))
            b = by_model.get(("B", model))
            c = by_model.get(("C", model))
            if a and c:
                lines.append(f"- `{model}` C vs A Macro-F1 gain: `{float(c['macro_f1']) - float(a['macro_f1']):.6f}`")
            if b and c:
                lines.append(f"- `{model}` C vs B Macro-F1 gain: `{float(c['macro_f1']) - float(b['macro_f1']):.6f}`")
        dummy_best = max((row for row in completed if row["model_name"].startswith("dummy_")), key=lambda row: float(row.get("macro_f1", -1)), default=None)
        b_best = max((row for row in completed if row["feature_group"] == "B"), key=lambda row: float(row.get("macro_f1", -1)), default=None)
        if dummy_best and b_best:
            lines.append(f"- B best vs Dummy best Macro-F1 gain: `{float(b_best['macro_f1']) - float(dummy_best['macro_f1']):.6f}`")
        for fg in ("A", "B", "C"):
            lgb = by_model.get((fg, "lightgbm"))
            tree = by_model.get((fg, "decision_tree"))
            if lgb and tree:
                lines.append(f"- `{fg}` LightGBM vs Decision Tree Macro-F1 gain: `{float(lgb['macro_f1']) - float(tree['macro_f1']):.6f}`")
        lines.append("- HCG embedding standalone ability: compare all `B/*` rows against dummy baselines in the table.")
        lines.append("- Raw + HCG fusion gain: compare `C - A` and `C - B` gains above.")
        lines.append("- Effect/time tradeoff: use `macro_f1_vs_train_time.png` and train_seconds columns.")
    else:
        lines.append("No completed classifier task found.")
    lines.extend(["", "## Results", "", "| Feature | Model | Status | Macro-F1 | Weighted-F1 | Accuracy | Train seconds |", "| --- | --- | --- | ---: | ---: | ---: | ---: |"])
    for row in sorted(rows, key=lambda r: (str(r.get("feature_group", "")), str(r.get("model_name", "")))):
        lines.append(
            f"| `{row.get('feature_group', '')}` | `{row.get('model_name', '')}` | `{row.get('status', '')}` | "
            f"`{row.get('macro_f1', '')}` | `{row.get('weighted_f1', '')}` | `{row.get('accuracy', '')}` | `{row.get('train_seconds', '')}` |"
        )
    atomic_write_text(output_dir / "classifier_summary.md", "\n".join(lines) + "\n")


def maybe_render_figures(args: argparse.Namespace) -> None:
    if not args.render_figures:
        return
    script = ROOT / "scripts/render_hcg_classification_figures.py"
    if not script.exists():
        return
    subprocess.run([sys.executable, str(script), "--results-dir", str(args.output_dir)], check=False)


def worker_command(feature_group: str, model_name: str) -> list[str]:
    args = [
        value
        for value in sys.argv[1:]
        if value not in {"--worker-feature-group", "--worker-model"}
    ]
    cleaned: list[str] = []
    skip_next = False
    for value in args:
        if skip_next:
            skip_next = False
            continue
        if value in {"--worker-feature-group", "--worker-model"}:
            skip_next = True
            continue
        cleaned.append(value)
    return [
        sys.executable,
        str(Path(__file__).resolve()),
        *cleaned,
        "--worker-feature-group",
        feature_group,
        "--worker-model",
        model_name,
        "--no-isolate-tasks",
        "--no-progress",
    ]


def mark_isolated_failure(feature_group: str, model_name: str, args: argparse.Namespace, returncode: int) -> dict[str, Any]:
    tid = task_id(feature_group, model_name)
    directory = task_dir(args.output_dir, feature_group, model_name)
    status_path = directory / "task_status.json"
    status = read_json(status_path, initial_status(tid, feature_group, model_name))
    if status.get("status") in {"completed", "failed", "skipped"}:
        return {
            "task_id": tid,
            "feature_group": feature_group,
            "model_name": model_name,
            "status": status.get("status"),
        }
    error = f"isolated worker exited with code {returncode}; task may have been killed by OOM or signal"
    status.update(
        {
            "status": "failed",
            "stage": "failed",
            "failed_stage": status.get("stage", ""),
            "error_message": error,
            "finished_at": utc_now_iso(),
        }
    )
    atomic_write_json(status_path, status)
    row = {
        "task_id": tid,
        "feature_group": feature_group,
        "model_name": model_name,
        "status": "failed",
        "train_rows": status.get("train_rows", 0),
        "valid_rows": status.get("valid_rows", 0),
        "test_rows": status.get("test_rows", 0),
        "feature_count": status.get("feature_count", 0),
        "metrics_path": "",
        "model_path": "",
        "tensorboard_logdir": "",
        "completed_at": status["finished_at"],
        "error_message": error,
    }
    append_csv_row(args.output_dir / "metrics_live.csv", METRICS_LIVE_FIELDS, row)
    EventLogger(args.output_dir).emit("task_failed", tid, feature_group, model_name, "failed", "failed", message=error)
    return row


def run_task_isolated(feature_group: str, model_name: str, args: argparse.Namespace, display: ProgressDisplay) -> dict[str, Any]:
    tid = task_id(feature_group, model_name)
    display.update(f"{tid} worker start")
    result = subprocess.run(worker_command(feature_group, model_name), cwd=str(ROOT), check=False)
    if result.returncode != 0:
        row = mark_isolated_failure(feature_group, model_name, args, result.returncode)
        display.update(f"{tid} failed worker={result.returncode}", advance=1)
        if args.fail_fast:
            raise RuntimeError(f"{tid} isolated worker failed with code {result.returncode}")
        return row
    status = read_json(task_dir(args.output_dir, feature_group, model_name) / "task_status.json", {})
    display.update(f"{tid} {status.get('status', 'done')}", advance=1)
    return {
        "task_id": tid,
        "feature_group": feature_group,
        "model_name": model_name,
        "status": status.get("status", "completed"),
    }


def main() -> int:
    args = parse_args()
    for name in ("dataset_dir", "output_dir", "runs_dir"):
        setattr(args, name, resolve_path(getattr(args, name)))
    feature_groups = parse_csv_list(args.feature_groups)
    models = expand_models(args.models)
    bad_groups = [group for group in feature_groups if group not in DATASET_FILES]
    if bad_groups:
        raise ValueError(f"Unknown feature groups: {', '.join(bad_groups)}")
    require_dependencies(models)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    worker_mode = bool(args.worker_feature_group or args.worker_model)
    if worker_mode:
        if args.worker_feature_group not in DATASET_FILES or args.worker_model not in models:
            raise ValueError("--worker-feature-group/--worker-model must match requested feature groups and models")
        feature_groups = [args.worker_feature_group]
        models = [args.worker_model]
        args.isolate_tasks = False
    planned = [task_id(group, model) for group in feature_groups for model in models]
    event_logger = EventLogger(args.output_dir)
    board = StatusBoard(args.output_dir, len(planned), utc_now_iso(), planned)
    display = ProgressDisplay(args.progress, len(planned))
    event_logger.emit("experiment_start", total_steps=len(planned), message="HCG classification training started")
    try:
        for group in feature_groups:
            for model in models:
                if args.isolate_tasks:
                    run_task_isolated(group, model, args, display)
                else:
                    run_task(group, model, args, event_logger, board, display)
        if not worker_mode:
            write_summary(args.output_dir)
            maybe_render_figures(args)
            event_logger.emit("experiment_done", total_steps=len(planned), message="HCG classification training finished")
        return 0
    finally:
        display.close()


if __name__ == "__main__":
    raise SystemExit(main())
