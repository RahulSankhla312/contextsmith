from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from contextsmith.cli import app

runner = CliRunner()


def run(*args: str) -> str:
    result = runner.invoke(app, list(args))
    assert result.exit_code == 0, result.output
    return result.output


def test_cli_end_to_end(repo: Path):
    p = str(repo)
    assert "Indexed 6 files" in run("index", p, "--no-semantic")
    assert "shop/pricing.py" in run("rank", "coupon discount", "-p", p)
    assert "tokens" in run("context", "coupon discount", "-b", "600", "-p", p)
    assert "Cart.total" in run("impact", "percent_off", "-p", p)
    assert json.loads(run("callers", "apply_discount", "--json", "-p", p))[0]["name"] == "Cart.total"
    assert "Saved note" in run("note", "add", "Coupons stack", "--file", "shop/pricing.py", "-p", p)
    assert json.loads(run("overview", "-p", p))["files"] == 6


def test_mcp_config_snippets(repo: Path):
    assert "claude mcp add contextsmith" in run("mcp-config", "claude", "-p", str(repo))
    assert json.loads(run("mcp-config", "cursor", "-p", str(repo)))["mcpServers"]["contextsmith"]["args"][0] == "serve"
    assert "[mcp_servers.contextsmith]" in run("mcp-config", "codex", "-p", str(repo))
