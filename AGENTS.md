# Repository Guidelines

## Project Structure & Module Organization

This repository builds TuGraph-ready graph data from the Unicauca network-flow dataset. Core Python helpers live in `src/tugraph_homework/`. Operational scripts are in `scripts/`, including CSV preparation, TuGraph import, graph checks, and Node2Vec procedure runners. TuGraph stored procedures live in `procedures/`; archived or unusable procedure versions are under `procedures/archived_node2vec/`. Documentation and experiment notes are maintained in `docs/`, especially `docs/experiment_record.md`.

Large data and runtime artifacts are intentionally separated: `data/raw/` for source CSVs, `data/processed/` for generated HCG/TCG CSVs, `data/features/` for ML features and reports, and `docker/tugraph-*` for mounted TuGraph data, import, logs, and temp files. Avoid committing large generated outputs unless explicitly required.

## Build, Test, and Development Commands

Run scripts from the repository root with `PYTHONPATH=src`.

```bash
PYTHONPATH=src python3 scripts/inspect_dataset.py --sample-rows 200000
```
Checks raw dataset shape and key uniqueness.

```bash
PYTHONPATH=src python3 scripts/prepare_processed_csv.py --csv data/raw/Dataset-Unicauca-Version2-87Atts.csv --graph all --output-root data/processed
```
Generates HCG and TCG intermediate CSV files.

```bash
PYTHONPATH=src python3 scripts/import_tugraph_native.py --graph-type hcg --dry-run
```
Validates TuGraph native import setup before importing.

```bash
python3 -m py_compile scripts/*.py src/tugraph_homework/*.py procedures/*.py
```
Performs a lightweight syntax check.

## Coding Style & Naming Conventions

Use Python 3, 4-space indentation, type hints where useful, and small single-purpose functions. Follow existing script naming: imperative snake_case names such as `prepare_processed_csv.py` or `run_hcg_node2vec_procedure_batch.py`. Keep generated report names descriptive and scoped, for example `data/features/hcg/reports/hcg_node2vec_py_full_check.md`.

## Testing Guidelines

There is no formal test suite yet. Prefer smoke tests with bounded inputs before full runs, for example `--max-rows 2000`, `--dry-run`, `--max-batches 1`, or report-generating check scripts such as `scripts/check_walks_file.py`. Record important experiment commands and results in `docs/experiment_record.md`.

## Commit & Pull Request Guidelines

Recent commits use concise Chinese or English summaries, often starting with an action: `修复node2vec问题`, `更新文档`, or `Add HCG weighted walk procedure and build scripts`. Keep commits focused and mention affected workflow or graph component. Pull requests should include a short purpose, commands run, generated report paths, and warnings about large data or TuGraph/Docker side effects.

## Security & Configuration Tips

Do not commit credentials, JWT files, or private dataset access tokens. Be careful with `docker/tugraph-data/`, `docker/tugraph-import/`, and `docker/tugraph-tmp/`; they may contain very large database or walk files. Prefer documenting reproducible commands over committing heavyweight artifacts.
