"""Semantic layer: only runs when the optional extra is installed."""

from __future__ import annotations

from pathlib import Path

import pytest

from contextsmith import semantic

pytestmark = pytest.mark.skipif(not semantic.available(), reason="pip install contextsmith[semantic]")


def test_semantic_index_finds_files_by_meaning(repo: Path):
    from contextsmith.engine import Engine

    eng = Engine(repo)
    report = eng.index(semantic=True)
    assert report.embedded >= 6  # source symbols only; tests are skipped
    # No shared words with "shipping_cost" or its docstring, only shared meaning.
    ranking = eng.rank("how much does delivery of a heavy parcel cost", weights={"file_bm25": 0, "history": 0, "cochange": 0})
    assert ranking.files[0].path == "shop/shipping.py"
    assert "semantic" in ranking.files[0].reasons


def test_vectors_are_reused_when_nothing_changed(repo: Path):
    from contextsmith.engine import Engine

    eng = Engine(repo)
    eng.index(semantic=True)
    assert eng.index().embedded == 0  # stays on, but nothing new to embed
    (repo / "shop/shipping.py").write_text(
        'def shipping_cost(weight_kg, express=False):\n    """Flat rate plus weight."""\n    return 1\n',
        encoding="utf-8",
    )
    assert eng.index().embedded == 1  # only the changed symbol


def test_reranker_reorders_without_losing_files(repo: Path):
    from contextsmith.engine import Engine

    eng = Engine(repo)
    eng.index(semantic=True)
    plain = [f.path for f in eng.rank("coupon percentage discount").files]
    reranked = [f.path for f in eng.rank("coupon percentage discount", rerank=True).files]
    assert sorted(plain) == sorted(reranked)
    assert reranked[0] in ("shop/pricing.py", "shop/cart.py")


def test_reused_symbol_ids_never_keep_stale_vectors(repo: Path):
    from contextsmith import semantic as sem
    from contextsmith.engine import Engine

    eng = Engine(repo)
    eng.index(semantic=True)
    # Rewriting the newest file frees its symbol ids, which SQLite hands to the new symbols.
    (repo / "web/money.ts").write_text(
        "// Convert grams to kilograms.\nexport function gramsToKg(g: number): number {\n  return g / 1000;\n}\n",
        encoding="utf-8",
    )
    eng.index()
    for row in eng.conn.execute(
        "SELECT s.id, s.qualname, s.signature, s.doc, f.path, v.hash FROM symbols s "
        "JOIN files f ON f.id=s.file_id JOIN symbol_vec v ON v.symbol_id=s.id"
    ):
        expected = sem._hash(sem.DEFAULT_MODEL, sem.summary(row[4], row[1], row[2], row[3]))
        assert row[5] == expected, row[1]
