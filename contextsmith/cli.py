"""Command line: `ctxsmith index`, `ctxsmith context "task"`, `ctxsmith serve`, ..."""

from __future__ import annotations

import contextlib
import json
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    with contextlib.suppress(AttributeError, OSError):
        _stream.reconfigure(encoding="utf-8", errors="replace")

import typer  # noqa: E402
from rich.console import Console  # noqa: E402
from rich.table import Table  # noqa: E402

from contextsmith.engine import Engine  # noqa: E402

app = typer.Typer(add_completion=False, help="ContextSmith: the best code context per token.")
note_app = typer.Typer(help="Team notes pinned to code.")
app.add_typer(note_app, name="note")
console = Console()
PathOpt = typer.Option(".", "--path", "-p", help="Repository to work on.")


def _print_json(data) -> None:
    if sys.stdout.isatty():
        console.print_json(json.dumps(data))
    else:  # piped into jq, a file or another program: plain JSON, no colour codes
        sys.stdout.write(json.dumps(data, indent=2) + "\n")


@app.command()
def index(path: str = typer.Argument(".", help="Repository to index."),
          no_git: bool = typer.Option(False, "--no-git", help="Skip git history."),
          semantic: bool = typer.Option(None, "--semantic/--no-semantic",
                                        help="Turn local embeddings on or off (remembered).")) -> None:
    """Index a repository (incremental: only changed files are re-parsed)."""
    def progress(done: int, total: int) -> None:
        console.print(f"[dim]embedded {done}/{total} symbols[/]", highlight=False)

    report = Engine(path).index(with_git=not no_git, semantic=semantic, progress=progress)
    extra = f" · {report.embedded} embedded" if report.embedded else ""
    console.print(f"[green]Indexed[/] {report.files_seen} files "
                  f"({report.files_parsed} parsed, {report.files_removed} removed) · "
                  f"{report.symbols} symbols · {report.edges} call edges{extra} · {report.seconds}s")


@app.command()
def context(task: str, budget: int = typer.Option(4000, "--budget", "-b", help="Token budget."),
            rerank: bool = typer.Option(False, "--rerank", help="Experimental: re-rank the top files with a cross-encoder (lowered recall@1 in the benchmark)."),
            path: str = PathOpt) -> None:
    """Print the best context for a task within a token budget."""
    pack = Engine(path).context(task, budget=budget, rerank=rerank)
    sys.stdout.write(pack.text + "\n")
    console.print(f"[dim]{pack.tokens}/{pack.budget} tokens · {pack.units} snippets · "
                  f"{len(pack.files)} files[/]", highlight=False)


@app.command()
def search(query: str, limit: int = typer.Option(15, "--limit", "-n"), path: str = PathOpt) -> None:
    """Ranked symbols for a query."""
    table = Table("score", "symbol", "kind", "where")
    for r in Engine(path).search(query, limit=limit):
        table.add_row(f"{r['score']:.3f}", r["name"], r["kind"], f"{r['path']}:{r['lines']}")
    console.print(table)


@app.command()
def rank(task: str, limit: int = typer.Option(15, "--limit", "-n"), path: str = PathOpt) -> None:
    """Ranked files for a task, with the signals that found each one."""
    table = Table("#", "file", "score", "signals (rank)")
    for i, f in enumerate(Engine(path).rank(task).files[:limit], 1):
        why = ", ".join(f"{k}#{v}" for k, v in sorted(f.reasons.items(), key=lambda kv: kv[1]))
        table.add_row(str(i), f.path, f"{f.score:.4f}", why)
    console.print(table)


JsonOpt = typer.Option(False, "--json", help="Print JSON instead of a table.")


def _print_symbols(rows: list[dict], as_json: bool, title: str = "") -> None:
    if as_json:
        _print_json(rows)
        return
    depth = any("depth" in r for r in rows)
    table = Table(*(["depth"] if depth else []), "symbol", "kind", "where", title=title or None)
    for r in rows:
        table.add_row(*([str(r["depth"])] if depth else []), r["name"], r["kind"], f"{r['path']}:{r['lines']}")
    console.print(table if rows else "[dim]nothing found[/]")


