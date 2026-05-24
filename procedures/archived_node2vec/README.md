# Archived Procedures

This directory contains procedures that are kept for reference only.

## hcg_node2vec_walk_v2_unusable.cpp

Do not upload or execute this C++ node2vec procedure in the current TuGraph
4.5.2 runtime. It can compile and may write partial walk files, but procedure
calls crash the TuGraph server or plugin runner during return/cleanup.

The active HCG node2vec walk generator is:

```text
procedures/hcg_node2vec_walk_py.py
```

