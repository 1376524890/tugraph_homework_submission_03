# coding=utf-8
"""Batched HCG node2vec random-walk Python stored procedure for TuGraph."""

import json
import math
import os
import random
import time


def _safe_int(value, default):
    try:
        return int(value)
    except Exception:
        return default


def _safe_float(value, default):
    try:
        return float(value)
    except Exception:
        return default


def _field_value(item, field_name):
    try:
        return item[field_name]
    except Exception:
        pass
    try:
        return item.GetField(field_name)
    except Exception:
        return None


def _field_to_float(value, default=1.0):
    if value is None:
        return default
    for attr in ("AsInt64", "AsDouble", "AsFloat", "integer", "real"):
        try:
            return float(getattr(value, attr)())
        except Exception:
            pass
    try:
        return float(value)
    except Exception:
        pass
    try:
        return float(str(value))
    except Exception:
        return default


def _field_to_string(value, default=""):
    if value is None:
        return default
    for attr in ("AsString", "ToString", "string"):
        try:
            return str(getattr(value, attr)())
        except Exception:
            pass
    try:
        return str(value)
    except Exception:
        return default


def _parse_params(input_text):
    params = json.loads(input_text or "{}")
    walk_length = _safe_int(params.get("walk_length", params.get("walk_len", 20)), 20)
    num_walks = _safe_int(params.get("num_walks", 5), 5)
    p = _safe_float(params.get("p", 1.0), 1.0)
    q = _safe_float(params.get("q", 1.0), 1.0)
    max_start_nodes = _safe_int(params.get("max_start_nodes", 1000), 1000)
    start_offset = _safe_int(params.get("start_offset", 0), 0)
    start_vid = _safe_int(params.get("start_vid", -1), -1)
    seed = _safe_int(params.get("seed", 20260524), 20260524)
    max_elapsed_seconds = _safe_float(params.get("max_elapsed_seconds", 0), 0)
    weight_field = params.get("weight_field", "flow_count")
    weight_transform = params.get("weight_transform", "log1p")
    return {
        "output_path": params.get("output_path", "/tmp/hcg_walks_node2vec_py_batch.txt"),
        "id_map_path": params.get("id_map_path", "/tmp/hcg_node_id_map_node2vec_py_batch.csv"),
        "walk_length": max(1, walk_length),
        "num_walks": max(1, num_walks),
        "p": p if p > 0 else 1.0,
        "q": q if q > 0 else 1.0,
        "max_start_nodes": max_start_nodes,
        "start_offset": max(0, start_offset),
        "start_vid": start_vid,
        "seed": seed,
        "return_preview_lines": max(0, _safe_int(params.get("return_preview_lines", 5), 5)),
        "only_start_nodes_with_out_edges": bool(params.get("only_start_nodes_with_out_edges", True)),
        "max_elapsed_seconds": max_elapsed_seconds if max_elapsed_seconds > 0 else 0,
        "weight_field": weight_field or "flow_count",
        "weight_transform": weight_transform if weight_transform in ("log1p", "none", "sqrt") else "log1p",
        "token_field": params.get("token_field", "endpoint_id") or "endpoint_id",
    }


def _ensure_parent(path):
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)


