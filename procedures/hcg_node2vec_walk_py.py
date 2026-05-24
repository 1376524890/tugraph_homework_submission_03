# coding=utf-8
"""HCG node2vec random-walk Python stored procedure for TuGraph.

This is the active implementation for generating walks inside TuGraph.
The archived C++ node2vec procedure is not used because it crashes the
current TuGraph 4.5.2 runtime during plugin return/cleanup.
"""

import json
import os
import random
import time


def _vid_token(vid):
    return str(int(vid))


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


def _parse_params(input_text):
    params = json.loads(input_text or "{}")
    walk_length = _safe_int(params.get("walk_length", params.get("walk_len", 20)), 20)
    num_walks = _safe_int(params.get("num_walks", 5), 5)
    p = _safe_float(params.get("p", 1.0), 1.0)
    q = _safe_float(params.get("q", 1.0), 1.0)
    max_start_nodes = _safe_int(params.get("max_start_nodes", 1000), 1000)
    start_vid = _safe_int(params.get("start_vid", -1), -1)
    seed = _safe_int(params.get("seed", 20260524), 20260524)
    return {
        "output_path": params.get("output_path", "/tmp/hcg_walks_node2vec_py.txt"),
        "id_map_path": params.get("id_map_path", "/tmp/hcg_node_id_map_node2vec_py.csv"),
        "walk_length": max(1, walk_length),
        "num_walks": max(1, num_walks),
        "p": p if p > 0 else 1.0,
        "q": q if q > 0 else 1.0,
        "max_start_nodes": max_start_nodes,
        "start_vid": start_vid,
        "seed": seed,
        "return_preview_lines": max(0, _safe_int(params.get("return_preview_lines", 5), 5)),
        "only_start_nodes_with_out_edges": bool(params.get("only_start_nodes_with_out_edges", True)),
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

    def get_neighbors(vid):
        vid = int(vid)
        if vid in neighbor_cache:
            return neighbor_cache[vid]
        neighbors = []
        vit = txn.GetVertexIterator(vid)
        if vit.IsValid():
            eit = vit.GetOutEdgeIterator()
            while eit.IsValid():
                neighbors.append(int(eit.GetDst()))
                eit.Next()
        neighbor_cache[vid] = neighbors
        return neighbors

    try:
        if params["start_vid"] >= 0:
            vit = txn.GetVertexIterator(params["start_vid"])
            if not vit.IsValid():
                raise RuntimeError("start_vid does not exist: {}".format(params["start_vid"]))
            start_nodes.append(params["start_vid"])
        else:
            vit = txn.GetVertexIterator()
            while vit.IsValid():
                vid = int(vit.GetId())
                if (not params["only_start_nodes_with_out_edges"]) or get_neighbors(vid):
                    start_nodes.append(vid)
                    if params["max_start_nodes"] > 0 and len(start_nodes) >= params["max_start_nodes"]:
                        break
                vit.Next()

        with open(params["output_path"], "w", encoding="utf-8") as walks_out:
            for _ in range(params["num_walks"]):
                for start_vid in start_nodes:
                    walk = [int(start_vid)]
                    previous = None
                    current = int(start_vid)
                    while len(walk) < params["walk_length"]:
                        neighbors = get_neighbors(current)
                        if not neighbors:
                            break
                        if previous is None:
                            next_node = random.choice(neighbors)
                        else:
                            previous_neighbors = set(get_neighbors(previous))
                            weights = []
                            for candidate in neighbors:
                                if candidate == previous:
                                    weights.append(1.0 / params["p"])
                                elif candidate in previous_neighbors:
                                    weights.append(1.0)
                                else:
                                    weights.append(1.0 / params["q"])
                            next_node = random.choices(neighbors, weights=weights, k=1)[0]
                        walk.append(int(next_node))
                        previous = current
                        current = int(next_node)

                    touched.update(walk)
                    line = " ".join(_vid_token(vid) for vid in walk)
                    walks_out.write(line + "\n")
                    if len(preview) < params["return_preview_lines"]:
                        preview.append(line)
                    walk_count += 1

        with open(params["id_map_path"], "w", encoding="utf-8") as id_map_out:
            id_map_out.write("vid,token\n")
            for vid in sorted(touched):
                id_map_out.write('{},"{}"\n'.format(vid, _vid_token(vid)))

        response = {
            "status": "ok",
            "procedure": "hcg_node2vec_walk_py",
            "output_path": params["output_path"],
            "id_map_path": params["id_map_path"],
            "start_node_count": len(start_nodes),
            "walk_count": walk_count,
            "walk_length": params["walk_length"],
            "num_walks": params["num_walks"],
            "p": params["p"],
            "q": params["q"],
            "touched_node_count": len(touched),
            "cached_neighbor_count": len(neighbor_cache),
            "preview": preview,
            "elapsed_seconds": time.time() - started,
        }
        return (True, json.dumps(response, ensure_ascii=False))
    except Exception as exc:
        response = {
            "status": "error",
            "procedure": "hcg_node2vec_walk_py",
            "message": str(exc),
            "elapsed_seconds": time.time() - started,
        }
        return (True, json.dumps(response, ensure_ascii=False))
    finally:
        try:
            txn.Abort()
        except Exception:
            pass
