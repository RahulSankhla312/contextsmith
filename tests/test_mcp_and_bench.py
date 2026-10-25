from __future__ import annotations

import asyncio
from pathlib import Path

from contextsmith import mcp_server
from contextsmith.bench import gold_files, gold_hunks, hunk_recall


def test_mcp_exposes_the_tools(repo: Path, monkeypatch):
    monkeypatch.setenv("CTXSMITH_ROOT", str(repo))
    mcp_server.engine.cache_clear()
    tools = {t.name for t in asyncio.run(mcp_server.mcp.list_tools())}
    assert {"get_context", "search", "find_symbol", "callers", "callees", "impact",
            "related_files", "add_note", "overview", "reindex"} <= tools
    out = mcp_server.get_context("coupon discount", budget_tokens=1500)
    assert "shop/pricing.py" in out and "tokens" in out
    assert "apply_discount" in mcp_server.find_symbol("apply_discount")
    mcp_server.engine.cache_clear()


def test_gold_files_come_from_the_patch():
    patch = (
        "diff --git a/src/a.py b/src/a.py\n--- a/src/a.py\n+++ b/src/a.py\n@@ -1 +1 @@\n-x\n+y\n"
        "diff --git a/src/b.py b/src/b.py\n"
    )
    assert gold_files(patch) == ["src/a.py", "src/b.py"]


def test_hunks_track_the_lines_a_fix_touches():
    patch = (
        "diff --git a/m.py b/m.py\n--- a/m.py\n+++ b/m.py\n"
        "@@ -10,3 +10,3 @@ def f():\n     a = 1\n-    b = 2\n+    b = 3\n     c = 4\n"
        "@@ -40,2 +40,3 @@ def g():\n     x = 1\n+    y = 2\n     z = 3\n"
    )
    hunks = gold_hunks(patch)
    assert hunks == [("m.py", {11}), ("m.py", {40, 41})]
    assert hunk_recall(hunks, [("m.py", 5, 20)]) == 0.5
    assert hunk_recall(hunks, [("m.py", 1, 100)]) == 1.0
    assert hunk_recall(hunks, [("other.py", 1, 100)]) == 0.0
