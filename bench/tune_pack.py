"""Grid-search how snippets are scored and packed, for hunk recall within a budget.

Usage: python bench/tune_pack.py pytest-dev/pytest,psf/requests,pallets/flask
File ranking is fixed (tune.py chose it); this only changes which functions and outlines
fill the budget, scored by how many hunks of the real fix end up shown in full.
"""

from __future__ import annotations

import itertools
import sys

from contextsmith import pack, rank
from contextsmith.bench import BUDGETS, CACHE, checkout, gold_hunks, hunk_recall, load_dataset
from contextsmith.engine import Engine

RANK_GRID = {"SYMBOL_K": [1.0, 5.0, 20.0], "SYMBOL_FLOOR": [0.2, 0.5], "FILE_POWER": [1.0, 2.0],
             "LIMIT_SYMBOLS": [60, 150]}
PACK_GRID = {"COST_EXPONENT": [0.3, 0.5, 0.7], "MIN_TOKENS": [0, 100], "SAME_FILE_DISCOUNT": [0.7, 0.9]}


def combos(grid: dict) -> list[dict]:
    return [dict(zip(grid, vals, strict=True)) for vals in itertools.product(*grid.values())]


def apply(params: dict) -> None:
    for k, v in params.items():
        setattr(rank if hasattr(rank, k) else pack, k, v)


def main(repos: list[str]) -> None:
    data = [r for r in load_dataset() if r["repo"] in repos]
    grid = [(a, b) for a in combos(RANK_GRID) for b in combos(PACK_GRID)]
    totals = [0.0] * len(grid)
    for inst in data:
        root = checkout(inst["repo"], inst["base_commit"])
        eng = Engine(root, db_path=CACHE / "index" / f"{inst['repo'].replace('/', '__')}.db")
        eng.index(semantic=True)
        hunks = gold_hunks(inst["patch"])
        rankings = {}
        for i, (rp, pp) in enumerate(grid):
            key = tuple(rp.items())
            if key not in rankings:
                apply(rp)
                rankings[key] = eng.rank(inst["problem_statement"])
            apply(pp)
            for b in BUDGETS:
                built = pack.build(eng.conn, eng.root, rankings[key], b, inst["problem_statement"])
                totals[i] += hunk_recall(hunks, built.spans) / len(BUDGETS)
        eng.close()
        print(f"scored {inst['instance_id']}", flush=True)
    best = sorted(range(len(grid)), key=lambda i: -totals[i])[:10]
    print(f"\nmean hunk recall over budgets {BUDGETS}:")
    for i in best:
        print(f"{totals[i] / len(data):.3f}  {grid[i][0]} {grid[i][1]}")


if __name__ == "__main__":
    main(sys.argv[1].split(","))
