#!/usr/bin/env bash
set -euo pipefail

CONTAINER_NAME="${CONTAINER_NAME:-tugraph-db}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REMOTE_DIR="/tmp/hcg_cpp_build"
OUT_DIR="${ROOT_DIR}/build/tugraph_cpp_plugins"

mkdir -p "${OUT_DIR}"

docker exec "${CONTAINER_NAME}" sh -lc "rm -rf '${REMOTE_DIR}' && mkdir -p '${REMOTE_DIR}/procedures' '${REMOTE_DIR}/stub_include/tools' '${REMOTE_DIR}/stub_include/boost/algorithm' '${REMOTE_DIR}/stub_include/lgraph' '${REMOTE_DIR}/out'"

docker cp "${ROOT_DIR}/procedures/hcg_weighted_walk_v1.cpp" "${CONTAINER_NAME}:${REMOTE_DIR}/procedures/hcg_weighted_walk_v1.cpp"
docker cp "${ROOT_DIR}/build/tugraph_stub_include/tools/lgraph_log.h" "${CONTAINER_NAME}:${REMOTE_DIR}/stub_include/tools/lgraph_log.h"
docker cp "${ROOT_DIR}/build/tugraph_stub_include/boost/algorithm/hex.hpp" "${CONTAINER_NAME}:${REMOTE_DIR}/stub_include/boost/algorithm/hex.hpp"
docker cp "${ROOT_DIR}/build/tugraph_stub_include/lgraph/lgraph_spatial.h" "${CONTAINER_NAME}:${REMOTE_DIR}/stub_include/lgraph/lgraph_spatial.h"

docker exec "${CONTAINER_NAME}" sh -lc "cd '${REMOTE_DIR}' && \
  g++ -fno-gnu-unique -fPIC --std=c++17 -rdynamic -O3 -fopenmp -DNDEBUG -shared \
    -D_GLIBCXX_USE_CXX11_ABI=1 -Istub_include -I/usr/local/include \
    procedures/hcg_weighted_walk_v1.cpp /usr/local/lib64/lgraph/liblgraph.so \
    -o out/hcg_weighted_walk_v1.so && \
  ls -lh out/*.so"

docker cp "${CONTAINER_NAME}:${REMOTE_DIR}/out/hcg_weighted_walk_v1.so" "${OUT_DIR}/hcg_weighted_walk_v1.so"

ls -lh "${OUT_DIR}/"*.so
