"""图构建公共转换函数。

本文件包含 HCG 端点/通信边字段生成、Flow 记录标准化、TCG 的 CR/PR/DHR/SHR
关系判定、边方向确定和稳定 relation_id 生成逻辑。
"""

from __future__ import annotations

import collections
import hashlib
import ipaddress
import math
from pathlib import Path
from typing import Any

from tugraph_homework.common import endpoint_id, parse_float, parse_int, parse_timestamp, progress_iter, read_rows


COMMON_SERVICE_PORTS = {20, 21, 22, 23, 25, 53, 80, 110, 143, 443, 993, 995, 3128, 8080}
PROXY_PORTS = {3128, 8080, 8000, 8888}
# TCG 关系优先级：同一对 flow 命中多个关系时，只保留数值最小的关系。
RELATION_PRIORITIES = {"CR": 1, "PR": 2, "DHR": 3, "SHR": 4}

HCG_ENDPOINT_FIELDS = [
    "endpoint_id",
    "ip",
    "port",
    "is_private_ip",
    "port_bucket",
    "is_common_service_port",
    "is_proxy_port",
]
HCG_EDGE_FIELDS = [
    "edge_id",
    "src_endpoint",
    "dst_endpoint",
    "source_id",
    "target_id",
    "flow_count",
    "first_seen_epoch",
    "last_seen_epoch",
    "first_seen",
    "last_seen",
    "total_fwd_packets",
    "total_bwd_packets",
    "total_packets",
    "total_fwd_bytes",
    "total_bwd_bytes",
    "total_bytes",
    "avg_duration",
    "min_duration",
    "max_duration",
    "protocol_set",
    "protocol_name_set",
    "major_protocol",
    "major_protocol_name",
    "protocol_entropy",
    "l7_protocol_entropy",
]
TCG_FLOW_FIELDS = [
    "record_id",
    "flow_id",
    "src_endpoint",
    "dst_endpoint",
    "src_ip",
    "src_port",
    "dst_ip",
    "dst_port",
    "protocol",
    "timestamp",
    "timestamp_epoch",
    "duration",
    "fwd_packets",
    "bwd_packets",
    "fwd_bytes",
    "bwd_bytes",
    "l7_protocol",
    "protocol_name",
    "label",
]
TCG_EDGE_FIELDS = [
    "relation_id",
    "src_record_id",
    "dst_record_id",
    "source_id",
    "target_id",
    "relation_type",
    "relation_priority",
    "delta_seconds",
    "same_timestamp",
]


def port_bucket(port: int) -> str:
    if 0 <= port <= 1023:
        return "well_known"
    if 1024 <= port <= 49151:
        return "registered"
    if 49152 <= port <= 65535:
        return "dynamic"
    return "invalid"


def is_private_ip(ip: str) -> bool:
    try:
        return ipaddress.ip_address(ip).is_private
    except ValueError:
        return False


def endpoint_parts(value: str) -> tuple[str, int]:
    if not value:
        return "", 0
    if ":" not in value:
        return value, 0
    ip, port = value.rsplit(":", 1)
    return ip, parse_int(port)


def endpoint_row(ip: str, port_value: str | int) -> dict[str, Any]:
    port = parse_int(str(port_value))
    endpoint = endpoint_id(ip, str(port))
    return {
        "endpoint_id": endpoint,
        "ip": ip,
        "port": port,
        "is_private_ip": is_private_ip(ip),
        "port_bucket": port_bucket(port),
        "is_common_service_port": port in COMMON_SERVICE_PORTS,
        "is_proxy_port": port in PROXY_PORTS,
    }


def get_first(row: dict[str, str], names: tuple[str, ...], default: str = "") -> str:
    for name in names:
        value = row.get(name)
        if value not in (None, ""):
            return value
    return default


def normalized_endpoints(row: dict[str, str]) -> tuple[str, int, str, int, str, str]:
    # 支持原始数据的 Source/Destination 字段，也支持已标准化的 src/dst 字段。
    src_ip = get_first(row, ("src_ip", "Source.IP"))
    dst_ip = get_first(row, ("dst_ip", "Destination.IP"))
    src_port_text = get_first(row, ("src_port", "Source.Port"))
    dst_port_text = get_first(row, ("dst_port", "Destination.Port"))

    if (not src_ip or not src_port_text) and row.get("src_endpoint"):
        src_ip, src_port = endpoint_parts(row["src_endpoint"])
    else:
        src_port = parse_int(src_port_text)
    if (not dst_ip or not dst_port_text) and row.get("dst_endpoint"):
        dst_ip, dst_port = endpoint_parts(row["dst_endpoint"])
    else:
        dst_port = parse_int(dst_port_text)

    src_endpoint = endpoint_id(src_ip, str(src_port))
    dst_endpoint = endpoint_id(dst_ip, str(dst_port))
    return src_ip, src_port, dst_ip, dst_port, src_endpoint, dst_endpoint


