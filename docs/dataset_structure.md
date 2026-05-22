# 数据集结构

数据文件：`data/raw/Dataset-Unicauca-Version2-87Atts.csv`

检查结果：

| 指标 | 值 |
| --- | ---: |
| 文件大小 | 1767404086 bytes |
| 数据行数 | 3577296 |
| 字段数 | 87 |
| 唯一 `{IP, port}` 端点数 | 935600 |
| 唯一 `Flow.ID` 数 | 1522917 |

关键字段：

| 字段 | 含义 |
| --- | --- |
| `Flow.ID` | 数据集原始流 ID，会重复，不能作为唯一主键。 |
| `Source.IP`, `Source.Port` | 源端点。 |
| `Destination.IP`, `Destination.Port` | 目的端点。 |
| `Protocol` | L4 协议编号。 |
| `Timestamp` | 流时间，样例格式为 `26/04/201711:11:17`。 |
| `Flow.Duration` | 流持续时间。 |
| `Total.Fwd.Packets`, `Total.Backward.Packets` | 正反向包数。 |
| `Total.Length.of.Fwd.Packets`, `Total.Length.of.Bwd.Packets` | 正反向字节数。 |
| `Label` | 标签，抽样前 20 万行为 `BENIGN`。 |
| `L7Protocol`, `ProtocolName` | 应用层协议编号和名称。 |

完整字段可通过以下命令查看：

```bash
PYTHONPATH=src python3 scripts/inspect_dataset.py --sample-rows 200000
```
