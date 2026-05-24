#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TUGRAPH_INCLUDE="${TUGRAPH_INCLUDE:-/home/marktom/tugraph/tugraph-db/include}"
TUGRAPH_LIBLGRAPH="${TUGRAPH_LIBLGRAPH:-/home/marktom/tugraph/tugraph-db/build/output/liblgraph.so}"
OUT_DIR="${ROOT_DIR}/build/tugraph_cpp_plugins_host"

mkdir -p "${OUT_DIR}"

LINK_ARGS=()
if [[ -f "${TUGRAPH_LIBLGRAPH}" ]]; then
  LINK_ARGS+=("${TUGRAPH_LIBLGRAPH}")
else
  echo "Warning: ${TUGRAPH_LIBLGRAPH} not found; building host ABI-check .so without linking liblgraph.so."
fi

g++ -fno-gnu-unique -fPIC --std=c++17 -rdynamic -O3 -fopenmp -DNDEBUG -shared \
  -D_GLIBCXX_USE_CXX11_ABI=1 \
  -include optional -include any \
  -I"${ROOT_DIR}/build/tugraph_stub_include" \
  -I"${TUGRAPH_INCLUDE}" \
  "${ROOT_DIR}/procedures/hcg_weighted_walk_v1.cpp" \
  "${LINK_ARGS[@]}" \
  -o "${OUT_DIR}/hcg_weighted_walk_v1.so"

ls -lh "${OUT_DIR}/"*.so

echo
echo "ABI check:"
for so in "${OUT_DIR}/"*.so; do
  echo "--- ${so}"
  objdump -T "${so}" | grep -E 'GLIBCXX_|GLIBC_' | sort -u | tail -n 20 || true
done

echo
echo "Warning: these host-built .so files may not load in the CentOS 7 TuGraph container if they require newer GLIBC/GLIBCXX symbols."
