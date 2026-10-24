"""Grid-search ranking weights on a tuning set; report the best few.

Usage: python bench/tune.py pytest-dev/pytest,psf/requests,pallets/flask
Each issue is checked out and indexed once; every weight combination is then scored
against it (ranking takes milliseconds), so the whole grid costs little more than one run.
"""

from __future__ import annotations

import itertools
import statistics
import sys

from contextsmith.bench import CACHE, checkout, gold_files, load_dataset
from contextsmith.engine import Engine
from contextsmith.rank import rank

GRID = {
    "symbol_bm25": [0.0, 0.5, 1.0],
    "symbol_mention": [0.0, 0.3, 0.7],
    "history": [0.0, 0.5],
    "graph": [0.0, 0.2],
    "cochange": [0.0, 0.3],
    "pagerank": [0.0, 0.05],
    "file_bm25": [1.0, 1.5],
}


def objective(files: list[str], gold: list[str]) -> float:
    """Mean of recall@1, @3 and @5: rewards getting the right file near the top."""
    return statistics.mean(len(set(files[:k]) & set(gold)) / len(gold) for k in (1, 3, 5))


def main(repos: list[str]) -> None:
    data = [r for r in load_dataset() if r["repo"] in repos]
    keys = list(GRID)
    combos = [dict(zip(keys, vals, strict=True)) for vals in itertools.product(*GRID.values())]
    totals = [0.0] * len(combos)
    for inst in data:
        root = checkout(inst["repo"], inst["base_commit"])
        eng = Engine(root, db_path=CACHE / "index" / f"{inst['repo'].replace('/', '__')}.db")
        eng.index()
        gold = gold_files(inst["patch"])
        for i, w in enumerate(combos):
            files = [f.path for f in rank(eng.conn, inst["problem_statement"], weights=w, limit_files=10).files]
            totals[i] += objective(files, gold)
        eng.close()
        print(f"scored {inst['instance_id']}", flush=True)
    best = sorted(range(len(combos)), key=lambda i: -totals[i])[:8]
    print("\nbest weight sets (objective = mean recall@1,3,5):")
    for i in best:
        print(f"{totals[i] / len(data):.3f}  {combos[i]}")


if __name__ == "__main__":
    main(sys.argv[1].split(","))
