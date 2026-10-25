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

RANK_GRID = {"SYMBOL_K": [8.0, 20.0, 50.0], "SYMBOL_FLOOR": [0.0, 0.2], "FILE_POWER": [1.0],
             "LIMIT_SYMBOLS": [150, 300]}
PACK_GRID = {"COST_EXPONENT": [0.1, 0.2, 0.3], "MIN_TOKENS": [100, 250]}
PER_REPO = 6  # issues per repository: packing is slower to score than ranking


def combos(grid: dict) -> list[dict]:
    return [dict(zip(grid, vals, strict=True)) for vals in itertools.product(*grid.values())]


def apply(params: dict) -> None:
    for k, v in params.items():
        setattr(rank if hasattr(rank, k) else pack, k, v)


def main(repos: list[str]) -> None:
    data = [r for repo in repos for r in [x for x in load_dataset() if x["repo"] == repo][:PER_REPO]]
    grid = [(a, b) for a in combos(RANK_GRID) for b in combos(PACK_GRID)]
    defaults = ({k: getattr(rank, k) for k in RANK_GRID}, {k: getattr(pack, k) for k in PACK_GRID})
    grid.append(defaults)  # reference: the constants as they are now
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
    print(f"\ncurrent defaults: {totals[-1] / len(data):.3f}  {grid[-1]}")
    best = sorted(range(len(grid)), key=lambda i: -totals[i])[:10]
    print(f"\nmean hunk recall over budgets {BUDGETS}:")
    for i in best:
        print(f"{totals[i] / len(data):.3f}  {grid[i][0]} {grid[i][1]}")


if __name__ == "__main__":
    main(sys.argv[1].split(","))
