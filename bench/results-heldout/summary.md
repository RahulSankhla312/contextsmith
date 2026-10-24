SWE-bench Lite file localisation · 37 issues · repos: astropy/astropy, mwaskom/seaborn, pydata/xarray, pylint-dev/pylint, sphinx-doc/sphinx

| strategy | recall@1 | recall@3 | recall@5 | recall@10 | budget_recall@4000 | budget_recall@8000 | query ms |
|---|---|---|---|---|---|---|---|
| bm25_files | 43.2% | 56.8% | 70.3% | 81.1% | 29.7% | 37.8% | 27 |
| contextsmith | 35.1% | 56.8% | 75.7% | 83.8% | 78.4% | 86.5% | 33 |
| no_git | 27.0% | 51.4% | 67.6% | 89.2% | – | – | 28 |
| no_mentions | 35.1% | 56.8% | 75.7% | 83.8% | – | – | 30 |
| with_graph | 35.1% | 56.8% | 73.0% | 83.8% | – | – | 34 |

Median index time per checkout (incremental after the first): 3.24s
