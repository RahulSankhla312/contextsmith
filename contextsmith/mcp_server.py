"""MCP server: the same engine, as tools any coding agent can call."""

from __future__ import annotations

import json
import os
from functools import lru_cache

try:  # MCP Python SDK 2.x
    from mcp.server.mcpserver import MCPServer as _Server
except ImportError:  # 1.x
    from mcp.server.fastmcp import FastMCP as _Server

from contextsmith.engine import Engine

mcp = _Server(
    "contextsmith",
    instructions=(
        "Code context for this repository. Call get_context first with the task and a token "
        "budget: it returns the most relevant code, ranked and packed. Use callers/impact before "
        "changing a function, related_files to find what usually changes together, and add_note "
        "to record a decision or gotcha future sessions should know."
    ),
)


@lru_cache(maxsize=1)
def engine() -> Engine:
    return Engine(os.environ.get("CTXSMITH_ROOT", "."))


def _json(data) -> str:
    return json.dumps(data, indent=2)


@mcp.tool()
def get_context(task: str, budget_tokens: int = 4000) -> str:
    """The most relevant code for a task, packed into at most `budget_tokens` tokens.

    Ranks files and symbols by full-text match, call graph, git co-change and history,
    then fits function bodies and file outlines into the budget.
    """
    pack = engine().context(task, budget=budget_tokens)
    return pack.text + f"\n\n<!-- {pack.tokens}/{pack.budget} tokens, {pack.units} snippets -->"


@mcp.tool()
def search(query: str, limit: int = 20) -> str:
    """Ranked symbols (functions, classes, methods) matching a query."""
    return _json(engine().search(query, limit=limit))


@mcp.tool()
def find_symbol(name: str) -> str:
    """Where a function, class or method is defined (by name or qualified name)."""
    return _json(engine().find_symbol(name))


@mcp.tool()
def callers(name: str) -> str:
    """Functions that call `name`."""
    return _json(engine().callers(name))


@mcp.tool()
def callees(name: str) -> str:
    """Functions that `name` calls."""
    return _json(engine().callees(name))


@mcp.tool()
def impact(name: str, depth: int = 3) -> str:
    """Everything that transitively calls `name`: what a change to it could break."""
    return _json(engine().impact(name, depth=depth))


@mcp.tool()
def related_files(path: str) -> str:
    """Files linked to `path` by imports/calls, and files that historically change with it."""
    return _json(engine().related_files(path))


@mcp.tool()
def add_note(text: str, path: str = "", symbol: str = "") -> str:
    """Remember a decision, invariant or gotcha, optionally pinned to a file or symbol."""
    note_id = engine().add_note(text, path or None, symbol or None)
    return f"Saved note {note_id}."


@mcp.tool()
def overview() -> str:
    """Repository summary: languages, size, most central and most changed files."""
    return _json(engine().overview())


@mcp.tool()
def reindex() -> str:
    """Re-index changed files (incremental and fast)."""
    return _json(engine().index().as_dict())


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
