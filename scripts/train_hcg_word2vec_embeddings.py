#!/usr/bin/env python3
"""Train HCG Endpoint Word2Vec embeddings from existing Node2Vec walks."""

from __future__ import annotations

import argparse
import csv
import itertools
import json
import logging
import os
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow
import gensim
from gensim.models import Word2Vec
from gensim.models.callbacks import CallbackAny2Vec

from tugraph_homework.common import ROOT, progress_iter


DEFAULT_WALKS = ROOT / "docker/tugraph-tmp/hcg_walks_node2vec_py_full.txt"
DEFAULT_ID_MAP = ROOT / "docker/tugraph-tmp/hcg_node_id_map_node2vec_py_full.csv"
DEFAULT_OUTPUT = ROOT / "data/features/hcg/node2vec/hcg_endpoint_node2vec_d64.parquet"
DEFAULT_MODEL_OUTPUT = ROOT / "data/features/hcg/node2vec/hcg_endpoint_node2vec_d64.model"
DEFAULT_REPORT = ROOT / "data/features/hcg/reports/hcg_word2vec_d64_report.md"
DEFAULT_JSON_REPORT = ROOT / "data/features/hcg/reports/hcg_word2vec_d64_report.json"
FULL_HCG_EXPECTED_TOKENS = 933_050
LOGGER = logging.getLogger("hcg_word2vec")


class EpochLogger(CallbackAny2Vec):
    """Log Word2Vec epoch boundaries."""

    def __init__(self) -> None:
        self.epoch = 0
        self.epoch_start = 0.0

    def on_epoch_begin(self, model: Word2Vec) -> None:
        self.epoch_start = time.perf_counter()
        LOGGER.info("training epoch %d/%d started", self.epoch + 1, model.epochs)

    def on_epoch_end(self, model: Word2Vec) -> None:
        elapsed = time.perf_counter() - self.epoch_start
        LOGGER.info("training epoch %d/%d finished in %.2fs", self.epoch + 1, model.epochs, elapsed)
        self.epoch += 1


class WalkSentenceIterator:
    """Re-iterable sentence stream for gensim."""

    def __init__(self, path: Path, max_lines: int = 0, desc: str = "Read walks", total: int | None = None) -> None:
        self.path = path
        self.max_lines = max_lines
        self.desc = desc
        self.total = total

    def __iter__(self) -> Iterator[list[str]]:
        with self.path.open("r", encoding="utf-8") as fh:
            input_lines = itertools.islice(fh, self.max_lines) if self.max_lines else fh
            for raw_line in progress_iter(input_lines, self.desc, "sentences", self.total):
                parts = raw_line.strip().split()
                if parts:
                    yield parts


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train HCG Word2Vec Endpoint embeddings from Node2Vec walks.")
    parser.add_argument("--walks", type=Path, default=DEFAULT_WALKS)
    parser.add_argument("--id-map", type=Path, default=DEFAULT_ID_MAP)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--model-output", type=Path, default=DEFAULT_MODEL_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--json-report", type=Path, default=DEFAULT_JSON_REPORT)
    parser.add_argument("--log-file", type=Path, default=None, help="Default: report path with .log suffix.")
    parser.add_argument("--vector-size", type=int, default=64)
    parser.add_argument("--window", type=int, default=5)
    parser.add_argument("--min-count", type=int, default=1)
    parser.add_argument("--sg", type=int, default=1)
    parser.add_argument("--negative", type=int, default=5)
    parser.add_argument("--sample", type=float, default=1e-4)
    parser.add_argument("--epochs", type=int, default=5)
    parser.add_argument("--workers", type=int, default=0, help="0 means min(cpu_count, 8).")
    parser.add_argument("--seed", type=int, default=20260525)
    parser.add_argument("--max-lines", type=int, default=0, help="0 means full walks file.")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--compute-nearest-samples", type=int, default=10)
    return parser.parse_args()


def resolve_path(path: Path) -> Path:
    return path if path.is_absolute() else ROOT / path


def setup_logging(log_file: Path) -> None:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    LOGGER.setLevel(logging.INFO)
    LOGGER.handlers.clear()
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

    stream_handler = logging.StreamHandler(sys.stderr)
    stream_handler.setFormatter(formatter)
    LOGGER.addHandler(stream_handler)

    file_handler = logging.FileHandler(log_file, mode="w", encoding="utf-8")
    file_handler.setFormatter(formatter)
    LOGGER.addHandler(file_handler)


def ensure_inputs(args: argparse.Namespace) -> None:
    for name in ("walks", "id_map"):
        path = getattr(args, name)
        if not path.exists():
            raise FileNotFoundError(f"{name.replace('_', '-')} file not found: {path}")
    outputs = [args.output, args.model_output, args.report, args.json_report]
    existing = [path for path in outputs if path and path.exists()]
    if existing and not args.overwrite:
        joined = ", ".join(str(path) for path in existing)
        raise FileExistsError(f"output exists and --overwrite was not set: {joined}")


