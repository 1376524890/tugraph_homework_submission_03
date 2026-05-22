# TuGraph Homework Submission 03

本仓库围绕 Unicauca 87 属性网络流数据集，提供两种 TuGraph 建模和 Bolt 导入脚本：

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
PYTHONPATH=src python3 scripts/create_hcg_db.py --max-rows 10000
PYTHONPATH=src python3 scripts/create_tcg_db.py --max-rows 10000
```

全量导入前建议确认 TuGraph 子图容量和磁盘空间。数据集 3577296 行，TCG 的边数量受 `--window-seconds` 和 `--max-predecessors` 控制。
