# TCG D64-Capped Size Estimation Report

## Edge Counts by Relation Type (Full Scan)

| Relation | Count |
| --- | ---: |
| CR | 346,014 |
| PR | 37,965,114 |
| DHR | 54,938,804 |
| SHR | 40,990,482 |
| Total | 134,240,414 |

## Vertex Statistics

- Unique source vertices: 3,410,883
- Unique destination vertices: 3,476,117
- Unique vertices (union): 3,536,188

## Degree Distributions

### Source Out-Degree

| Percentile | Value |
| --- | ---: |
| p50 | 21 |
| p90 | 93 |
| p95 | 139 |
| p99 | 284 |
| max | 720 |

### Destination In-Degree

| Percentile | Value |
| --- | ---: |
| p50 | 23 |
| p90 | 89 |
| p95 | 129 |
| p99 | 251 |
| max | 690 |

## Capped Estimates

### K=5

- Predecessor-capped edges: 16,175,961
- Successor-capped edges: 15,514,918
- Union upper bound: 16,175,961
- Union estimate: 15,845,439
- Estimated CSV input: 2.21 GB
- Estimated TuGraph data: 4.43 GB
- Estimated walk file: 1.0 GB
- Estimated embedding parquet: 873.36 MB
- Total peak: ~8.5 GB
- **Verdict: CAUTION - feasible with 20.4GB free**

### K=10

- Predecessor-capped edges: 29,804,719
- Successor-capped edges: 28,268,074
- Union upper bound: 29,804,719
- Union estimate: 29,036,396
- Estimated CSV input: 4.06 GB
- Estimated TuGraph data: 8.11 GB
- Estimated walk file: 1.0 GB
- Estimated embedding parquet: 873.36 MB
- Total peak: ~14.0 GB
- **Verdict: CAUTION - marginal with 20.4GB free, requires cleanup first**

### K=20

- Predecessor-capped edges: 51,681,246
- Successor-capped edges: 48,672,709
- Union upper bound: 51,681,246
- Union estimate: 50,176,977
- Estimated CSV input: 7.01 GB
- Estimated TuGraph data: 14.02 GB
- Estimated walk file: 1.0 GB
- Estimated embedding parquet: 873.36 MB
- Total peak: ~22.9 GB
- **Verdict: NOT FEASIBLE - 22.9GB needed, 20.4GB free**

## Disk Space

- Free: 20.38 GB

## Recommendation

- K=5: Feasible. Can proceed after D64-light completes.
- K=10: Marginal. Would need to clean temp files first.
- K=20: Not feasible without additional disk space.