@app.command()
def symbol(name: str, path: str = PathOpt, as_json: bool = JsonOpt) -> None:
    """Where a symbol is defined."""
    _print_symbols(Engine(path).find_symbol(name), as_json)


@app.command()
def callers(name: str, path: str = PathOpt, as_json: bool = JsonOpt) -> None:
    """Functions that call NAME."""
    _print_symbols(Engine(path).callers(name), as_json)


@app.command()
def callees(name: str, path: str = PathOpt, as_json: bool = JsonOpt) -> None:
    """Functions that NAME calls."""
    _print_symbols(Engine(path).callees(name), as_json)


@app.command()
def impact(name: str, depth: int = typer.Option(3, "--depth"), limit: int = typer.Option(15, "--limit", "-n"),
           path: str = PathOpt, as_json: bool = JsonOpt) -> None:
    """What could break if NAME changes (transitive callers)."""
    result = Engine(path).impact(name, depth=depth)
    if as_json:
        _print_json(result)
        return
    rows = result["callers"]
    title = f"{len(rows)} callers in {len(result['files'])} files depend on {name}"
    _print_symbols(rows[:limit], False, title)
    if len(rows) > limit:
        console.print(f"[dim]… and {len(rows) - limit} more (--limit, --json)[/]")


@app.command()
def related(file: str, path: str = PathOpt) -> None:
    """Files linked to FILE by code, and files that change together with it."""
    _print_json(Engine(path).related_files(file))


@app.command()
def overview(path: str = PathOpt) -> None:
    """Repository summary."""
    _print_json(Engine(path).overview())


@note_app.command("add")
def note_add(text: str, file: str = typer.Option(None, "--file"), symbol: str = typer.Option(None, "--symbol"),
             path: str = PathOpt) -> None:
    """Record a decision, invariant or gotcha."""
    console.print(f"Saved note {Engine(path).add_note(text, file, symbol)}.")


@note_app.command("list")
def note_list(path: str = PathOpt) -> None:
    _print_json(Engine(path).notes())


@app.command()
def serve(path: str = PathOpt) -> None:
    """Run the MCP server over stdio (for Claude Code, Cursor, Codex, ...)."""
    import os

    os.environ["CTXSMITH_ROOT"] = path
    from contextsmith.mcp_server import main as run

    run()


@app.command("mcp-config")
def mcp_config(client: str = typer.Argument("claude", help="claude, cursor, windsurf, codex or json."),
               path: str = PathOpt) -> None:
    """Print the exact snippet that connects an agent to this repository."""
    import shutil

    from contextsmith.engine import find_root

    root = str(find_root(Path(path)))
    exe = "ctxsmith"
    if sys.prefix != sys.base_prefix:  # inside a virtualenv the agent won't have on its PATH
        exe = shutil.which("ctxsmith", path=str(Path(sys.executable).parent)) or exe
    if client == "claude":
        quoted = f'"{exe}"' if " " in exe else exe
        lines = [f'claude mcp add contextsmith -- {quoted} serve --path "{root}"']
    elif client == "codex":  # ~/.codex/config.toml
        lines = ["[mcp_servers.contextsmith]", f"command = {json.dumps(exe)}",
                 f'args = ["serve", "--path", {json.dumps(root)}]']
    else:  # Cursor, Windsurf and most other clients read this JSON shape
        snippet = {"mcpServers": {"contextsmith": {"command": exe, "args": ["serve", "--path", root]}}}
        lines = [json.dumps(snippet, indent=2)]
    sys.stdout.write("\n".join(lines) + "\n")


@app.command()
def bench(
    repos: str = typer.Option("pytest-dev/pytest,psf/requests,pallets/flask", help="SWE-bench Lite repos."),
    limit: int = typer.Option(0, help="Max instances (0 = all for those repos)."),
    out: str = typer.Option("bench/results", help="Output folder."),
    semantic: bool = typer.Option(True, "--semantic/--no-semantic", help="Include embedding strategies."),
) -> None:
    """Run the SWE-bench Lite file-localisation benchmark."""
    from contextsmith.bench import run

    run([r.strip() for r in repos.split(",") if r.strip()], limit=limit, out_dir=out, semantic=semantic)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
