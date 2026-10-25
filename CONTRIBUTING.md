# Contributing

Thanks for helping. ContextSmith has one rule that matters more than the others:
**ranking changes must come with benchmark numbers.**

## Setup

```bash
git clone https://github.com/RahulSankhla312/contextsmith
cd contextsmith
python -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e ".[dev,semantic]"
pytest -q && ruff check .
```

## Changing the ranker or the packer

1. Tune only on the tuning repositories:
   `python bench/tune.py pytest-dev/pytest,psf/requests,pallets/flask,sphinx-doc/sphinx,pylint-dev/pylint,pydata/xarray,astropy/astropy,mwaskom/seaborn`
2. Check the result on repositories the tuning never saw (Django is the held-out set):
   `ctxsmith bench --repos django/django --out bench/results-django`
3. Put both tables in the pull request. A change that helps the tuning set and hurts the
   held-out set is overfitting, and will not be merged.

The first run clones each repository into `~/.cache/contextsmith/repos` and embeds its
symbols once; later runs reuse both.

## Adding a language

Add the extensions to `EXTENSIONS` and a `LanguageSpec` (definition, call, import and
container node types) to `SPECS` in `contextsmith/languages.py`, then a sample to
`tests/test_parser.py`. The grammar comes from `tree-sitter-language-pack`.

## Commits

Small, focused commits with a message that says why. Run `pytest -q` and `ruff check .` first.
