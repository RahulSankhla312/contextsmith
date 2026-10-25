# Changelog

## Unreleased

- `ctxsmith ... | head` exits quietly instead of printing a traceback (Windows).

## 0.1.0 — first release

- **Index:** tree-sitter parsing for Python, JavaScript, TypeScript/TSX, Java, Go and Rust;
  symbols, call graph, import graph and PageRank in one SQLite file.
- **Hybrid retrieval:** BM25 over files, symbols and commit history; exact-name and path
  mentions; git co-change; local embeddings (`contextsmith[semantic]`) stored in sqlite-vec;
  all fused with reciprocal-rank fusion. Experimental cross-encoder re-ranking (`--rerank`, off:
  it lowered recall@1 on the Django benchmark).
- **Token-budgeted packing:** `get_context(task, budget)` returns function bodies, class and
  file outlines chosen by value per token, never over budget.
- **Always fresh:** re-indexing checks file size and mtime first and re-parses only what
  changed (an unchanged 2,800-file repository: ~0.5 s); the MCP server refreshes before answering.
- **Memory:** team notes pinned to files and symbols, surfaced in context.
- **MCP server** with 10 tools; `ctxsmith mcp-config` prints the setup for Claude Code,
  Cursor, Windsurf and Codex.
- **Benchmark:** `ctxsmith bench` — SWE-bench Lite file localisation with baselines and
  ablations, including `hunk_recall` (are the lines the fix changes shown in full);
  `bench/tune.py` and `bench/tune_pack.py` for weight search on a separate tuning set.
  Held-out result on 114 Django issues: the fix's file is inside a 4,000-token context 92% of
  the time, against 29% for pasting BM25-ranked whole files; top-5 file recall 85% vs 77%.
