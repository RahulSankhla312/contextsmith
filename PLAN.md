# ContextSmith — plan

**One line:** the best context per token for coding agents — a local code-context engine
that combines a code graph, hybrid search, git history and team memory, and packs the most
useful context into a token budget you choose. Proven on a public benchmark, not claimed.

## 1. The market (October 2026)

| Tool | Stars | What it does well | Gap |
|---|---|---|---|
| Graphify (YC S26) | ~116k | Tree-sitter graph, 20+ assistants, PR triage | Headline "71.5x fewer tokens" measured at 7.3x independently; no budgeted context |
| codebase-memory-mcp | ~47k | Fast C binary, 162 languages, impact analysis, BM25 + embeddings | Memory is shallow; no token budget; no public retrieval benchmark |
| GitNexus (Akon Labs) | ~46k | KuzuDB graph, Cypher, multi-repo | PolyForm **Noncommercial** licence; no memory |
| Serena | ~24k | Precise LSP refs/renames, 40+ languages | Needs a language server per language; no ranking or memory |
| CodeAlmanac (Almanac, YC S26) | new | Agent-written wiki of decisions and invariants | macOS only; needs Codex/Claude Code; human review of facts |
| Claude Context | — | BM25 + vectors | Needs Milvus; no graph, impact or memory |
| Sverklo | — | Hybrid ranking + memory + a benchmark | Vendor-run benchmark; regex fallback for most languages |

What nobody does (per the comparisons above):
1. **Token budgeting.** No tool answers "the best context for this task in N tokens".
2. **A reproducible benchmark on public data.** Numbers are vendor-run and conflict.
3. **Git co-change** as a ranking signal (files that change together), and history search.
4. **Memory** that is local, cross-platform and tied to the code it describes.

## 2. What we build

```
repo ──► indexer ──► SQLite (files, symbols, edges, FTS5, git, notes)
                         │
 task ──► ranker ── BM25(symbols) + BM25(files) + BM25(commit history)
                    + call-graph expansion + co-change + PageRank prior
                    fused with reciprocal-rank fusion
                         │
           packer ── greedy knapsack: score ÷ tokens, file diversity,
                     signatures for breadth, full bodies for the top hits
                         │
         CLI  ·  MCP server (any agent)  ·  Python API
```

Components (each a module with one job):
- `languages` — extension → grammar, node types per language (Python, JS, TS, TSX, Java, Go, Rust).
- `parser` — tree-sitter → symbols (name, kind, lines, signature, docstring), raw calls, imports.
- `store` — SQLite schema, FTS5 tables, all queries.
- `indexer` — `git ls-files` walk, incremental by content hash, call resolution
  (same file → imported module → unique global name).
- `gitinfo` — `git log` → churn, recency, co-change pairs, commit messages per file.
- `rank` — hybrid retrieval and fusion; returns ranked files and symbols with reasons.
- `pack` — budgeted context packing; returns Markdown with paths and line ranges.
- `memory` — notes pinned to a path or symbol, plus searchable commit history.
- `mcp_server` — tools: `get_context`, `search`, `find_symbol`, `callers`, `callees`,
  `impact`, `related_files`, `add_note`, `overview`.
- `eval` — SWE-bench Lite file-localisation benchmark with baselines and ablations.

## 3. How we prove it

SWE-bench Lite gives a real GitHub issue and the files its real fix changed.
For each issue we check out the repo at the issue's base commit, index it, query with the
issue text and measure:

- **Recall@k** — share of the fixed files found in the top k (k = 1, 3, 5, 10).
- **Budgeted recall** — share of the fixed files present in a 4k / 8k-token context pack.
- **Index time** and **query time**.

Baselines: BM25 over whole files (what "search the repo" tools do). Ablations: without git,
without graph, without commit history — so every signal has to earn its place.

## 4. Milestones

| | Scope | Done when |
|---|---|---|
| v0.1 | Parser (7 languages), store, incremental indexer, git signals, hybrid ranker, packer, CLI, MCP server, tests | `ctxsmith index` + `ctxsmith context "task" --budget 4000` work on a real repo |
| v0.2 | SWE-bench Lite benchmark harness + first public results table vs BM25 baseline | Results in README, reproducible with one command |
| v0.3 | Optional local embeddings (ONNX) in the fusion; tuning from benchmark results | Beats v0.1 on the benchmark |
| v0.4 | Memory: notes pinned to code, staleness when the pinned code changes, decisions mined from commits | `add_note` / notes surface in context |
| v0.5 | File watcher, multi-repo, VS Code + Claude Code + Cursor setup guides, PyPI release | `pipx install contextsmith` |
| v1.0 | Graph UI, PR impact report in CI | Launch: HN, Reddit, LinkedIn |

## 5. Non-goals (for now)

- Competing on language count (codebase-memory-mcp has 162). Seven languages, done well.
- Hosting code anywhere. Everything runs locally; nothing leaves the machine.
- LLM calls inside the engine. Ranking and packing are deterministic and free.