def read_id_map(path: Path) -> dict[str, int]:
    LOGGER.info("reading id map: %s", path)
    token_to_vid: dict[str, int] = {}
    with path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames != ["vid", "token"]:
            raise ValueError(f"id map header must be vid,token, got: {reader.fieldnames}")
        for row_number, row in enumerate(reader, start=2):
            token = (row.get("token") or "").strip()
            vid_raw = (row.get("vid") or "").strip()
            if not token:
                raise ValueError(f"id map has empty token at line {row_number}")
            if token in token_to_vid:
                raise ValueError(f"id map has duplicate token at line {row_number}: {token}")
            try:
                token_to_vid[token] = int(vid_raw)
            except ValueError as exc:
                raise ValueError(f"id map has invalid vid at line {row_number}: {vid_raw}") from exc
    LOGGER.info("id map loaded: %d tokens", len(token_to_vid))
    return token_to_vid


def summarize_walks(path: Path, max_lines: int) -> dict[str, Any]:
    LOGGER.info("summarizing walks: %s max_lines=%d", path, max_lines)
    line_count = 0
    sentence_count = 0
    empty_lines = 0
    total_len = 0
    min_len: int | None = None
    max_len = 0
    tokens: set[str] = set()

    with path.open("r", encoding="utf-8") as fh:
        input_lines = itertools.islice(fh, max_lines) if max_lines else fh
        iterable = progress_iter(input_lines, "Summarize walks", "lines", max_lines or None)
        for line_number, raw_line in enumerate(iterable, start=1):
            parts = raw_line.strip().split()
            line_count += 1
            if not parts:
                empty_lines += 1
                length = 0
            else:
                sentence_count += 1
                length = len(parts)
                tokens.update(parts)
            total_len += length
            min_len = length if min_len is None else min(min_len, length)
            max_len = max(max_len, length)

    result = {
        "walk_line_count": line_count,
        "sentence_count": sentence_count,
        "empty_line_count": empty_lines,
        "average_walk_length": (total_len / line_count) if line_count else 0.0,
        "min_walk_length": min_len if min_len is not None else 0,
        "max_walk_length": max_len,
        "walk_unique_token_count": len(tokens),
    }
    LOGGER.info(
        "walk summary finished: lines=%d unique_tokens=%d avg_len=%.4f",
        result["walk_line_count"],
        result["walk_unique_token_count"],
        result["average_walk_length"],
    )
    return result


def save_embeddings(model: Word2Vec, token_to_vid: dict[str, int], output: Path) -> dict[str, Any]:
    LOGGER.info("building embedding dataframe")
    tokens = list(model.wv.index_to_key)
    vectors = np.asarray(model.wv.vectors, dtype=np.float32)
    emb_cols = [f"emb_{idx:03d}" for idx in range(vectors.shape[1])]

    vid_values = [token_to_vid.get(token) for token in tokens]
    missing_vid_count = sum(vid is None for vid in vid_values)
    df = pd.DataFrame(vectors, columns=emb_cols)
    df.insert(0, "vid", pd.Series(vid_values, dtype="Int64"))
    df.insert(0, "endpoint_id", tokens)

    output.parent.mkdir(parents=True, exist_ok=True)
    LOGGER.info("writing parquet: %s rows=%d dim=%d", output, len(df), vectors.shape[1])
    df.to_parquet(output, index=False)
    LOGGER.info("parquet write finished")

    nan_count = int(np.isnan(vectors).sum())
    inf_count = int(np.isinf(vectors).sum())
    return {
        "parquet_row_count": int(len(df)),
        "missing_id_map_token_count": int(missing_vid_count),
        "id_map_coverage": (len(tokens) - missing_vid_count) / len(tokens) if tokens else 0.0,
        "nan_count": nan_count,
        "inf_count": inf_count,
        "embedding_columns": emb_cols,
    }


def compute_nearest_samples(model: Word2Vec, sample_count: int) -> list[dict[str, Any]]:
    if sample_count <= 0 or not model.wv.index_to_key:
        return []
    tokens = model.wv.index_to_key[:sample_count]
    samples: list[dict[str, Any]] = []
    for token in tokens:
        nearest = [
            {"endpoint_id": other, "similarity": float(score)}
            for other, score in model.wv.similar_by_word(token, topn=min(5, max(0, len(model.wv) - 1)))
        ]
        samples.append({"endpoint_id": token, "nearest": nearest})
    return samples


