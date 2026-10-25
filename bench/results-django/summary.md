SWE-bench Lite file localisation · 114 issues · repos: django/django

| strategy | recall@1 | recall@3 | recall@5 | recall@10 | budget_recall@4000 | budget_recall@8000 | hunk_recall@4000 | hunk_recall@8000 | query ms |
|---|---|---|---|---|---|---|---|---|---|
| bm25_files | 50.9% | 70.2% | 77.2% | 84.2% | 28.9% | 49.1% | 28.9% | 49.1% | 145 |
| lexical | 48.2% | 74.6% | 78.9% | 86.0% | 86.0% | 89.5% | 42.3% | 46.2% | 145 |
| semantic_only | 48.2% | 69.3% | 78.9% | 86.8% | – | – | – | – | 249 |
| contextsmith | 51.8% | 79.8% | 85.1% | 88.6% | 92.1% | 96.5% | 48.1% | 50.7% | 238 |
| contextsmith+rerank | 34.2% | 73.7% | 81.6% | 91.2% | – | – | – | – | 1824 |
| no_git | 56.1% | 78.9% | 84.2% | 90.4% | – | – | – | – | 249 |

Median index time per checkout (incremental after the first): 6.45s
