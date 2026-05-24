# HCG Random Walk Procedure Usage

本文档说明 HCG random walks 的存储过程方案。当前可用 node2vec 二阶游走实现是 Python 存储过程 `procedures/hcg_node2vec_walk_py.py`。C++ node2vec v2 已归档为不可用，不要上传或执行。

## 源码文件

- `procedures/hcg_weighted_walk_v1.cpp`
  - weighted first-order random walk。
  - 等价于 DeepWalk / node2vec `p=1, q=1` 的一阶游走。
  - 支持 `weighted`、`weight_field`、`weight_transform`、`directed`、`max_start_nodes`。

- `procedures/archived_node2vec/hcg_node2vec_walk_v2_unusable.cpp`
  - 已归档，不可用。
  - 当前 TuGraph 4.5.2 runtime 中调用会导致服务或 plugin runner 崩溃。

- `procedures/hcg_node2vec_walk_py.py`
  - 当前可用 node2vec second-order random walk。
  - 通过 Python 存储过程在 TuGraph 数据库侧生成 walks。
  - 支持 `p`、`q` 二阶转移偏置。

当前可用过程都只读 HCG 图，不修改数据库数据，只写服务端或容器内 walks 文件和 id map 文件。

## WebUI 上传编译步骤

1. 打开 TuGraph WebUI。
2. 进入 `hcg` 子图。
3. 进入存储过程或插件管理页面。
4. 新建 C++ 存储过程。
5. 上传 `procedures/hcg_weighted_walk_v1.cpp`。
6. 设置名称 `hcg_weighted_walk_v1`。
7. 选择只读或 read-only。
8. 编译。
9. 输入 JSON 参数进行 smoke test。
10. 查看 response JSON。
11. 检查 `output_path` 是否生成 walks 文件。
12. 不要上传已归档的 `procedures/archived_node2vec/hcg_node2vec_walk_v2_unusable.cpp`。

## Python node2vec 存储过程

上传并执行 smoke：

```bash
PYTHONPATH=src python3 scripts/run_hcg_node2vec_procedure.py \
  --upload \
  --delete-first \
  --call \
  --max-start-nodes 1000 \
  --walk-length 10 \
  --num-walks 2 \
  --output-path /tmp/hcg_walks_node2vec_py_smoke_1000.txt \
  --id-map-path /tmp/hcg_node_id_map_node2vec_py_smoke_1000.csv \
  --timeout 600
```

当前 1000 起点 smoke：`2000` 条 walks，过程耗时 `15.0082` 秒，检查报告为 `data/features/hcg/reports/hcg_node2vec_py_procedure_smoke_1000_check.md`。

全量估算：HCG 有 `865950` 个有出边 Endpoint，`num_walks=5` 时约 `4329750` 条 walks。按当前 Python 存储过程 smoke 吞吐估算，`walk_length=20,num_walks=5` 约需 `10-18` 小时，因此未自动执行全量。

如果 WebUI 编译要求与本地源码不同，优先按编译报错调整：

- `#include "lgraph/lgraph.h"` 可能需要改成 `#include "lgraph.h"`。
- 入口函数当前使用 TuGraph v1 风格 `extern "C" LGAPI bool Process(GraphDB& db, const std::string& request, std::string& response)`。
- 如果当前 TuGraph 版本迭代器 API 不同，需要调整 `GetVertexIterator()`、`GetOutEdgeIterator()`、`GetLabel()`、`GetField()`、`GetDst()` 调用。
- 源码会用 `__has_include("tools/json.hpp")` 优先启用 TuGraph 自带 JSON 头；如果 WebUI 编译器不支持 `__has_include`，可删除文件顶部条件 include 块，使用源码内置的最小参数解析器。

## 本地编译 `.so` 后上传

当前 `tugraph-db` 容器缺少 Boost 头，WebUI 直接编译源码会报：

```text
fatal error: boost/date_time/posix_time/posix_time.hpp: No such file or directory
```

如果容器不能访问外网安装 `boost-devel`，可以在容器内使用本仓库提供的轻量编译 stub 生成 `.so`，再在 WebUI 上传 `.so` 文件：

```bash
bash scripts/build_hcg_cpp_plugins_in_docker.sh
```

产物路径：

```text
build/tugraph_cpp_plugins/hcg_weighted_walk_v1.so
```

这套编译方式只在编译期用 stub 绕过 TuGraph 头文件中的 Boost Log/Geometry include，不改变 TuGraph 数据库数据，也不修改正在运行的 TuGraph 服务。容器里的 TuGraph 头使用了 `std::optional` 和 `std::any`，因此本地 `.so` 编译参数使用 `-std=c++17`。

也可以在宿主机直接编译：

```bash
bash scripts/build_hcg_cpp_plugins_local.sh
```

宿主机产物路径：

```text
build/tugraph_cpp_plugins_host/hcg_weighted_walk_v1.so
```

但当前宿主机是 Ubuntu 24.04 / GCC 13 / glibc 2.39，本地编译出的 `.so` 会引用较新的 `GLIBC_2.38`、`GLIBCXX_3.4.32` 等符号。当前 TuGraph 容器是 CentOS 7，运行时大概率没有这些符号，因此**不推荐把宿主机直接编译产物上传到当前 WebUI**。当前推荐上传的是容器内编译产物：

```text
build/tugraph_cpp_plugins/hcg_weighted_walk_v1.so
```

