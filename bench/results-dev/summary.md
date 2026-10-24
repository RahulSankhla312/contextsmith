SWE-bench Lite file localisation · 26 issues · repos: pallets/flask, psf/requests, pytest-dev/pytest

| strategy | recall@1 | recall@3 | recall@5 | recall@10 | budget_recall@4000 | budget_recall@8000 | query ms |
|---|---|---|---|---|---|---|---|
| bm25_files | 42.3% | 61.5% | 73.1% | 76.9% | 19.2% | 42.3% | 20 |
| contextsmith | 42.3% | 69.2% | 80.8% | 80.8% | 76.9% | 84.6% | 22 |
| no_git | 42.3% | 53.8% | 76.9% | 80.8% | – | – | 20 |
| no_mentions | 30.8% | 61.5% | 73.1% | 80.8% | – | – | 21 |
| with_graph | 38.5% | 65.4% | 80.8% | 80.8% | – | – | 22 |

Median index time per checkout (incremental after the first): 1.46s
