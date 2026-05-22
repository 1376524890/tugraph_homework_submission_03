# TuGraph Homework Submission 03

本仓库围绕 Unicauca 87 属性网络流数据集，提供 HCG 和 TCG 的本地构建脚本、TuGraph schema/导入脚本和建模说明。

- HCG：`{IP, port}` 端点为点，端点间存在 flow 通信则聚合为一条有向 `COMMUNICATES` 边。
- TCG：每条 flow 为点，flow 间满足 CR、PR、DHR、SHR 因果关系则建立有向 `CAUSES` 边。

## 重要变化

旧版 TCG 使用 `shared_endpoint_time_window`，并在构图阶段使用 `--window-seconds` 和 `--max-predecessors` 控制边数。新版论文对齐版 TCG 不再把时间窗口或前驱截断写入构图规则：`delta_seconds` 只作为边属性保存，后续查询、采样、实验或嵌入训练阶段再过滤。

`flow_id` 在该数据集中会重复，不能作为 Flow 节点主键。新版 Flow 节点主键为 `record_id`；原始数据缺少 `record_id` 时按原始行号生成稳定 ID，例如 `rec_0000000001`。

## 数据检查

```bash
PYTHONPATH=src python3 scripts/inspect_dataset.py
```

## HCG 构建

HCG 是基于 flow 记录的通信近似图，即 flow-level HCG approximation。当前原始数据是流级统计数据；如果缺少 TCP flags 或 SYN 字段，脚本不会伪造 SYN 判断，也无法严格按 TCP SYN 触发建边。

```bash
PYTHONPATH=src python3 scripts/build_hcg.py \
  --input data/raw/Dataset-Unicauca-Version2-87Atts.csv \
  --output data/rebuild/hcg
```

旧入口 `scripts/prepare_processed_csv.py --graph hcg` 仍可生成 HCG CSV，但建议新结果写入 `data/rebuild/hcg`，以保留 `data/processed/` 下的旧版结果。

## TCG 构建

TCG 使用四类关系，优先级为 `CR > PR > DHR > SHR`：

- `CR`：五元组方向相反，近似请求/响应。
- `PR`：`dstIp(f1) == srcIp(f2)`，近似传播、代理、转发或链式访问。
- `DHR`：同一源 IP 使用不同源端口。
- `SHR`：同一源 IP 使用相同源端口。

构图阶段不使用时间窗口，不使用 `max_predecessors`，不生成自环。`relation_id` 使用 `src_record_id`、`dst_record_id` 和 `relation_type` 的稳定 hash 生成。

先估算边数：

```bash
PYTHONPATH=src python3 scripts/build_tcg.py \
  --input data/raw/Dataset-Unicauca-Version2-87Atts.csv \
  --mode estimate \
  --output data/rebuild/tcg
```

只生成 CR 关系做小规模检查：

```bash
PYTHONPATH=src python3 scripts/build_tcg.py \
  --input data/raw/Dataset-Unicauca-Version2-87Atts.csv \
  --mode build \
  --relation-types CR \
  --output data/rebuild/tcg \
  --output-format parquet \
  --partition-by relation_type
```

全量分区生成命令如下。不要在估算前直接运行：

```bash
PYTHONPATH=src python3 scripts/build_tcg.py \
  --input data/raw/Dataset-Unicauca-Version2-87Atts.csv \
  --mode build \
  --relation-types CR,PR,DHR,SHR \
  --output data/rebuild/tcg \
  --output-format parquet \
  --partition-by relation_type \
  --chunk-size 1000000
```

输出会保存在 `data/rebuild/tcg/causes_full_parts/relation_type=.../`。这是无时间窗口约束的全量因果关系图分区结果。

## 查询视图

`causes_delta_60s.parquet`、`causes_delta_300s.parquet`、`causes_delta_3600s.parquet` 等是查询阶段派生子图，不是原始 TCG 构图结果。

```bash
PYTHONPATH=src python3 scripts/query_tcg_by_delta.py \
  --input data/rebuild/tcg/causes_full_parts \
  --output data/rebuild/tcg/query_views/causes_delta_60s.parquet \
  --max-delta-seconds 60 \
  --relation-types CR,PR,DHR,SHR
```

## TuGraph 导入

`create_hcg_db.py` 和 `create_tcg_db.py` 只负责 schema 创建和已有中间文件导入。新版 TCG 不支持 `--direct-csv` 旧在线构图。

HCG 导入示例：

```bash
PYTHONPATH=src python3 scripts/create_hcg_db.py \
  --processed-dir data/rebuild/hcg \
  --progress-interval 500000
```

TCG 如需导入 TuGraph，建议先用 `--output-format csv` 生成新版中间 CSV 分区，再按实际导入策略整理为 `flows.csv` 和 `causes.csv` 后导入。全量 TCG 可能非常大，导入前先确认磁盘和 TuGraph 子图容量。

TuGraph 连接信息写在本地 `.env` 中，该文件已加入 `.gitignore`：

```bash
cp .env.example .env
```