实际实验中不使用 `build/tugraph_cpp_plugins_host/` 下的宿主机编译版本；该目录只保留用于 ABI 风险验证。后续 C++ v1 源码变更后，统一重新执行 `bash scripts/build_hcg_cpp_plugins_in_docker.sh`，再上传 `build/tugraph_cpp_plugins/` 下的容器编译版本。

## v1 Smoke Test 参数

```json
{
  "output_path": "/tmp/hcg_walks_v1_smoke.txt",
  "id_map_path": "/tmp/hcg_node_id_map_v1_smoke.csv",
  "walk_length": 10,
  "num_walks": 2,
  "weighted": true,
  "weight_field": "flow_count",
  "weight_transform": "log1p",
  "directed": true,
  "seed": 20260524,
  "max_start_nodes": 1000,
  "use_endpoint_id_token": true,
  "return_preview_lines": 5
}
```

## 已归档 C++ v2 Node2Vec 参数

C++ v2 node2vec 已归档为不可用，不再提供 smoke 参数。请使用上面的 Python node2vec 存储过程命令。

## 小规模正式参数

```json
{
  "output_path": "/var/lib/lgraph/walks/hcg_walks_v1_10k.txt",
  "id_map_path": "/var/lib/lgraph/walks/hcg_node_id_map_v1_10k.csv",
  "walk_length": 20,
  "num_walks": 5,
  "weighted": true,
  "weight_field": "flow_count",
  "weight_transform": "log1p",
  "directed": true,
  "seed": 20260524,
  "max_start_nodes": 10000,
  "use_endpoint_id_token": true,
  "return_preview_lines": 5
}
```

## 全量参数模板

```json
{
  "output_path": "/var/lib/lgraph/walks/hcg_walks_v1_full.txt",
  "id_map_path": "/var/lib/lgraph/walks/hcg_node_id_map_v1_full.csv",
  "walk_length": 20,
  "num_walks": 5,
  "weighted": true,
  "weight_field": "flow_count",
  "weight_transform": "log1p",
  "directed": true,
  "seed": 20260524,
  "max_start_nodes": 0,
  "use_endpoint_id_token": true,
  "return_preview_lines": 5
}
```

## 输出文件检查命令

```bash
wc -l /tmp/hcg_walks_v1_smoke.txt
head -n 5 /tmp/hcg_walks_v1_smoke.txt
head -n 5 /tmp/hcg_node_id_map_v1_smoke.csv
```

使用本仓库检查脚本：

```bash
python3 scripts/check_walks_file.py \
  --walks /tmp/hcg_walks_v1_smoke.txt \
  --expected-min-lines 1000 \
  --min-walk-len 2 \
  --max-preview 10
```

默认报告写入：

```text
data/features/hcg/reports/hcg_walks_smoke_check.md
```

## 后续 Python word2vec 训练命令模板

```bash
PYTHONPATH=src python3 scripts/train_word2vec_embeddings.py \
  --walks /var/lib/lgraph/walks/hcg_walks_v1_full.txt \
  --output data/features/hcg/node2vec/hcg_endpoint_node2vec_d64.parquet \
  --vector-size 64 \
  --window 5 \
  --negative 5 \
  --epochs 3 \
  --workers 16 \
  --min-count 0
```

## 常见错误

- 编译找不到 `lgraph.h`：WebUI 编译环境 include 路径与源码不一致，尝试把 `#include "lgraph/lgraph.h"` 改成 `#include "lgraph.h"`。
- 找不到 JSON 头文件：当前源码未依赖 JSON 头，已内置最小参数解析器。
- `endpoint_id` 字段名不一致：walks 会退回使用 vid token，并在 response `warnings` 中提示。
- `flow_count` 字段类型不是 int：源码会尝试 int64、double、string 数值解析，失败则边权退回 1.0。
- `output_path` 不可写：创建父目录，并确认 TuGraph 服务进程或容器用户有写权限。
- WebUI 编译不允许写 `/var/lib/lgraph`：先用 `/tmp/...` 做 smoke test，确认容器内路径权限。
- 返回 preview 正常但文件未生成：可能是容器路径不可见、挂载路径不在宿主机同一位置，或权限不足。
- walks 行数少于预期：可能是 `max_start_nodes` 限制、部分 Endpoint 无出边，或过程提前失败。

## 实现风险提醒

1. C++ 存储过程适合生成 walks，但不负责 word2vec 训练。
2. 全量 HCG 约有近百万 Endpoint，`walk_length=20`、`num_walks=5` 时，walk token 可能接近上亿级，输出文件可能很大。
3. 全量运行前必须先跑 `max_start_nodes=1000` 和 `max_start_nodes=10000`。
4. 如果 `directed=true`，出度为 0 的节点会生成短 walk。
5. 如果想提高覆盖率，可以尝试 `directed=false`。
6. 如果文件过大，可以把 `use_endpoint_id_token=false`，改用 vid token，并使用 id map 映射回 `endpoint_id`。
7. 如果 C++ v2 过慢，先使用 v1 作为第一版 HCG embedding。
8. v1 的结果可作为 DeepWalk / node2vec `p=1,q=1` 的基线。
9. v2 才是严格 node2vec 二阶游走版本。
10. 后续分类实验应比较 F0、F3、F4，验证 HCG embedding 是否提升 `protocol_name` 或 `l7_protocol` 分类效果。
