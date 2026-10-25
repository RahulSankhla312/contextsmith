<div align="center">

# ContextSmith

**The best code context per token for coding agents.**

Hybrid retrieval (code graph + BM25 + local embeddings + git history) packed into a hard
token budget, served over MCP. Local, no API keys, MIT.

[![CI](https://github.com/RahulSankhla312/contextsmith/actions/workflows/ci.yml/badge.svg)](https://github.com/RahulSankhla312/contextsmith/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.11%20|%203.12%20|%203.13-blue.svg)](https://github.com/RahulSankhla312/contextsmith/blob/main/pyproject.toml)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](https://github.com/RahulSankhla312/contextsmith/blob/main/LICENSE)

<img src="https://raw.githubusercontent.com/RahulSankhla312/contextsmith/main/docs/demo.gif" alt="ContextSmith indexing Flask, ranking files for a bug report, packing context into a token budget and printing the Claude Code setup" width="820">

</div>

Coding agents waste most of their context window on the wrong code: they grep, open whole
files, and run out of room before they reach the function that needs the fix. ContextSmith
answers one question as well as possible: **given this task and N tokens, what code should
the agent read?**

```bash
pipx install "contextsmith[semantic]"     # or: pip install "contextsmith[semantic]"
cd your-repo
ctxsmith index                             # seconds; incremental afterwards
ctxsmith context "Coupons are applied twice at checkout" --budget 4000
ctxsmith mcp-config claude                 # prints the one-line Claude Code setup
```

## Results

The test: take a real GitHub issue from [SWE-bench Lite](https://www.swebench.com/), check the
repository out at the issue's own commit (so no future code or history leaks in), give the
issue text to the tool, and check whether the code the real fix changed comes back.

**Final test on Django: 114 issues that no tuning step ever saw.**

| | BM25, whole files | **ContextSmith** |
|---|---|---|
| The fix's file is ranked 1st / in the top 3 / top 5 | 50.9% / 70.2% / 77.2% | **51.8% / 79.8% / 85.1%** |
| The fix's file is inside a **4,000-token** context | 28.9% | **92.1%** (3.2x) |
| The **exact lines the fix changes** are shown in 4,000 tokens | 28.9% | **48.1%** (1.7x) |
| Query time (median, laptop CPU, 2,800-file repository) | 145 ms | 238 ms |

The baseline pastes BM25-ranked files whole until the budget runs out, which is what
"search the repo and open files" agents do. ContextSmith spends the same tokens on the
functions that matter and outlines of the rest, so the right file almost always makes it in.

<details>
<summary>All strategies and ablations</summary>

| strategy | R@1 | R@3 | R@5 | R@10 | file in 4k | file in 8k | lines in 4k | lines in 8k | ms |
|---|---|---|---|---|---|---|---|---|---|
| BM25, whole files | 50.9 | 70.2 | 77.2 | 84.2 | 28.9 | 49.1 | 28.9 | 49.1 | 145 |
| lexical (no embeddings) | 48.2 | 74.6 | 78.9 | 86.0 | 86.0 | 89.5 | 42.3 | 46.2 | 145 |
| embeddings only | 48.2 | 69.3 | 78.9 | 86.8 | – | – | – | – | 249 |
| **ContextSmith (default)** | **51.8** | **79.8** | **85.1** | 88.6 | **92.1** | **96.5** | **48.1** | **50.7** | 238 |
| + cross-encoder re-rank | 34.2 | 73.7 | 81.6 | 91.2 | – | – | – | – | 1824 |
| without git history | 56.1 | 78.9 | 84.2 | 90.4 | – | – | – | – | 249 |

Full numbers: [bench/results-django/summary.md](https://github.com/RahulSankhla312/contextsmith/blob/main/bench/results-django/summary.md).

</details>

What the ablations say, including what didn't work:
- **Embeddings earn their place:** adding them to the lexical ranker lifts top-5 from 79% to
  85% and exact-line coverage from 42% to 48%.
- **The cross-encoder re-rank hurts** the top result (52% → 34%) at 8x the latency, so it is
  off by default and marked experimental. A general web-search re-ranker doesn't understand
  issue-to-code relevance; a code-trained one is on the roadmap.
- **Git commit history is mixed:** it helped on the tuning repositories, but on Django
  removing it *raises* recall@1 by 4 points. It stays on because the default was fixed before
  the Django run; changing it now would be tuning on the test set.
- At 8,000 tokens whole files catch up on exact lines (49% vs 51%): every Django fix here
  touches one file, and at that budget it often fits whole.

**Method.** Weights were chosen by grid search on 89 issues from 8 other repositories
(pytest, requests, flask, sphinx, pylint, xarray, astropy, seaborn) with
[`bench/tune.py`](https://github.com/RahulSankhla312/contextsmith/blob/main/bench/tune.py) and
[`bench/tune_pack.py`](https://github.com/RahulSankhla312/contextsmith/blob/main/bench/tune_pack.py),
then frozen before Django was run once. Reproduce it with
`ctxsmith bench --repos django/django` (first run: about two hours on a laptop).

## How it works

```mermaid
flowchart LR
    subgraph Index["ctxsmith index (incremental)"]
        TS["tree-sitter<br/>7 languages"] --> SYM["symbols · calls · imports"]
        SYM --> G["call graph<br/>PageRank"]
        SYM --> FTS["FTS5 BM25<br/>files · symbols · bodies"]
        SYM --> EMB["ONNX embeddings<br/>symbol summaries"]
        EMB --> VEC["sqlite-vec<br/>cosine index"]
        GIT["git log"] --> H["commit-message index<br/>co-change pairs"]
    end
    subgraph Query["get_context(task, budget)"]
        Q["task text"] --> S1["file BM25"] & S2["semantic kNN"] & S3["paths in task"] & S4["history BM25"]
        S1 & S2 & S3 & S4 --> RRF["reciprocal-rank<br/>fusion"]
        RRF --> KS["knapsack packer<br/>value per token"]
        KS --> OUT["≤ N tokens of code"]
    end
    Index -. one SQLite file .-> Query
```

**One SQLite file per repository** holds everything: files, symbols, call and import edges,
three FTS5 indexes, git statistics, team notes, and the vector index (a `vec0` virtual table
from [sqlite-vec](https://github.com/asg017/sqlite-vec); a numpy fallback runs where SQLite
can't load extensions).

**Retrieval (RAG).** Each signal produces its own ranked list of files; reciprocal-rank fusion
combines them, so no single noisy signal dominates:

| Signal | What it catches |
|---|---|
| BM25 over whole files (`camelCase`/`snake_case` split, paths weighted up) | exact vocabulary |
| Semantic kNN over symbol summaries (`BAAI/bge-small-en-v1.5`, ONNX, CPU) | the same idea in different words |
| Paths named in the task (tracebacks, "in `foo/bar.py`") | explicit pointers |
| BM25 over each file's commit messages | "this was touched for a similar bug before" |
| Co-change, call-graph neighbours, PageRank, exact-name mentions | available as weights; off by default because the benchmark showed they hurt *file* ranking |

The weights come from a grid search (`bench/tune.py`) on 89 SWE-bench Lite issues from 8
repositories and were then checked on Django, which tuning never saw.

**What gets embedded, and why.** Not whole files and not raw chunks: one short summary per
function or class — path, qualified name, signature, first docstring sentence. On a laptop
CPU this is ~30x cheaper than embedding bodies, and it is what identifies "which function is
this about". Vectors are cached by content hash, so a function that didn't change is never
embedded twice — across re-indexes and across git checkouts. Test files are skipped.

**Experimental re-rank.** `ctxsmith context --rerank` re-scores the top 20 files with a
cross-encoder (`ms-marco-MiniLM-L-6-v2`). It is off by default because the benchmark shows it
hurts (see Results).

**Packing.** Candidates are function bodies (matched by name, docstring and body text),
class outlines and file outlines. A greedy knapsack takes the best value per token,
discounts repeats from one file, and enforces the budget on the final rendered text, so the
answer is never over budget.

**Always fresh.** Re-indexing compares file size and mtime before reading anything, so an
unchanged repository re-indexes in milliseconds; the MCP server does this before answering,
so the agent never reads a stale index.

## Use it from your agent (MCP)

`ctxsmith mcp-config <client>` prints the exact snippet for your machine.

**Claude Code**

```bash
claude mcp add contextsmith -- ctxsmith serve --path /path/to/repo
```

**Cursor, Windsurf and other clients** (`mcp.json`):

```json
{
  "mcpServers": {
    "contextsmith": { "command": "ctxsmith", "args": ["serve", "--path", "/path/to/repo"] }
  }
}
```

**Codex** (`~/.codex/config.toml`):

```toml
[mcp_servers.contextsmith]
command = "ctxsmith"
args = ["serve", "--path", "/path/to/repo"]
```

| Tool | Returns |
|---|---|
| `get_context(task, budget_tokens)` | the best code for the task, packed to the budget |
| `search(query)` | ranked functions and classes |
| `find_symbol(name)` | where something is defined |
| `callers(name)` / `callees(name)` | one hop of the call graph |
| `impact(name)` | everything that transitively calls it: what a change could break |
| `related_files(path)` | files linked by code, and files that change together in git |
| `add_note(text, path, symbol)` | a decision or gotcha that later sessions should know |
| `overview()` | languages, size, central and most-changed files |
| `reindex()` | force an incremental re-index |

## CLI

| Command | What it does |
|---|---|
| `ctxsmith index [PATH] [--no-semantic]` | Index; incremental, embeddings on when the extra is installed |
| `ctxsmith context "task" -b 4000` | Best context within a token budget |
| `ctxsmith rank "task"` | Ranked files, with the signals that found each |
| `ctxsmith search "query"` | Ranked functions and classes |
| `ctxsmith symbol / callers / callees NAME` | Navigate the call graph (`--json` for scripts) |
| `ctxsmith impact NAME` | What could break if NAME changes |
| `ctxsmith related FILE` | Files linked by code, and files that change together |
| `ctxsmith note add "text" --file F` | Remember a decision or gotcha |
| `ctxsmith overview` | Languages, size, central and most-changed files, semantic status |
| `ctxsmith serve` | MCP server over stdio |
| `ctxsmith mcp-config [claude\|cursor\|codex]` | Setup snippet for your agent |
| `ctxsmith bench --repos django/django` | Run the SWE-bench Lite benchmark yourself |

## Python API

```python
from contextsmith import Engine

eng = Engine("path/to/repo")
eng.index()
pack = eng.context("Fix the race when two users book the last seat", budget=6000)
print(pack.text, pack.tokens, pack.files)
eng.impact("reserve_seat")
```

## Configuration

| Variable | Default |
|---|---|
| `CTXSMITH_EMBED_MODEL` | `BAAI/bge-small-en-v1.5` (any [fastembed](https://github.com/qdrant/fastembed) text model, e.g. `jinaai/jina-embeddings-v2-base-code`) |
| `CTXSMITH_RERANK_MODEL` | `Xenova/ms-marco-MiniLM-L-6-v2` |
| `FASTEMBED_CACHE_PATH` | `~/.cache/contextsmith/models` |

The index lives in `<repo>/.contextsmith/` (git-ignored automatically). Without the
`semantic` extra everything still works, lexically.

## Languages

Python, JavaScript, TypeScript/TSX, Java, Go and Rust, parsed with tree-sitter.

## How it compares

Graphify, codebase-memory-mcp, GitNexus, Serena and Claude Context are good tools; this is
where ContextSmith differs:

| | ContextSmith |
|---|---|
| Answers "the best context for this task **in N tokens**" | ✅ budgeted packer, never over budget |
| Published, reproducible benchmark with baselines and ablations | ✅ `ctxsmith bench`, held-out repositories |
| Lexical + semantic + git history, fused | ✅ |
| Fully local, no API keys, one SQLite file | ✅ |
| Team notes pinned to code, surfaced in context | ✅ |
| Commercial-friendly licence | ✅ MIT |

## Roadmap

Multi-repo indexes, note staleness tracking, a file watcher, a graph view, a PR impact
report, and more languages. Ideas and benchmark-backed pull requests are welcome: see
[CONTRIBUTING.md](https://github.com/RahulSankhla312/contextsmith/blob/main/CONTRIBUTING.md).

## Licence

MIT
