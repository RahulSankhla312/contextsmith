"""SWE-bench Lite file-localisation benchmark.

For every issue: check out the repository at the issue's base commit, index it, query
with the issue text, and check whether the files changed by the real fix are found —
in the top k results, and inside a fixed token budget.

The baseline is BM25 over whole files, and its budgeted variant pastes whole files until
the budget runs out — what "search the repo and paste files" agents do today.

Two budgeted measures: `budget_recall` — is each file the fix changed in the context at all;
`hunk_recall` — is the code each hunk of the fix changes actually shown (a stricter test of
whether the agent sees the lines it must edit, not just a file outline).
"""

from __future__ import annotations

import json
import re
import statistics
import subprocess
import time
import urllib.request
from pathlib import Path

from contextsmith.engine import Engine
from contextsmith.rank import rank
from contextsmith.text import count_tokens

CACHE = Path.home() / ".cache" / "contextsmith"
DATASET_URL = (
    "https://datasets-server.huggingface.co/rows?dataset=princeton-nlp%2FSWE-bench_Lite"
    "&config=default&split=test&offset={offset}&length=100"
)
KS = (1, 3, 5, 10)
BUDGETS = (4000, 8000)

LEXICAL_OFF = {"symbol_bm25": 0, "symbol_mention": 0, "history": 0, "path_mention": 0, "graph": 0,
               "cochange": 0, "pagerank": 0}
STRATEGIES: dict[str, dict] = {
    "bm25_files": {**LEXICAL_OFF, "semantic": 0},
    # What you get without the semantic extra: the same ranker, embeddings off.
    "lexical": {"semantic": 0},
    "semantic_only": {**LEXICAL_OFF, "file_bm25": 0, "semantic": 1.0},
    "contextsmith": {},
    "contextsmith+rerank": {"_rerank": True},
    "no_git": {"history": 0, "cochange": 0},
}


def load_dataset() -> list[dict]:
    CACHE.mkdir(parents=True, exist_ok=True)
    cached = CACHE / "swebench_lite.json"
    if cached.exists():
        return json.loads(cached.read_text(encoding="utf-8"))
    rows: list[dict] = []
    for offset in range(0, 400, 100):
        with urllib.request.urlopen(DATASET_URL.format(offset=offset), timeout=60) as resp:
            page = json.load(resp)
        batch = [r["row"] for r in page.get("rows", [])]
        rows.extend(batch)
        if len(batch) < 100:
            break
    cached.write_text(json.dumps(rows), encoding="utf-8")
    return rows


def gold_files(patch: str) -> list[str]:
    return sorted(set(re.findall(r"^diff --git a/(\S+) b/", patch, re.M)))


def gold_hunks(patch: str) -> list[tuple[str, set[int]]]:
    """For each hunk of the fix: its file and the pre-fix line numbers it touches.

    Removed lines count as themselves; a pure insertion counts as the lines around it.
    """
    hunks: list[tuple[str, set[int]]] = []
    path, old, prev = "", 0, ""
    for line in patch.splitlines():
        kind, prev = prev, line[:1]
        if line.startswith("diff --git"):
            m = re.match(r"diff --git a/(\S+) b/", line)
            path = m.group(1) if m else ""
        elif line.startswith("@@"):
            m = re.match(r"@@ -(\d+)", line)
            old = int(m.group(1)) if m else 0
            hunks.append((path, set()))
        elif not hunks or line.startswith(("---", "+++")):
            continue
        elif line.startswith("-"):
            hunks[-1][1].add(old)
            old += 1
        elif line.startswith("+"):
            if kind not in ("-", "+"):  # an insertion, not the new side of a replacement
                hunks[-1][1].update((max(old - 1, 1), old))
        else:
            old += 1
    return [h for h in hunks if h[1]]


def hunk_recall(hunks: list[tuple[str, set[int]]], spans: list[tuple[str, int, int]]) -> float:
    shown = sum(any(p == path and any(a <= ln <= b for ln in lines) for p, a, b in spans)
                for path, lines in hunks)
    return shown / len(hunks) if hunks else 0.0


def _git(cwd: Path, *args: str, attempts: int = 3) -> None:
    """Run git, retrying: on a long benchmark a transient failure must not end the run."""
    for i in range(attempts):
        try:
            subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)
            return
        except subprocess.CalledProcessError:
            if i == attempts - 1:
                raise
            time.sleep(2 * (i + 1))


def checkout(repo: str, commit: str) -> Path:
    path = CACHE / "repos" / repo.replace("/", "__")
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", "--quiet", f"https://github.com/{repo}.git", str(path)], check=True)
    try:
        _git(path, "checkout", "--quiet", "-f", commit)
    except subprocess.CalledProcessError:
        _git(path, "fetch", "--quiet", "origin")
        _git(path, "checkout", "--quiet", "-f", commit)
    _git(path, "clean", "-fdq")
    return path


