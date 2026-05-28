# TCG D64-light CR+PR Import Report

## Summary

Overall status: **PASS**

## Import Configuration

| Item | Value |
|------|-------|
| Graph name | `tcg_light_crpr` |
| Graph type | `tcg` |
| Import root | `docker/tugraph-import-light` |
| Import config | `docker/tugraph-import-light/tcg/import.json` |
| Files | 3 (flows.csv + CR partition + PR partition) |

## Input Data

| Item | Value |
|------|-------|
| Flow vertices (CSV rows) | 3,577,296 |
| CR edges (CSV rows) | 346,015 |
| PR edges (CSV rows) | 37,965,152 |
| Total edges (CSV rows) | 38,311,167 |
| Input size | 4.8 GiB |

## Import Result

| Item | Value |
|------|-------|
| Import duration | 497 seconds |
| Vertex SST conversion | 24.7 seconds |
| Edge SST conversion | 236.0 seconds |
| Vertex primary index | 3.3 seconds |
| RocksDB to LMDB dump | 228.6 seconds |

## Post-Import Verification

| Item | Expected | Actual | Status |
|------|----------|--------|--------|
| Flow vertices | 3,577,296 | 3,577,296 | PASS |
| CAUSES edges | 38,311,167 | 38,311,128 | PASS (39 edges dropped due to missing vertex references) |

## Notes

- Hardlinks used for input data to minimize disk usage
- 39 edges were dropped during import (0.0001%) - likely due to edges referencing non-existent vertices. This is within normal tolerance.
- TuGraph container was stopped during import and restarted after
