"""SWE-bench Lite file-localisation benchmark.

For every issue: check out the repository at the issue's base commit, index it, query
with the issue text, and check whether the files changed by the real fix are found —
in the top k results, and inside a fixed token budget.

The baseline is BM25 over whole files, and its budgeted variant pastes whole files until
the budget runs out — what "search the repo and paste files" agents do today.
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

STRATEGIES: dict[str, dict[str, float]] = {
    "bm25_files": {"symbol_bm25": 0, "symbol_mention": 0, "history": 0, "path_mention": 0, "graph": 0,
                   "cochange": 0, "pagerank": 0},
    "contextsmith": {},
    "no_git": {"history": 0, "cochange": 0},
    "no_mentions": {"symbol_mention": 0, "path_mention": 0},
    "with_graph": {"graph": 0.2, "pagerank": 0.05},
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


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


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


def evaluate(instance: dict) -> dict:
    root = checkout(instance["repo"], instance["base_commit"])
    eng = Engine(root, db_path=CACHE / "index" / f"{instance['repo'].replace('/', '__')}.db")
    t0 = time.perf_counter()
    eng.index()
    index_s = time.perf_counter() - t0
    gold = gold_files(instance["patch"])
    task = instance["problem_statement"]
    result = {"id": instance["instance_id"], "repo": instance["repo"], "gold": gold,
              "index_s": round(index_s, 2), "strategies": {}}
    for name, weights in STRATEGIES.items():
        t0 = time.perf_counter()
        ranking = rank(eng.conn, task, weights=weights, limit_files=50)
        query_ms = (time.perf_counter() - t0) * 1000
        files = [f.path for f in ranking.files]
        r = {"query_ms": round(query_ms, 1), "top": files[:10]}
        for k in KS:
            r[f"recall@{k}"] = len(set(files[:k]) & set(gold)) / len(gold)
        for b in BUDGETS:
            if name == "bm25_files":
                inside = _whole_files_within(root, files, b)
            elif name == "contextsmith":
                inside = eng.context(task, budget=b).files
            else:
                continue
            r[f"budget_recall@{b}"] = len(set(inside) & set(gold)) / len(gold)
        result["strategies"][name] = r
    eng.close()
    return result


def summarize(results: list[dict]) -> str:
    names = list(STRATEGIES)
    cols = [f"recall@{k}" for k in KS] + [f"budget_recall@{b}" for b in BUDGETS]
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
            xs = [r["strategies"][n][c] for r in results if c in r["strategies"][n]]
            vals.append(f"{100 * statistics.mean(xs):.1f}%" if xs else "–")
        ms = statistics.median(r["strategies"][n]["query_ms"] for r in results)
        lines.append(f"| {n} | " + " | ".join(vals) + f" | {ms:.0f} |")
    idx = statistics.median(r["index_s"] for r in results)
    lines += ["", f"Median index time per checkout (incremental after the first): {idx:.2f}s"]
    return "\n".join(lines)


def run(repos: list[str], limit: int = 0, out_dir: str = "bench/results") -> list[dict]:
    data = [r for r in load_dataset() if r["repo"] in repos]
    if limit:
        data = data[:limit]
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    results = []
    for i, inst in enumerate(data, 1):
        res = evaluate(inst)
        results.append(res)
        cs = res["strategies"]["contextsmith"]
        bm = res["strategies"]["bm25_files"]
        print(f"[{i}/{len(data)}] {inst['instance_id']}: contextsmith R@5={cs['recall@5']:.2f} "
              f"bm25 R@5={bm['recall@5']:.2f}", flush=True)
    (out / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    summary = summarize(results)
    (out / "summary.md").write_text(summary + "\n", encoding="utf-8")
    print("\n" + summary)
    return results