def Process(db, input):
    started = time.time()
    params = _parse_params(input)
    random.seed(params["seed"])
    _ensure_parent(params["output_path"])
    _ensure_parent(params["id_map_path"])

    txn = db.CreateReadTxn()
    neighbor_cache = {}
    start_nodes = []
    touched = set()
    preview = []
    walk_count = 0
    completed_start_node_count = 0
    stopped_reason = ""
    token_cache = {}
    weight_fallback_count = 0

    def time_budget_exceeded():
        return params["max_elapsed_seconds"] > 0 and (time.time() - started) >= params["max_elapsed_seconds"]

    def edge_weight(eit):
        nonlocal weight_fallback_count
        raw = _field_to_float(_field_value(eit, params["weight_field"]), 1.0)
        if raw <= 0:
            raw = 1.0
            weight_fallback_count += 1
        if params["weight_transform"] == "none":
            return max(raw, 1e-12)
        if params["weight_transform"] == "sqrt":
            return max(math.sqrt(raw), 1e-12)
        return max(math.log1p(raw), 1e-12)

    def vertex_token(vid):
        vid = int(vid)
        if vid in token_cache:
            return token_cache[vid]
        token = str(vid)
        try:
            vit = txn.GetVertexIterator(vid)
            if vit.IsValid():
                token = _field_to_string(_field_value(vit, params["token_field"]), token) or token
        except Exception:
            pass
        token_cache[vid] = token
        return token

    def get_neighbors(vid):
        vid = int(vid)
        if vid in neighbor_cache:
            return neighbor_cache[vid]
        neighbors = []
        vit = txn.GetVertexIterator(vid)
        if vit.IsValid():
            eit = vit.GetOutEdgeIterator()
            while eit.IsValid():
                neighbors.append((int(eit.GetDst()), edge_weight(eit)))
                eit.Next()
        neighbor_cache[vid] = neighbors
        return neighbors

    def choose_weighted(entries):
        total = 0.0
        for _, weight in entries:
            total += weight
        if total <= 0:
            return random.choice(entries)[0]
        threshold = random.random() * total
        cumulative = 0.0
        for dst, weight in entries:
            cumulative += weight
            if cumulative >= threshold:
                return dst
        return entries[-1][0]

    def pick_start_nodes():
        if params["start_vid"] >= 0:
            vit = txn.GetVertexIterator(params["start_vid"])
            if not vit.IsValid():
                raise RuntimeError("start_vid does not exist: {}".format(params["start_vid"]))
            return [params["start_vid"]]

        selected = []
        seen = 0
        vit = txn.GetVertexIterator()
        while vit.IsValid():
            vid = int(vit.GetId())
            if (not params["only_start_nodes_with_out_edges"]) or get_neighbors(vid):
                if seen >= params["start_offset"]:
                    selected.append(vid)
                    if params["max_start_nodes"] > 0 and len(selected) >= params["max_start_nodes"]:
                        break
                seen += 1
            vit.Next()
        return selected

    try:
        start_nodes = pick_start_nodes()
        with open(params["output_path"], "w", encoding="utf-8") as walks_out:
            for walk_round in range(params["num_walks"]):
                for start_vid in start_nodes:
                    if time_budget_exceeded():
                        stopped_reason = "max_elapsed_seconds"
                        break
                    walk = [int(start_vid)]
                    previous = None
                    current = int(start_vid)
                    while len(walk) < params["walk_length"]:
                        neighbors = get_neighbors(current)
                        if not neighbors:
                            break
                        if previous is None or (params["p"] == 1.0 and params["q"] == 1.0):
                            next_node = choose_weighted(neighbors)
                        else:
                            previous_neighbors = {dst for dst, _ in get_neighbors(previous)}
                            weighted_candidates = []
                            for candidate, edge_weight_value in neighbors:
                                if candidate == previous:
                                    bias = 1.0 / params["p"]
                                elif candidate in previous_neighbors:
                                    bias = 1.0
                                else:
                                    bias = 1.0 / params["q"]
                                weighted_candidates.append((candidate, edge_weight_value * bias))
                            next_node = choose_weighted(weighted_candidates)
                        walk.append(int(next_node))
                        previous = current
                        current = int(next_node)

                    touched.update(walk)
                    line = " ".join(vertex_token(vid) for vid in walk)
                    walks_out.write(line + "\n")
                    if len(preview) < params["return_preview_lines"]:
                        preview.append(line)
                    walk_count += 1
                    if walk_round == 0:
                        completed_start_node_count += 1
                if stopped_reason:
                    break

        with open(params["id_map_path"], "w", encoding="utf-8") as id_map_out:
            id_map_out.write("vid,token\n")
            for vid in sorted(touched):
                token = vertex_token(vid).replace('"', '""')
                id_map_out.write('{},"{}"\n'.format(vid, token))

        response = {
            "status": "ok",
            "procedure": "hcg_node2vec_walk_py_batch",
            "output_path": params["output_path"],
            "id_map_path": params["id_map_path"],
            "start_offset": params["start_offset"],
            "start_node_count": len(start_nodes),
            "next_start_offset": params["start_offset"] + len(start_nodes),
            "walk_count": walk_count,
            "completed_start_node_count": completed_start_node_count,
            "walk_length": params["walk_length"],
            "num_walks": params["num_walks"],
            "max_elapsed_seconds": params["max_elapsed_seconds"],
            "stopped_reason": stopped_reason,
            "p": params["p"],
            "q": params["q"],
            "weight_field": params["weight_field"],
            "weight_transform": params["weight_transform"],
            "token_field": params["token_field"],
            "weight_fallback_count": weight_fallback_count,
            "touched_node_count": len(touched),
            "cached_neighbor_count": len(neighbor_cache),
            "cached_token_count": len(token_cache),
            "preview": preview,
            "elapsed_seconds": time.time() - started,
        }
        return (True, json.dumps(response, ensure_ascii=False))
    except Exception as exc:
        response = {
            "status": "error",
            "procedure": "hcg_node2vec_walk_py_batch",
            "message": str(exc),
            "elapsed_seconds": time.time() - started,
        }
        return (True, json.dumps(response, ensure_ascii=False))
    finally:
        try:
            txn.Abort()
        except Exception:
            pass
