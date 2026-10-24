from __future__ import annotations

from pathlib import Path

from contextsmith.engine import Engine
from contextsmith.text import count_tokens


def test_index_reports_files_symbols_and_edges(repo: Path):
    report = Engine(repo).index()
    assert report.files_seen == 6
    assert report.files_parsed == 6
    assert report.symbols >= 9
    assert report.edges >= 2  # total -> apply_discount -> percent_off


def test_reindex_only_parses_changed_files(repo: Path):
    eng = Engine(repo)
    eng.index()
    (repo / "shop/shipping.py").write_text("def shipping_cost(w):\n    return 1\n", encoding="utf-8")
    (repo / "shop/new.py").write_text("def brand_new():\n    pass\n", encoding="utf-8")
    report = eng.index()
    assert report.files_parsed == 2
    assert eng.find_symbol("brand_new")


def test_deleted_files_leave_the_index(repo: Path):
    eng = Engine(repo)
    eng.index()
    (repo / "shop/shipping.py").unlink()
    report = eng.index()
    assert report.files_removed == 1
    assert not eng.find_symbol("shipping_cost")


def test_call_graph_resolves_across_files(repo: Path):
    eng = Engine(repo)
    eng.index()
    callers = {c["name"] for c in eng.callers("apply_discount")}
    assert "Cart.total" in callers
    callees = {c["name"] for c in eng.callees("apply_discount")}
    assert "percent_off" in callees
    impact = eng.impact("percent_off")
    assert {"apply_discount", "Cart.total"} <= {c["name"] for c in impact["callers"]}


def test_ranking_finds_the_right_file_for_a_task(repo: Path):
    eng = Engine(repo)
    files = [f.path for f in eng.rank("Coupon percentage discount is applied wrong").files]
    assert files[0] == "shop/pricing.py"
    assert "shop/shipping.py" not in files[:2]


def test_cochange_and_history_feed_related_files(repo: Path):
    eng = Engine(repo)
    eng.index()
    related = {r["path"]: r for r in eng.related_files("shop/cart.py")}
    assert related["shop/pricing.py"]["changed_together"] >= 2
    assert related["shop/pricing.py"]["code_link"] > 0


def test_test_files_rank_below_source(repo: Path):
    files = [f.path for f in Engine(repo).rank("cart total coupon").files]
    assert files.index("shop/cart.py") < files.index("tests/test_cart.py")


def test_context_respects_the_token_budget(repo: Path):
    eng = Engine(repo)
    for budget in (300, 800, 3000):
        pack = eng.context("coupon discount wrong in cart total", budget=budget)
        assert pack.tokens <= budget, (budget, pack.tokens)
        assert count_tokens(pack.text) == pack.tokens
    small = eng.context("coupon discount wrong in cart total", budget=300)
    large = eng.context("coupon discount wrong in cart total", budget=3000)
    assert large.units >= small.units
    assert "apply_discount" in large.text


def test_typescript_files_link_through_imports(repo: Path):
    eng = Engine(repo)
    eng.index()
    related = {r["path"] for r in eng.related_files("web/checkout.ts")}
    assert "web/money.ts" in related


def test_notes_surface_in_context(repo: Path):
    eng = Engine(repo)
    eng.add_note("Coupons are percentages only; flat coupons were removed in 2025.", path="shop/pricing.py")
    pack = eng.context("coupon discount bug", budget=2000)
    assert "Team notes" in pack.text and "flat coupons" in pack.text


def test_overview(repo: Path):
    ov = Engine(repo).overview()
    assert ov["files"] == 6 and ov["languages"]["python"] == 4
    assert "shop/pricing.py" in ov["central_files"]


def test_works_without_git(tmp_path: Path):
    (tmp_path / "a.py").write_text("def alpha():\n    beta()\n\ndef beta():\n    pass\n", encoding="utf-8")
    eng = Engine(tmp_path)
    report = eng.index()
    assert report.files_seen == 1 and report.edges == 1
