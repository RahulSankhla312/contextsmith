# ContextSmith

**The best code context per token for coding agents.**

ContextSmith indexes your repository into a code graph, full-text indexes and git history,
then answers one question better than anything else: *given this task and a token budget,
what code should the agent read?* It runs locally, needs no API keys, and plugs into any
agent over MCP (Claude Code, Cursor, Codex, Windsurf, …).

```bash
pip install contextsmith        # or: pipx install contextsmith
ctxsmith index .
ctxsmith context "Coupon discounts are applied twice at checkout" --budget 4000
```

## Why another code-context tool?

Graphify, codebase-memory-mcp, GitNexus and Serena build excellent code graphs. What none of
them do:

| | ContextSmith |
|---|---|
| **Token budgets** — "the best context for this task in N tokens" | ✅ A budgeted packer: full bodies for the top hits, outlines for breadth, never over budget |
| **A reproducible benchmark on public data** | ✅ `ctxsmith bench` — SWE-bench Lite file localisation, baselines and ablations included |
| **Git co-change** — files that change together, even with no import between them | ✅ A ranking signal, plus `related` |
| **Commit history search** — "why was this added?" | ✅ Commit messages are indexed per file |
| **Team notes pinned to code** | ✅ `note add` / MCP `add_note`; notes surface in context |
| Commercial-friendly licence | ✅ MIT |

## How it ranks

Seven signals, fused with reciprocal-rank fusion so no single noisy signal dominates:

1. BM25 over whole files
2. BM25 over symbols (names, signatures, docstrings), with `camelCase`/`snake_case` splitting
3. BM25 over each file's commit history
4. Paths mentioned in the task (tracebacks)
5. Call/import graph neighbours of the best hits
6. Files that historically change together with the best hits
7. PageRank over the file graph, as a gentle prior

Then the packer solves a small knapsack: each candidate (function body, class outline, file
outline) has a value from the ranking and a cost in tokens; it repeatedly takes the best value
per token, discounting repeated snippets from one file, and trims to the exact budget.

## Benchmark

<!-- BENCHMARK -->

Reproduce: `ctxsmith bench --repos pytest-dev/pytest,psf/requests,pallets/flask`.

## Use it from your agent (MCP)

**Claude Code**

```bash
claude mcp add contextsmith -- ctxsmith serve --path /path/to/repo
```

**Cursor / Windsurf / any MCP client** (`mcp.json`):

```json
{
  "mcpServers": {
    "contextsmith": { "command": "ctxsmith", "args": ["serve", "--path", "/path/to/repo"] }
  }
}
```

Tools: `get_context(task, budget_tokens)`, `search`, `find_symbol`, `callers`, `callees`,
`impact`, `related_files`, `add_note`, `overview`, `reindex`.

## CLI

| Command | What it does |
|---|---|
| `ctxsmith index [PATH]` | Index (incremental: only changed files are re-parsed) |
| `ctxsmith context "task" -b 4000` | Best context within a token budget |
| `ctxsmith rank "task"` | Ranked files, with the signals that found each |
| `ctxsmith search "query"` | Ranked functions/classes |
| `ctxsmith symbol / callers / callees NAME` | Navigate the call graph |
| `ctxsmith impact NAME` | What could break if NAME changes |
| `ctxsmith related FILE` | Files linked by code, and files that change together |
| `ctxsmith note add "text" --file F` | Remember a decision or gotcha |
| `ctxsmith overview` | Languages, size, central and most-changed files |
| `ctxsmith serve` | MCP server over stdio |
| `ctxsmith bench` | SWE-bench Lite benchmark |

## Python API

```python
from contextsmith import Engine

eng = Engine("path/to/repo")
eng.index()
pack = eng.context("Fix the race when two users book the last seat", budget=6000)
print(pack.text, pack.tokens)
eng.impact("reserve_seat")
```

## Languages

Python, JavaScript, TypeScript/TSX, Java, Go and Rust — parsed with tree-sitter.

## Status and roadmap

v0.1 — see [PLAN.md](PLAN.md): optional local embeddings, note staleness tracking, file
watching, multi-repo, a graph UI and a PR impact report are next.

## Licence

MIT
