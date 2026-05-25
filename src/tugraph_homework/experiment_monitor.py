from __future__ import annotations

import csv
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def atomic_write_text(path: Path, text: str, encoding: str = "utf-8") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp")
    tmp.write_text(text, encoding=encoding)
    os.replace(tmp, path)


def atomic_write_json(path: Path, payload: dict[str, Any] | list[Any]) -> None:
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
        fh.flush()
        os.fsync(fh.fileno())


def append_csv_row(path: Path, fieldnames: list[str], row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.exists() and path.stat().st_size > 0
    with path.open("a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        if not exists:
            writer.writeheader()
        writer.writerow({field: row.get(field, "") for field in fieldnames})
        fh.flush()
        os.fsync(fh.fileno())


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def system_stats() -> dict[str, Any]:
    try:
        import psutil  # type: ignore
    except ImportError:
        return {}
    process = psutil.Process(os.getpid())
    return {
        "memory_gb": process.memory_info().rss / (1024**3),
        "system_memory_percent": psutil.virtual_memory().percent,
        "cpu_percent": psutil.cpu_percent(interval=None),
    }


class StatusBoard:
    def __init__(self, output_dir: Path, total_tasks: int, experiment_started_at: str, planned_tasks: list[str]) -> None:
        self.output_dir = output_dir
        self.total_tasks = total_tasks
        self.experiment_started_at = experiment_started_at
        self.planned_tasks = planned_tasks
        self.completed: list[dict[str, Any]] = []
        self.failed: list[dict[str, Any]] = []
        self.current: dict[str, Any] | None = None
        self.last_metrics: dict[str, Any] = {}

    @property
    def path(self) -> Path:
        return self.output_dir / "running_status.md"

    def update_current(self, task_id: str | None, stage: str = "", metrics: dict[str, Any] | None = None) -> None:
        self.current = {"task_id": task_id or "", "stage": stage, "updated_at": utc_now_iso()}
        if metrics:
            self.last_metrics.update(metrics)
        self.write()

    def mark_completed(self, row: dict[str, Any]) -> None:
        self.completed.append(row)
        self.current = None
        self.write()

    def mark_failed(self, row: dict[str, Any]) -> None:
        self.failed.append(row)
        self.current = None
        self.write()

    def pending_tasks(self) -> list[str]:
        done = {str(row.get("task_id", "")) for row in self.completed + self.failed}
        current = str(self.current.get("task_id", "")) if self.current else ""
        return [task for task in self.planned_tasks if task not in done and task != current][:20]

    def write(self) -> None:
        lines = [
            "# HCG Classification Running Status",
            "",
            f"- Experiment started: `{self.experiment_started_at}`",
            f"- Total tasks: `{self.total_tasks}`",
            f"- Completed tasks: `{len(self.completed)}`",
            f"- Failed tasks: `{len(self.failed)}`",
            f"- Current task: `{(self.current or {}).get('task_id', '')}`",
            f"- Current stage: `{(self.current or {}).get('stage', '')}`",
            f"- Last valid macro_f1: `{self.last_metrics.get('valid_macro_f1', '')}`",
            f"- Last valid weighted_f1: `{self.last_metrics.get('valid_weighted_f1', '')}`",
            "",
            "## Completed Tasks",
            "",
            "| Task | Model | Macro-F1 | Weighted-F1 | Accuracy |",
            "| --- | --- | ---: | ---: | ---: |",
        ]
        for row in self.completed[-50:]:
            lines.append(
                f"| `{row.get('task_id', '')}` | `{row.get('model_name', '')}` | "
                f"`{row.get('macro_f1', '')}` | `{row.get('weighted_f1', '')}` | `{row.get('accuracy', '')}` |"
            )
        lines.extend(["", "## Failed Tasks", "", "| Task | Stage | Error |", "| --- | --- | --- |"])
        for row in self.failed[-50:]:
            error = str(row.get("error_message", "")).replace("|", "\\|")[:240]
            lines.append(f"| `{row.get('task_id', '')}` | `{row.get('stage', '')}` | {error} |")
        lines.extend(["", "## Next Pending Tasks", ""])
        for task in self.pending_tasks():
            lines.append(f"- `{task}`")
        atomic_write_text(self.path, "\n".join(lines) + "\n")


class EventLogger:
    def __init__(self, output_dir: Path) -> None:
        self.output_dir = output_dir
        self.progress_path = output_dir / "progress.jsonl"

    def emit(
        self,
        event: str,
        task_id: str = "",
        feature_group: str = "",
        model_name: str = "",
        stage: str = "",
        status: str = "",
        elapsed_seconds: float = 0.0,
        train_rows: int = 0,
        valid_rows: int = 0,
        test_rows: int = 0,
        feature_count: int = 0,
        current_step: int = 0,
        total_steps: int = 0,
        metrics: dict[str, Any] | None = None,
        message: str = "",
    ) -> None:
        payload = {
            "timestamp": utc_now_iso(),
            "event": event,
            "task_id": task_id,
            "feature_group": feature_group,
            "model_name": model_name,
            "stage": stage,
            "status": status,
            "elapsed_seconds": elapsed_seconds,
            "train_rows": train_rows,
            "valid_rows": valid_rows,
            "test_rows": test_rows,
            "feature_count": feature_count,
            "current_step": current_step,
            "total_steps": total_steps,
            "metrics": metrics or {},
            "message": message,
        }
        payload.update(system_stats())
        append_jsonl(self.progress_path, payload)


class ProgressDisplay:
    def __init__(self, enabled: bool, total: int) -> None:
        self.enabled = enabled
        self.total = total
        self.completed = 0
        self.rich_progress = None
        self.task = None
        self.tqdm_bar = None
        if not enabled:
            return
        try:
            from rich.progress import BarColumn, Progress, TextColumn, TimeElapsedColumn

            self.rich_progress = Progress(
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TextColumn("{task.completed}/{task.total}"),
                TimeElapsedColumn(),
            )
            self.rich_progress.start()
            self.task = self.rich_progress.add_task("classification tasks", total=total)
            return
        except ImportError:
            pass
        try:
            from tqdm.auto import tqdm

            self.tqdm_bar = tqdm(total=total, desc="classification tasks", unit="task", dynamic_ncols=True)
        except ImportError:
            self.tqdm_bar = None

    def update(self, description: str, advance: int = 0) -> None:
        if advance:
            self.completed += advance
        if not self.enabled:
            return
        if self.rich_progress is not None and self.task is not None:
            self.rich_progress.update(self.task, advance=advance, description=description)
        elif self.tqdm_bar is not None:
            if advance:
                self.tqdm_bar.update(advance)
            self.tqdm_bar.set_description(description)
        else:
            print(f"[{self.completed}/{self.total}] {description}", flush=True)

    def close(self) -> None:
        if self.rich_progress is not None:
            self.rich_progress.stop()
        if self.tqdm_bar is not None:
            self.tqdm_bar.close()


def iter_batches(length: int, batch_size: int) -> Iterable[slice]:
    start = 0
    while start < length:
        end = min(length, start + batch_size)
        yield slice(start, end)
        start = end


def elapsed(started: float) -> float:
    return time.perf_counter() - started