def shannon_entropy(counter: collections.Counter[Any]) -> float:
    total = sum(counter.values())
    if total <= 0:
        return 0.0
    entropy = 0.0
    for count in counter.values():
        if count > 0:
            p = count / total
            entropy -= p * math.log2(p)
    return entropy


def most_common_value(counter: collections.Counter[Any]) -> Any:
    if not counter:
        return ""
    return sorted(counter.items(), key=lambda item: (-item[1], str(item[0])))[0][0]


def stable_record_id(row_number: int, row: dict[str, str]) -> str:
    return row.get("record_id") or f"rec_{row_number:010d}"


def edge_hash(*parts: Any) -> str:
    payload = "|".join(str(part) for part in parts)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def build_hcg_rows(csv_path: Path, max_rows: int | None) -> tuple[dict[str, dict[str, Any]], dict[tuple[str, str], dict[str, Any]]]:
    endpoints: dict[str, dict[str, Any]] = {}
    edges: dict[tuple[str, str], dict[str, Any]] = {}
    # 协议计数用于生成 protocol_set、major_protocol 和 Shannon entropy。
    protocol_counts: dict[tuple[str, str], collections.Counter[int]] = collections.defaultdict(collections.Counter)
    protocol_name_counts: dict[tuple[str, str], collections.Counter[str]] = collections.defaultdict(collections.Counter)

    for row_number, row in read_rows(csv_path, max_rows=max_rows, progress_desc="aggregate HCG rows"):
        src_ip, src_port, dst_ip, dst_port, src, dst = normalized_endpoints(row)
        endpoints.setdefault(src, endpoint_row(src_ip, src_port))
        endpoints.setdefault(dst, endpoint_row(dst_ip, dst_port))

        timestamp_text, timestamp_epoch = parse_timestamp(get_first(row, ("timestamp", "Timestamp")))
        duration = parse_float(get_first(row, ("duration", "Flow.Duration"), "0"))
        fwd_packets = parse_int(get_first(row, ("fwd_packets", "Total.Fwd.Packets"), "0"))
        bwd_packets = parse_int(get_first(row, ("bwd_packets", "Total.Backward.Packets"), "0"))
        fwd_bytes = parse_int(get_first(row, ("fwd_bytes", "Total.Length.of.Fwd.Packets"), "0"))
        bwd_bytes = parse_int(get_first(row, ("bwd_bytes", "Total.Length.of.Bwd.Packets"), "0"))
        protocol = parse_int(get_first(row, ("protocol", "Protocol"), "0"))
        protocol_name = get_first(row, ("protocol_name", "ProtocolName", "l7_protocol"), "")

        # HCG 按有向端点对聚合：同一个 src_endpoint -> dst_endpoint 只保留一条 COMMUNICATES 边。
        key = (src, dst)
        edge = edges.setdefault(
            key,
            {
                "edge_id": edge_hash(src, dst, "COMMUNICATES"),
                "src_endpoint": src,
                "dst_endpoint": dst,
                "source_id": src,
                "target_id": dst,
                "flow_count": 0,
                "first_seen_epoch": timestamp_epoch,
                "last_seen_epoch": timestamp_epoch,
                "first_seen": timestamp_text,
                "last_seen": timestamp_text,
                "total_fwd_packets": 0,
                "total_bwd_packets": 0,
                "total_fwd_bytes": 0,
                "total_bwd_bytes": 0,
                "_duration_sum": 0.0,
                "min_duration": duration,
                "max_duration": duration,
            },
        )
        edge["flow_count"] += 1
        edge["total_fwd_packets"] += fwd_packets
        edge["total_bwd_packets"] += bwd_packets
        edge["total_fwd_bytes"] += fwd_bytes
        edge["total_bwd_bytes"] += bwd_bytes
        edge["_duration_sum"] += duration
        edge["min_duration"] = min(edge["min_duration"], duration)
        edge["max_duration"] = max(edge["max_duration"], duration)
        if timestamp_epoch and (not edge["first_seen_epoch"] or timestamp_epoch < edge["first_seen_epoch"]):
            edge["first_seen_epoch"] = timestamp_epoch
            edge["first_seen"] = timestamp_text
        if timestamp_epoch and timestamp_epoch > edge["last_seen_epoch"]:
            edge["last_seen_epoch"] = timestamp_epoch
            edge["last_seen"] = timestamp_text
        protocol_counts[key][protocol] += 1
        if protocol_name:
            protocol_name_counts[key][protocol_name] += 1

        if row_number % 500_000 == 0:
            print(f"aggregated_rows={row_number} endpoints={len(endpoints)} edges={len(edges)}", flush=True)

    for key, edge in progress_iter(edges.items(), "finalize HCG edges", "edges", len(edges)):
        edge["total_packets"] = edge["total_fwd_packets"] + edge["total_bwd_packets"]
        edge["total_bytes"] = edge["total_fwd_bytes"] + edge["total_bwd_bytes"]
        edge["avg_duration"] = edge["_duration_sum"] / edge["flow_count"] if edge["flow_count"] else 0.0
        edge["protocol_set"] = ",".join(str(value) for value in sorted(protocol_counts.get(key, {})))
        edge["protocol_name_set"] = ",".join(sorted(protocol_name_counts.get(key, {})))
        edge["major_protocol"] = most_common_value(protocol_counts.get(key, collections.Counter()))
        edge["major_protocol_name"] = most_common_value(protocol_name_counts.get(key, collections.Counter()))
        edge["protocol_entropy"] = shannon_entropy(protocol_counts.get(key, collections.Counter()))
        edge["l7_protocol_entropy"] = shannon_entropy(protocol_name_counts.get(key, collections.Counter()))
        edge.pop("_duration_sum", None)
    return endpoints, edges