def check_results(args: argparse.Namespace, metrics: dict[str, Any]) -> dict[str, bool]:
    full_run = args.max_lines == 0
    checks = {
        "walks_read": metrics["walk_line_count"] > 0,
        "vocab_non_empty": metrics["word2vec_vocab_token_count"] > 0,
        "parquet_rows_equal_vocab": metrics["parquet_row_count"] == metrics["word2vec_vocab_token_count"],
        "no_nan": metrics["nan_count"] == 0,
        "no_inf": metrics["inf_count"] == 0,
        "id_map_no_missing_tokens": metrics["missing_id_map_token_count"] == 0,
    }
    if args.min_count == 1:
        checks["vocab_equals_walk_unique_tokens"] = (
            metrics["word2vec_vocab_token_count"] == metrics["walk_unique_token_count"]
        )
    if full_run and args.min_count == 1:
        checks["full_rows_equal_expected_933050"] = metrics["parquet_row_count"] == FULL_HCG_EXPECTED_TOKENS
    return checks


def write_reports(
    args: argparse.Namespace,
    metrics: dict[str, Any],
    checks: dict[str, bool],
    nearest_samples: list[dict[str, Any]],
) -> None:
    result = {
        "inputs": {"walks": str(args.walks), "id_map": str(args.id_map)},
        "outputs": {
            "parquet": str(args.output),
            "model": str(args.model_output),
            "report": str(args.report),
            "json_report": str(args.json_report),
            "log_file": str(args.log_file),
        },
        "parameters": {
            "vector_size": args.vector_size,
            "window": args.window,
            "min_count": args.min_count,
            "sg": args.sg,
            "negative": args.negative,
            "sample": args.sample,
            "epochs": args.epochs,
            "workers": args.workers,
            "seed": args.seed,
            "max_lines": args.max_lines,
        },
        "dependencies": {
            "gensim": gensim.__version__,
            "numpy": np.__version__,
            "pandas": pd.__version__,
            "pyarrow": pyarrow.__version__,
        },
        "metrics": metrics,
        "checks": checks,
        "overall_status": "PASS" if all(checks.values()) else "FAIL",
        "nearest_samples": nearest_samples,
        "join_design": {
            "level": "Endpoint",
            "join_keys": ["src_endpoint", "dst_endpoint"],
            "flow_embedding": "concat(src_emb, dst_emb, abs(src_emb - dst_emb), src_emb * dst_emb)",
            "flow_embedding_dim_if_d64": 256,
        },
    }

    args.report.parent.mkdir(parents=True, exist_ok=True)
    with args.report.open("w", encoding="utf-8") as fh:
        fh.write("# HCG Word2Vec Endpoint Embedding Report\n\n")
        fh.write(f"Overall status: **{result['overall_status']}**\n\n")
        fh.write("## Inputs and Outputs\n\n")
        fh.write("| Item | Path |\n| --- | --- |\n")
        fh.write(f"| walks | `{args.walks}` |\n")
        fh.write(f"| id map | `{args.id_map}` |\n")
        fh.write(f"| parquet | `{args.output}` |\n")
        fh.write(f"| gensim model | `{args.model_output}` |\n")
        fh.write(f"| log file | `{args.log_file}` |\n\n")

        fh.write("## Training Parameters\n\n")
        fh.write("| Parameter | Value |\n| --- | ---: |\n")
        for key, value in result["parameters"].items():
            fh.write(f"| `{key}` | `{value}` |\n")
        fh.write("\n## Metrics\n\n")
        fh.write("| Metric | Value |\n| --- | ---: |\n")
        for key, value in metrics.items():
            if key == "embedding_columns":
                continue
            if isinstance(value, float):
                fh.write(f"| `{key}` | `{value:.6f}` |\n")
            else:
                fh.write(f"| `{key}` | `{value}` |\n")
        fh.write("\n## Runtime Dependencies\n\n")
        fh.write("| Package | Version |\n| --- | --- |\n")
        fh.write(f"| `gensim` | `{gensim.__version__}` |\n")
        fh.write(f"| `numpy` | `{np.__version__}` |\n")
        fh.write(f"| `pandas` | `{pd.__version__}` |\n")
        fh.write(f"| `pyarrow` | `{pyarrow.__version__}` |\n")
        fh.write("\n## Checks\n\n")
        fh.write("| Check | Result |\n| --- | --- |\n")
        for key, ok in checks.items():
            fh.write(f"| `{key}` | {'PASS' if ok else 'FAIL'} |\n")
        fh.write("\n## Downstream Join Design\n\n")
        fh.write("The parquet file contains Endpoint-level features, not flow-level features. ")
        fh.write("Join `endpoint_id` to flow `src_endpoint` and `dst_endpoint`, then build:\n\n")
        fh.write("```text\n")
        fh.write("src_emb = emb(src_endpoint)\n")
        fh.write("dst_emb = emb(dst_endpoint)\n")
        fh.write("flow_emb = concat(src_emb, dst_emb, abs(src_emb - dst_emb), src_emb * dst_emb)\n")
        fh.write("```\n\n")
        fh.write("For 64-dimensional endpoint embeddings, `flow_emb` has 256 dimensions.\n")
        if nearest_samples:
            fh.write("\n## Nearest Samples\n\n")
            for sample in nearest_samples:
                neighbors = ", ".join(
                    f"{item['endpoint_id']} ({item['similarity']:.4f})" for item in sample["nearest"]
                )
                fh.write(f"- `{sample['endpoint_id']}`: {neighbors}\n")

    if args.json_report:
        args.json_report.parent.mkdir(parents=True, exist_ok=True)
        args.json_report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    args = parse_args()
    for name in ("walks", "id_map", "output", "model_output", "report", "json_report", "log_file"):
        value = getattr(args, name)
        if value is not None:
            setattr(args, name, resolve_path(value))
    if args.log_file is None:
        args.log_file = args.report.with_suffix(".log")
    setup_logging(args.log_file)
    args.workers = args.workers or min(os.cpu_count() or 1, 8)
    if args.vector_size <= 0:
        raise ValueError("--vector-size must be positive")
    if args.max_lines < 0:
        raise ValueError("--max-lines must be >= 0")
    ensure_inputs(args)

    start = time.perf_counter()
    LOGGER.info("HCG Word2Vec training started")
    LOGGER.info("walks=%s size=%d bytes", args.walks, args.walks.stat().st_size)
    LOGGER.info("id_map=%s size=%d bytes", args.id_map, args.id_map.stat().st_size)
    LOGGER.info(
        "parameters: vector_size=%d window=%d min_count=%d sg=%d negative=%d sample=%s epochs=%d workers=%d seed=%d max_lines=%d",
        args.vector_size,
        args.window,
        args.min_count,
        args.sg,
        args.negative,
        args.sample,
        args.epochs,
        args.workers,
        args.seed,
        args.max_lines,
    )
    token_to_vid = read_id_map(args.id_map)
    walk_metrics = summarize_walks(args.walks, args.max_lines)

    LOGGER.info("initializing Word2Vec model")
    model = Word2Vec(
        vector_size=args.vector_size,
        window=args.window,
        min_count=args.min_count,
        sg=args.sg,
        negative=args.negative,
        sample=args.sample,
        workers=args.workers,
        seed=args.seed,
        epochs=args.epochs,
    )
    LOGGER.info("building Word2Vec vocabulary")
    vocab_sentences = WalkSentenceIterator(
        args.walks,
        args.max_lines,
        desc="Build vocab",
        total=walk_metrics["walk_line_count"],
    )
    train_sentences = WalkSentenceIterator(
        args.walks,
        args.max_lines,
        desc="Train Word2Vec",
        total=walk_metrics["walk_line_count"],
    )
    sentences = train_sentences
    model.build_vocab(vocab_sentences)
    if len(model.wv) == 0:
        raise ValueError("Word2Vec vocab is empty")
    LOGGER.info("vocabulary built: vocab=%d corpus_count=%d corpus_total_words=%d", len(model.wv), model.corpus_count, model.corpus_total_words)
    LOGGER.info("training Word2Vec")
    model.train(sentences, total_examples=model.corpus_count, epochs=args.epochs, callbacks=[EpochLogger()])

    args.model_output.parent.mkdir(parents=True, exist_ok=True)
    LOGGER.info("saving gensim model: %s", args.model_output)
    model.save(str(args.model_output))
    LOGGER.info("gensim model saved")
    output_metrics = save_embeddings(model, token_to_vid, args.output)
    LOGGER.info("computing nearest samples: %d", args.compute_nearest_samples)
    nearest_samples = compute_nearest_samples(model, args.compute_nearest_samples)

    elapsed_seconds = time.perf_counter() - start
    metrics: dict[str, Any] = {
        **walk_metrics,
        "id_map_token_count": len(token_to_vid),
        "word2vec_vocab_token_count": len(model.wv),
        **output_metrics,
        "vector_size": args.vector_size,
        "training_elapsed_seconds": elapsed_seconds,
        "training_elapsed_minutes": elapsed_seconds / 60.0,
        "seed": args.seed,
    }
    metrics["id_map_coverage_percent"] = metrics["id_map_coverage"] * 100.0

    checks = check_results(args, metrics)
    write_reports(args, metrics, checks, nearest_samples)
    LOGGER.info("reports written: %s %s", args.report, args.json_report)
    LOGGER.info("HCG Word2Vec training finished: status=%s elapsed=%.2fs", "PASS" if all(checks.values()) else "FAIL", elapsed_seconds)
    print(json.dumps({"metrics": metrics, "checks": checks}, ensure_ascii=False, indent=2, default=str))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
