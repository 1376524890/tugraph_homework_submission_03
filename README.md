# TuGraph Homework Submission 03

本仓库围绕 Unicauca 87 属性网络流数据集，提供两种 TuGraph 建模、中间 CSV 生成和 Bolt 导入脚本：

- HCG：`{IP, port}` 端点为点，通信为边。
- TCG：网络流为点，流间因果关系为边。

快速检查数据：

```bash
PYTHONPATH=src python3 scripts/inspect_dataset.py
```

TuGraph 连接信息写在本地 `.env` 中，该文件已加入 `.gitignore`：

```bash
cp .env.example .env
```

小批量建库验证：

```bash
PYTHONPATH=src python3 scripts/prepare_processed_csv.py --graph all --max-rows 10000
PYTHONPATH=src python3 scripts/create_hcg_db.py
PYTHONPATH=src python3 scripts/create_tcg_db.py
```

全量流程：

```bash
PYTHONPATH=src python3 scripts/prepare_processed_csv.py --graph all
du -sh data/raw data/processed data/processed/hcg data/processed/tcg
PYTHONPATH=src python3 scripts/create_hcg_db.py
PYTHONPATH=src python3 scripts/create_tcg_db.py
```

`prepare_processed_csv.py` 只读原始 CSV 并写入 `data/processed/`，不会连接 TuGraph。`create_hcg_db.py` 和 `create_tcg_db.py` 默认只从中间 CSV 入库；如需旧的直读原始 CSV 行为，显式传 `--direct-csv data/raw/Dataset-Unicauca-Version2-87Atts.csv`。

全量导入前建议确认 TuGraph 子图容量和 Docker 磁盘空间。当前数据集 3577296 行；按默认 TCG 参数估算，中间 CSV 约 1.6 GB，原始数据加中间文件约 3.4 GB。TuGraph 数据、索引、日志还会额外占用空间，建议给 Docker 中的数据库预留至少 8-12 GB；更稳妥的做法是把 TuGraph 数据目录映射到宿主机的大容量目录，避免容器层空间爆满。TCG 的边数量受 `--window-seconds` 和 `--max-predecessors` 控制。
