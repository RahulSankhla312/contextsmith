"""Grid-search ranking weights on a tuning set; report the best few.

Usage: python bench/tune.py pytest-dev/pytest,psf/requests,pallets/flask
Each issue is checked out and indexed once; every weight combination is then scored
against it (ranking takes milliseconds), so the whole grid costs little more than one run.
"""

from __future__ import annotations

import itertools
import sys

from contextsmith.bench import CACHE, checkout, gold_files, load_dataset
from contextsmith.engine import Engine
from contextsmith.rank import rank

GRID = {
    "rrf_k": [8, 15, 30],
    "file_bm25": [0.75, 1.0],
    "semantic": [1.5, 2.0, 3.0],
    "symbol_mention": [0.0],
    "history": [0.25, 0.5, 1.0],
    "cochange": [0.0, 0.15],
    "path_mention": [2.0],
    "symbol_bm25": [0.0],
    "graph": [0.0],
    "pagerank": [0.0],
}


def objective(files: list[str], gold: list[str]) -> float:
    """Weighted recall@1, @3, @5: getting the right file first matters most."""
    r = [len(set(files[:k]) & set(gold)) / len(gold) for k in (1, 3, 5)]
    return 0.5 * r[0] + 0.25 * r[1] + 0.25 * r[2]


def main(repos: list[str]) -> None:
    data = [r for r in load_dataset() if r["repo"] in repos]
    keys = list(GRID)
    combos = [dict(zip(keys, vals, strict=True)) for vals in itertools.product(*GRID.values())]
    # Lexical reference: the v0.1 defaults, no embeddings.
    combos.append({"rrf_k": 60, "file_bm25": 1.0, "semantic": 0.0, "symbol_mention": 0.3, "history": 0.5,
                   "cochange": 0.3, "path_mention": 2.0, "symbol_bm25": 0.0, "graph": 0.0, "pagerank": 0.0})
    totals = [0.0] * len(combos)
    for inst in data:
        root = checkout(inst["repo"], inst["base_commit"])
        eng = Engine(root, db_path=CACHE / "index" / f"{inst['repo'].replace('/', '__')}.db")
        eng.index(semantic=True)
        gold = gold_files(inst["patch"])
        for i, w in enumerate(combos):
            ww = dict(w)
            k = int(ww.pop("rrf_k"))
            files = [f.path for f in rank(eng.conn, inst["problem_statement"], weights=ww, limit_files=10,
                                          rrf_k=k).files]
            totals[i] += objective(files, gold)
        eng.close()
        print(f"scored {inst['instance_id']}", flush=True)
    print(f"\nlexical reference (v0.1 defaults, no semantic): {totals[-1] / len(data):.3f}")
    best = sorted(range(len(combos)), key=lambda i: -totals[i])[:8]
    print("\nbest weight sets (objective = 0.5 R@1 + 0.25 R@3 + 0.25 R@5):")
    for i in best:
        print(f"{totals[i] / len(data):.3f}  {combos[i]}")


if __name__ == "__main__":
    main(sys.argv[1].split(","))
