# TCG D64 Execution Plan

## Environment Summary

| Item | Value |
|------|-------|
| Git branch | master (clean, HEAD=e7e2a62) |
| Disk /home | 32GB free / 196GB (83% used) |
| TuGraph | Running, HTTP 7070 reachable |
| TCG flows | 3,577,296 |
| CR edges | 346,015 |
| PR edges | 37,965,152 |
| CR+PR total | 38,311,167 |
| Full TCG total | 134,240,549 |

## Risk: Disk Space

**32GB available** is below the 50GB safety threshold. Estimated peak additional usage for D64-light is ~10GB (import input + TuGraph data + walks + embeddings). This is feasible but tight. If TuGraph data directory grows beyond expectations, we will stop and report.

## Plan

### Phase 2: Script Implementation
Create 6 new scripts adapted from HCG versions:
1. `procedures/tcg_node2vec_walk_py_batch.py` - stored procedure
2. `scripts/run_tcg_node2vec_procedure_batch.py` - batch runner
3. `scripts/train_tcg_word2vec_embeddings.py` - Word2Vec trainer
4. `scripts/check_tcg_walks_file.py` - walk file validator
5. `scripts/build_tcg_classification_features.py` - D/E/F builder
6. `scripts/check_tcg_classification_features.py` - D/E/F validator

### Phase 3: D64-light Graph Construction
- Create `data/processed/tcg_light_crpr/` with CR+PR edges only
- Hardlink/copy from original TCG data
- Import as `tcg_light_crpr` graph in TuGraph

### Phase 4: Node2Vec Walks + Word2Vec
- Smoke test: 2 batches x 1000 start nodes
- Full run: 50000 batch size, walk_length=10, num_walks=2
- Train 64-dimensional Word2Vec embeddings

### Phase 5: D/E/F Dataset Construction
- D = TCG flow embedding only (64 dims + missing flag)
- E = A raw features + TCG embedding
- F = C (raw + HCG) + TCG embedding
- All aligned to A's record_id, target, split

### Phase 6: D64-capped Feasibility
- Estimate K=5 and K=10 capped edge counts using streaming
- Generate size estimation report
- Smoke test K=5 if feasible

### Phase 7: Reports
- Generate all report files
- Write experiment record document

## Constraints
- No modifications to raw data
- No overwriting HCG A/B/C datasets
- No full TCG Node2Vec (134M edges)
- No C++ stored procedures
- TCG vertices use `record_id` as primary key
- D/E/F must align with A's record_id, target, split (left join, no inner join)
- All scripts support --dry-run or smoke test