def _whole_files_within(root: Path, paths: list[str], budget: int) -> list[str]:
    used, out = 0, []
    for p in paths:
        try:
            cost = count_tokens((root / p).read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        if used + cost > budget:
            continue
        used += cost
        out.append(p)
    return out


def evaluate(instance: dict, semantic: bool = True) -> dict:
    root = checkout(instance["repo"], instance["base_commit"])
    eng = Engine(root, db_path=CACHE / "index" / f"{instance['repo'].replace('/', '__')}.db")
    t0 = time.perf_counter()
    eng.index(semantic=semantic)
    index_s = time.perf_counter() - t0
    gold = gold_files(instance["patch"])
    hunks = gold_hunks(instance["patch"])
    task = instance["problem_statement"]
    result = {"id": instance["instance_id"], "repo": instance["repo"], "gold": gold,
              "index_s": round(index_s, 2), "strategies": {}}
    for name, strategy in STRATEGIES.items():
        weights = {k: v for k, v in strategy.items() if not k.startswith("_")}
        if not semantic and (name.startswith("semantic") or "rerank" in name):
            continue
        t0 = time.perf_counter()
        opts = {"weights": weights, "rerank": bool(strategy.get("_rerank")), "rrf_k": strategy.get("_rrf_k")}
        ranking = rank(eng.conn, task, limit_files=50, **opts)
        query_ms = (time.perf_counter() - t0) * 1000
        files = [f.path for f in ranking.files]
        r = {"query_ms": round(query_ms, 1), "top": files[:10]}
        for k in KS:
            r[f"recall@{k}"] = len(set(files[:k]) & set(gold)) / len(gold)
        for b in BUDGETS:
            if name == "bm25_files":
                inside = _whole_files_within(root, files, b)
                spans = [(p, 1, 10**9) for p in inside]  # whole files show every line
            elif name in ("lexical", "contextsmith"):
                pack = eng.context(task, budget=b, **opts)
                inside, spans = pack.files, pack.spans
            else:
                continue
            r[f"budget_recall@{b}"] = len(set(inside) & set(gold)) / len(gold)
            r[f"hunk_recall@{b}"] = hunk_recall(hunks, spans)
        result["strategies"][name] = r
    eng.close()
    return result


def summarize(results: list[dict]) -> str:
    names = list(STRATEGIES)
    cols = ([f"recall@{k}" for k in KS] + [f"budget_recall@{b}" for b in BUDGETS]
            + [f"hunk_recall@{b}" for b in BUDGETS])
    lines = [
        f"SWE-bench Lite file localisation · {len(results)} issues · "
        f"repos: {', '.join(sorted({r['repo'] for r in results}))}",
        "",
        "| strategy | " + " | ".join(cols) + " | query ms |",
        "|---|" + "---|" * (len(cols) + 1),
    ]
    for n in names:
        vals = []
        for c in cols:
            xs = [r["strategies"][n][c] for r in results if n in r["strategies"] and c in r["strategies"][n]]
            vals.append(f"{100 * statistics.mean(xs):.1f}%" if xs else "–")
        times = [r["strategies"][n]["query_ms"] for r in results if n in r["strategies"]]
        if not times:
            continue
        ms = statistics.median(times)
        lines.append(f"| {n} | " + " | ".join(vals) + f" | {ms:.0f} |")
    idx = statistics.median(r["index_s"] for r in results)
    lines += ["", f"Median index time per checkout (incremental after the first): {idx:.2f}s"]
    return "\n".join(lines)


def run(repos: list[str], limit: int = 0, out_dir: str = "bench/results", semantic: bool = True) -> list[dict]:
    data = [r for r in load_dataset() if r["repo"] in repos]
    if limit:
        data = data[:limit]
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    # Every result is appended as it is scored, so an interrupted run resumes where it stopped.
    log = out / "results.jsonl"
    lines = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
    results = [json.loads(ln) for ln in lines if ln.strip()]
    done = {r["id"] for r in results}
    for i, inst in enumerate(data, 1):
        if inst["instance_id"] in done:
            continue
        res = evaluate(inst, semantic=semantic)
        results.append(res)
        with log.open("a", encoding="utf-8") as f:
            f.write(json.dumps(res) + "\n")
        cs = res["strategies"]["contextsmith"]
        bm = res["strategies"]["bm25_files"]
        print(f"[{i}/{len(data)}] {inst['instance_id']}: contextsmith R@5={cs['recall@5']:.2f} "
              f"bm25 R@5={bm['recall@5']:.2f}", flush=True)
    (out / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    summary = summarize(results)
    (out / "summary.md").write_text(summary + "\n", encoding="utf-8")
    print("\n" + summary)
    return results
