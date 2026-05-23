# HCG Random Walk C++ Procedure Environment Check

检查日期：2026-05-24

## 结论

当前作业仓库没有发现可直接复用的 TuGraph C++ 存储过程示例。进一步全盘检查发现本机存在 TuGraph 源码树 `/home/marktom/tugraph/tugraph-db/`，其中包含官方 C++ procedure 示例、`lgraph/lgraph.h` 和 `tools/json.hpp`。本次交付的 C++ 源码使用条件 include：如果 WebUI 编译环境可见 `tools/json.hpp`，优先用 `nlohmann::json` 解析参数；否则退回单文件内置的最小 JSON 参数解析器。入口使用 TuGraph v1 C++ 插件入口：

```cpp
#include "lgraph/lgraph.h"
using namespace lgraph_api;

extern "C" LGAPI bool Process(GraphDB& db,
                              const std::string& request,
                              std::string& response)
```

本地尝试使用 `/home/marktom/tugraph/tugraph-db/include` 做 `g++ -std=c++14 -fsyntax-only`，编译在 TuGraph 头文件依赖处停止，原因是当前系统缺少 Boost 头 `boost/date_time/posix_time/posix_time.hpp`。因此本地未完成完整 C++ 编译验证；WebUI 的 TuGraph 编译环境通常应自带这些依赖。若 WebUI 编译报 TuGraph API 或 include 路径不匹配，需要按 WebUI 编译报错调整 `#include "lgraph/lgraph.h"`、入口函数签名或迭代器 API。

后续在 `tugraph-db` 容器中复查 WebUI 编译错误，确认容器 `/usr/local/include/lgraph/lgraph.h` 会引入 `/usr/local/include/tools/lgraph_log.h`，而容器内不存在 Boost 头。由于容器可能无法连接外网，已增加本地 `.so` 编译脚本 `scripts/build_hcg_cpp_plugins_in_docker.sh`，使用编译期 stub 生成可上传的 `.so`：

- `build/tugraph_cpp_plugins/hcg_weighted_walk_v1.so`
- `build/tugraph_cpp_plugins/hcg_node2vec_walk_v2.so`

容器内 TuGraph 头还使用了 `std::optional` 和 `std::any`，因此 `.so` 编译使用 `-std=c++17`。

## 1. 找到的 TuGraph C++ 存储过程示例路径

未在当前作业仓库以下路径发现 C++ 存储过程示例：

- `procedures/`
- `plugins/`
- `cpp_plugins/`
- `src/`
- `scripts/`
- `docker/`
- `docs/`
- `README.md`

搜索关键词包括：

- `Process(GraphDB`
- `LGAPI`
- `lgraph_api`
- `GetVertexIterator`
- `GetOutEdgeIterator`
- `cpp_plugin`
- `procedure`
- `plugin`
- `stored procedure`
- `TuGraph`
- `C++`

当前作业仓库中找到的是 TuGraph 数据导入、schema、Docker 和实验记录相关内容，例如：

- `scripts/create_tugraph_import_config.py`
- `scripts/import_tugraph_native.py`
- `docs/graph_modeling.md`
- `docs/experiment_record.md`
- `README.md`

在本机 TuGraph 源码树中找到的相关示例：

- `/home/marktom/tugraph/tugraph-db/procedures/demo/v1_scan_graph.cpp`
- `/home/marktom/tugraph/tugraph-db/test/test_procedures/sortstr.cpp`
- `/home/marktom/tugraph/tugraph-db/procedures/algo_cpp/khop_kth.cpp`
- `/home/marktom/tugraph/tugraph-db/procedures/custom_cpp/*_procedure.cpp`

这些示例确认了以下常见写法：

- `#include "lgraph/lgraph.h"`
- `#include "tools/json.hpp"`
- `using namespace lgraph_api;`
- `extern "C" LGAPI bool Process(GraphDB &db, const std::string &request, std::string &response)`
- `db.CreateReadTxn()`
- `txn.GetVertexIterator()`
- `vit.GetOutEdgeIterator()`

## 2. 当前可用的头文件路径

当前作业仓库内未发现：

- `/usr/local/include/lgraph/`
- `include/lgraph.h`
- `lgraph.h`
- `tools/json.hpp`
- `nlohmann/json.hpp`
- `/usr/include/nlohmann/json.hpp`
- `/usr/local/include/nlohmann/json.hpp`

本机其他路径发现：

- `/home/marktom/tugraph/tugraph-db/include/lgraph/lgraph.h`
- `/home/marktom/tugraph/tugraph-db/include/tools/json.hpp`
- `/home/marktom/tugraph/tugraph-db/demo/ProcedureDemo/cpp/json.hpp`
- `/home/marktom/miniconda3/include/nlohmann/json.hpp`

## 3. 当前可用的 liblgraph.so 路径

未在常见系统库路径发现：

- `/usr/local/lib64/liblgraph.so`
- `/usr/local/lib/liblgraph.so`

本次检查未发现 `/home/marktom/tugraph/tugraph-db` 下的 `liblgraph.so`。

## 4. WebUI 上传编译可能需要的源码格式

推荐通过 TuGraph WebUI 新建 C++ 存储过程，分别上传以下单文件源码：

- `procedures/hcg_weighted_walk_v1.cpp`
- `procedures/hcg_node2vec_walk_v2.cpp`

建议设置：

- procedure name: `hcg_weighted_walk_v1` 或 `hcg_node2vec_walk_v2`
- graph/subgraph: `hcg`
- mode: read-only
- request: JSON 字符串
- response: JSON 字符串

当前源码不依赖项目内自定义头文件，不依赖 OpenMP，不依赖 boost/rapidjson。

## 5. 是否可以使用 nlohmann/json 或 tools/json.hpp

本机 TuGraph 源码树存在 `/home/marktom/tugraph/tugraph-db/include/tools/json.hpp`，Conda 环境存在 `/home/marktom/miniconda3/include/nlohmann/json.hpp`。但 WebUI 上传编译时不一定暴露 Conda include 路径。

当前两个 C++ procedure 通过 `__has_include("tools/json.hpp")` 自动判断：可用时使用官方示例里的 `nlohmann::json`，不可用时使用内置最小参数解析器。若 WebUI 编译器不支持 `__has_include`，可删除条件 include 块并保留内置解析器，或直接固定 include `tools/json.hpp`。

## 6. JSON 库不可用时的方案

源码中已经实现最小 JSON 参数解析函数，只解析本任务需要的 string/int/int64/double/bool 字段。该解析器适合本任务给定的扁平 JSON 参数，不适合作为通用 JSON 解析器。

## 7. 推荐上传到 WebUI 的源码文件名

- first-order weighted random walk: `hcg_weighted_walk_v1.cpp`
- second-order node2vec random walk: `hcg_node2vec_walk_v2.cpp`

## 需要注意

当前本地 TuGraph 源码示例确认了主要 API 形态，但本地系统缺少 Boost 头，未完成完整编译。若 WebUI 编译时报错，请优先检查：

- `#include "lgraph/lgraph.h"` 是否需要改成 `#include "lgraph.h"`。
- `VertexIterator::GetLabel()`、`OutEdgeIterator::GetLabel()`、`GetField()`、`GetDst()` 方法名是否与当前 TuGraph 版本一致。
- `FieldData::AsInt64()`、`AsDouble()`、`AsString()` 方法名是否与当前 TuGraph 版本一致。
- WebUI 是否要求只上传函数体，或允许完整 `.cpp` 文件。

如 WebUI 报 include 或 API 错误，应根据报错调整 include 路径或 JSON 解析头文件。
