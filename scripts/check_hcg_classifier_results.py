#!/usr/bin/env python3
"""Check completeness of HCG classifier result directories."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from tugraph_homework.common import ROOT


REQUIRED_METRICS = {"accuracy", "macro_precision", "macro_recall", "macro_f1", "weighted_f1"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check HCG classifier result completeness.")
    parser.add_argument("--results-dir", type=Path, default=ROOT / "data/features/hcg/classification/results")
    parser.add_argument("--expected-feature-groups", default="A,B,C")
    parser.add_argument("--expected-models", default="dummy_most_frequent,dummy_stratified,logistic_sgd,decision_tree,lightgbm,knn_sample")
    parser.add_argument("--allow-failed", action="store_true")
    parser.add_argument("--tensorboard", action="store_true", help="Also require TensorBoard log dirs for logistic_sgd and lightgbm.")
    parser.add_argument("--runs-dir", type=Path, default=ROOT / "runs/hcg_classification")
    parser.add_argument("--report", type=Path, default=ROOT / "data/features/hcg/classification/results/check_report.md")
    parser.add_argument("--json-report", type=Path, default=ROOT / "data/features/hcg/classification/results/check_report.json")
    return parser.parse_args()


def resolve_path(path: Path) -> Path:
    return path if path.is_absolute() else ROOT / path


def parse_csv_list(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def add_check(checks: list[dict[str, Any]], name: str, ok: bool, message: str = "", critical: bool = True) -> None:
    checks.append({"name": name, "ok": bool(ok), "message": message, "critical": critical})


def check_task(results_dir: Path, runs_dir: Path, fg: str, model: str, tensorboard: bool, checks: list[dict[str, Any]]) -> None:
    directory = results_dir / fg / model
    status_path = directory / "task_status.json"
    add_check(checks, f"{fg}/{model}/task_status", status_path.exists(), str(status_path))
    status = read_json(status_path)
    if not status_path.exists():
        return
    state = status.get("status")
    if state == "failed":
        add_check(checks, f"{fg}/{model}/failed_recorded", True, status.get("error_message", ""), critical=False)
        return
    if state == "skipped":
        add_check(checks, f"{fg}/{model}/skipped_recorded", True, status.get("error_message", ""), critical=False)
        return
    if state != "completed":
        add_check(checks, f"{fg}/{model}/completed_status", False, f"status={state}")
        return
    for name in ["metrics.json", "classification_report.csv", "confusion_matrix.csv", "feature_columns.json", "label_mapping.json"]:
        add_check(checks, f"{fg}/{model}/{name}", (directory / name).exists(), str(directory / name))
    metrics = read_json(directory / "metrics.json")
    add_check(checks, f"{fg}/{model}/metrics_keys", REQUIRED_METRICS.issubset(metrics), f"missing={sorted(REQUIRED_METRICS - set(metrics))}")
    if model in {"logistic_sgd", "knn_sample"}:
        add_check(checks, f"{fg}/{model}/scaler", (directory / "scaler.pkl").exists(), str(directory / "scaler.pkl"))
    if model == "lightgbm":
        add_check(checks, f"{fg}/{model}/lightgbm_model", (directory / "lightgbm_model.txt").exists(), str(directory / "lightgbm_model.txt"))
        add_check(checks, f"{fg}/{model}/feature_importance_gain", (directory / "feature_importance_gain.csv").exists(), str(directory / "feature_importance_gain.csv"))
    if tensorboard and model in {"logistic_sgd", "lightgbm"}:
        logdir = runs_dir / fg / model
        add_check(checks, f"{fg}/{model}/tensorboard_logdir", logdir.exists() and any(logdir.iterdir()), str(logdir))


def write_reports(report: Path, json_report: Path, checks: list[dict[str, Any]]) -> None:
    failed = [row for row in checks if not row["ok"]]
    critical_failed = [row for row in failed if row.get("critical", True)]
    result = {
        "overall_status": "PASS" if not critical_failed else "FAIL",
        "check_count": len(checks),
        "failed_count": len(failed),
        "critical_failed_count": len(critical_failed),
        "checks": checks,
    }
    json_report.parent.mkdir(parents=True, exist_ok=True)
    json_report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# HCG Classifier Result Check",
        "",
        f"Overall status: **{result['overall_status']}**",
        "",
        "| Check | Result | Message |",
        "| --- | --- | --- |",
    ]
    for row in checks:
        msg = str(row.get("message", "")).replace("|", "\\|")
        lines.append(f"| `{row['name']}` | {'PASS' if row['ok'] else 'FAIL'} | {msg} |")
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    for name in ("results_dir", "runs_dir", "report", "json_report"):
        setattr(args, name, resolve_path(getattr(args, name)))
    checks: list[dict[str, Any]] = []
    for name in ["classifier_summary.csv", "classifier_summary.json", "classifier_summary.md", "progress.jsonl", "running_status.md", "metrics_live.csv"]:
        add_check(checks, name, (args.results_dir / name).exists(), str(args.results_dir / name))
    fig_dir = args.results_dir / "figures"
    add_check(checks, "figures_dir", fig_dir.exists(), str(fig_dir))
    for fg in parse_csv_list(args.expected_feature_groups):
        for model in parse_csv_list(args.expected_models):
            check_task(args.results_dir, args.runs_dir, fg, model, args.tensorboard, checks)
    write_reports(args.report, args.json_report, checks)
    critical_failed = [row for row in checks if not row["ok"] and row.get("critical", True)]
    if critical_failed and not args.allow_failed:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
