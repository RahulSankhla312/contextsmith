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
| **Git co-change** — files that change together, even with no import between them | ✅ A ranking signal (removing git costs 8 points of recall@1 on unseen repos), plus `related` |
| **Commit history search** — "why was this added?" | ✅ Commit messages are indexed per file |
| **Team notes pinned to code** | ✅ `note add` / MCP `add_note`; notes surface in context |
| Commercial-friendly licence | ✅ MIT |

## How it ranks

Files are ranked by fusing several signals with reciprocal-rank fusion, so no single noisy
signal dominates:

1. BM25 over whole files (paths weighted above bodies), with `camelCase`/`snake_case` splitting
2. Paths named in the task (tracebacks, "in foo/bar.py")
3. Names the task mentions exactly (`Config.from_file`), weighted by how few files define them
4. BM25 over each file's commit history
5. Files that historically change together with the best hits

Call-graph neighbours, PageRank and symbol-level BM25 are available as extra signals, but the
benchmark showed they favour hub files when ranking *files*, so they are off by default.
Symbol-level BM25 still decides which functions go into the pack, and the call graph powers
`callers`, `callees` and `impact`. Weights come from `bench/tune.py`, checked on held-out repos.

Then the packer solves a small knapsack: each candidate (function body, class outline, file
outline) has a value from the ranking and a cost in tokens; it repeatedly takes the best value
per token, discounting repeated snippets from one file, and trims to the exact budget.

## Benchmark

Task: given a real GitHub issue from [SWE-bench Lite](https://www.swebench.com/), find the files
its real fix changed — checked out at the issue's own commit, so no future code or history leaks in.

**Held-out repositories** (never used for tuning):

SWE-bench Lite file localisation · 37 issues · repos: astropy/astropy, mwaskom/seaborn, pydata/xarray, pylint-dev/pylint, sphinx-doc/sphinx

| strategy | recall@1 | recall@3 | recall@5 | recall@10 | budget_recall@4000 | budget_recall@8000 | query ms |
|---|---|---|---|---|---|---|---|
| bm25_files | 43.2% | 56.8% | 70.3% | 81.1% | 29.7% | 37.8% | 27 |
| contextsmith | 35.1% | 56.8% | 75.7% | 83.8% | 78.4% | 86.5% | 33 |
| no_git | 27.0% | 51.4% | 67.6% | 89.2% | – | – | 28 |
| no_mentions | 35.1% | 56.8% | 75.7% | 83.8% | – | – | 30 |
| with_graph | 35.1% | 56.8% | 73.0% | 83.8% | – | – | 34 |

Median index time per checkout (incremental after the first): 3.24s

**Tuning repositories** (weights chosen here with `bench/tune.py`):

SWE-bench Lite file localisation · 26 issues · repos: pallets/flask, psf/requests, pytest-dev/pytest

| strategy | recall@1 | recall@3 | recall@5 | recall@10 | budget_recall@4000 | budget_recall@8000 | query ms |
|---|---|---|---|---|---|---|---|
| bm25_files | 42.3% | 61.5% | 73.1% | 76.9% | 19.2% | 42.3% | 20 |
| contextsmith | 42.3% | 69.2% | 80.8% | 80.8% | 76.9% | 84.6% | 22 |
| no_git | 42.3% | 53.8% | 76.9% | 80.8% | – | – | 20 |
| no_mentions | 30.8% | 61.5% | 73.1% | 80.8% | – | – | 21 |
| with_graph | 38.5% | 65.4% | 80.8% | 80.8% | – | – | 22 |

Median index time per checkout (incremental after the first): 1.46s

What this shows:
- **Per token, it is far better.** With the same budget, the files the fix needs are in the
  agent's context **2.6–4x more often** than pasting whole BM25-ranked files (78% vs 30% at
  4k tokens on unseen repositories).
- **Ranking:** better than BM25 at recall@5 and @10 on unseen repositories; **recall@1 is still
  behind BM25 there** (35% vs 43%) — the next thing to fix (see the roadmap).
- **Git history earns its place:** removing it costs 8 points of recall@1 on unseen code.
- Index once in seconds, then each query takes ~30 ms; re-indexing a new commit is incremental.

These are 63 issues — enough to see the direction, not to claim precision. Reproduce:
`ctxsmith bench --repos sphinx-doc/sphinx,pylint-dev/pylint,pydata/xarray,astropy/astropy,mwaskom/seaborn`.

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

v0.1 — see [PLAN.md](PLAN.md). Next: close the recall@1 gap (a cross-encoder or embedding
re-rank of the top 20), note staleness tracking, file watching, multi-repo, a graph UI and a
PR impact report.

## Licence

MIT