def flow_vertex(row_number: int, row: dict[str, str]) -> dict[str, Any]:
    src_ip, src_port, dst_ip, dst_port, src, dst = normalized_endpoints(row)
    timestamp_text, timestamp_epoch = parse_timestamp(get_first(row, ("timestamp", "Timestamp")))
    return {
        # flow_id 在数据集中可能重复，不能作为 Flow 主键；缺失 record_id 时用原始行号生成稳定主键。
        "record_id": stable_record_id(row_number, row),
        "flow_id": get_first(row, ("flow_id", "Flow.ID")),
        "src_endpoint": src,
        "dst_endpoint": dst,
        "src_ip": src_ip,
        "src_port": src_port,
        "dst_ip": dst_ip,
        "dst_port": dst_port,
        "protocol": parse_int(get_first(row, ("protocol", "Protocol"), "0")),
        "timestamp": timestamp_text,
        "timestamp_epoch": timestamp_epoch,
        "duration": parse_float(get_first(row, ("duration", "Flow.Duration"), "0")),
        "fwd_packets": parse_int(get_first(row, ("fwd_packets", "Total.Fwd.Packets"), "0")),
        "bwd_packets": parse_int(get_first(row, ("bwd_packets", "Total.Backward.Packets"), "0")),
        "fwd_bytes": parse_int(get_first(row, ("fwd_bytes", "Total.Length.of.Fwd.Packets"), "0")),
        "bwd_bytes": parse_int(get_first(row, ("bwd_bytes", "Total.Length.of.Bwd.Packets"), "0")),
        "l7_protocol": parse_int(get_first(row, ("l7_protocol", "L7Protocol"), "0")),
        "protocol_name": get_first(row, ("protocol_name", "ProtocolName")),
        "label": get_first(row, ("label", "Label")),
    }


def classify_relation(left: dict[str, Any], right: dict[str, Any]) -> tuple[str, str] | None:
    if left["record_id"] == right["record_id"]:
        return None
    # CR：协议相同且五元组方向相反，近似请求-响应关系。
    if (
        left["protocol"] == right["protocol"]
        and left["src_ip"] == right["dst_ip"]
        and left["src_port"] == right["dst_port"]
        and left["dst_ip"] == right["src_ip"]
        and left["dst_port"] == right["src_port"]
    ):
        return "CR", "reverse_five_tuple"
    # PR：上一条流的目的主机又成为下一条流的源主机，近似传播/代理/转发。
    if left["dst_ip"] == right["src_ip"]:
        return "PR", "dst_ip_to_src_ip"
    # DHR/SHR：同一源主机按源端口是否变化区分动态端口和静态端口关系。
    if left["src_ip"] == right["src_ip"] and left["src_port"] != right["src_port"]:
        return "DHR", "same_src_ip_different_src_port"
    if left["src_ip"] == right["src_ip"] and left["src_port"] == right["src_port"]:
        return "SHR", "same_src_ip_same_src_port"
    return None


def orient_flow_pair(left: dict[str, Any], right: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], int, bool]:
    # 边方向只由时间和 record_id 决定；delta_seconds 只保存为属性，不在这里过滤。
    left_ts = int(left.get("timestamp_epoch", 0))
    right_ts = int(right.get("timestamp_epoch", 0))
    if left_ts < right_ts:
        return left, right, right_ts - left_ts, False
    if left_ts > right_ts:
        return right, left, left_ts - right_ts, False
    if str(left["record_id"]) <= str(right["record_id"]):
        return left, right, 0, True
    return right, left, 0, True


def tcg_edge(left: dict[str, Any], right: dict[str, Any], relation_type: str) -> dict[str, Any]:
    src, dst, delta_seconds, same_timestamp = orient_flow_pair(left, right)
    relation_id = edge_hash(src["record_id"], dst["record_id"], relation_type)
    return {
        "relation_id": relation_id,
        "src_record_id": src["record_id"],
        "dst_record_id": dst["record_id"],
        "source_id": src["record_id"],
        "target_id": dst["record_id"],
        "relation_type": relation_type,
        "relation_priority": RELATION_PRIORITIES[relation_type],
        "delta_seconds": delta_seconds,
        "same_timestamp": same_timestamp,
    }
