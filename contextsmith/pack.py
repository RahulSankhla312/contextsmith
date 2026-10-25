"""Fit the most useful context into a token budget.

A budgeted knapsack, solved greedily: every candidate (a function body, a class outline,
a file outline) has a value from the ranking and a cost in tokens. We repeatedly take the
candidate with the best value per token, discounting more material from a file we have
already covered, so a small budget buys breadth and a large one buys depth.
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from contextsmith.rank import Ranking
from contextsmith.text import count_tokens

MAX_BODY_LINES = 80
SAME_FILE_DISCOUNT = 0.7
# Value per token**COST_EXPONENT: below 1 so a long, relevant function can beat a short,
# marginal one. MIN_TOKENS stops one-line stubs from winning on size alone.
COST_EXPONENT = 0.1
MIN_TOKENS = 250
FENCE = {
    "python": "python", "javascript": "javascript", "typescript": "typescript", "tsx": "tsx",
    "java": "java", "go": "go", "rust": "rust",
}


@dataclass
class Unit:
    path: str
    start: int
    end: int
    label: str
    body: str
    value: float
    tokens: int = 0


@dataclass
class Pack:
    text: str
    tokens: int
    budget: int
    files: list[str] = field(default_factory=list)
    units: int = 0
    # (path, first line, last line) of every code snippet shown in full.
    spans: list[tuple[str, int, int]] = field(default_factory=list)


class _Files:
    def __init__(self, root: Path):
        self.root = root
        self._cache: dict[str, list[str]] = {}

    def lines(self, path: str) -> list[str]:
        if path not in self._cache:
            try:
                text = (self.root / path).read_text(encoding="utf-8", errors="replace")
            except OSError:
                text = ""
            self._cache[path] = text.splitlines()
        return self._cache[path]


def _body(lines: list[str], start: int, end: int) -> str:
    chunk = lines[start - 1 : end]
    if len(chunk) > MAX_BODY_LINES:
        more = len(chunk) - MAX_BODY_LINES
        chunk = chunk[:MAX_BODY_LINES] + [f"    ... ({more} more lines)"]
    return "\n".join(chunk)


def _outline(conn: sqlite3.Connection, path: str, parent_id: int | None = None, limit: int = 40) -> str:
    if parent_id is None:
        rows = conn.execute(
            "SELECT s.start_line, s.signature, s.kind, s.parent_id FROM symbols s JOIN files f ON f.id=s.file_id "
            "WHERE f.path=? ORDER BY s.start_line LIMIT ?",
            (path, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT start_line, signature, kind, parent_id FROM symbols WHERE parent_id=? ORDER BY start_line LIMIT ?",
            (parent_id, limit),
        ).fetchall()
    out = []
    for r in rows:
        indent = "    " if (parent_id is None and r["parent_id"]) else ""
        out.append(f"{indent}{r['signature']}  # L{r['start_line']}")
    return "\n".join(out)


def build(conn: sqlite3.Connection, root: Path, ranking: Ranking, budget: int, task: str = "") -> Pack:
    files = _Files(root)
    lang = {r["path"]: r["language"] for r in conn.execute("SELECT path, language FROM files")}
    top_score = ranking.files[0].score if ranking.files else 1.0

    header_lines = ["## Most relevant files"]
    for f in ranking.files[:10]:
        why = ", ".join(sorted(f.reasons, key=lambda k: f.reasons[k])[:3])
        header_lines.append(f"- {f.path}  ({why})")
    header = "\n".join(header_lines)
    remaining = budget - count_tokens(header)

    candidates: list[Unit] = []
    for s in ranking.symbols:
        lines = files.lines(s.path)
        if not lines:
            continue
        if s.kind in ("class", "impl", "trait", "interface", "struct") and s.end_line - s.start_line > 40:
            outline = _outline(conn, s.path, parent_id=s.id)
            body = f"{s.signature}  # L{s.start_line}-{s.end_line}\n{outline}"
            label = f"{s.qualname} (outline)"
        else:
            body = _body(lines, s.start_line, s.end_line)
            label = s.qualname
        candidates.append(Unit(s.path, s.start_line, s.end_line, label, body, s.score))
    for f in ranking.files[:20]:
        outline = _outline(conn, f.path)
        if outline:
            candidates.append(Unit(f.path, 0, 0, "file outline", outline, 0.5 * f.score / (top_score or 1.0)))
    for u in candidates:
        u.tokens = count_tokens(u.body) + 12

    chosen: list[Unit] = []
    per_file: dict[str, int] = defaultdict(int)
    pool = list(candidates)
    while pool and remaining > 0:
        best, best_ratio = None, 0.0
        for u in pool:
            if u.tokens > remaining:
                continue
            if u.start and any(c.path == u.path and c.start <= u.start and u.end <= c.end and c.start
                               for c in chosen):
                continue  # already inside a chosen body
            ratio = u.value * (SAME_FILE_DISCOUNT ** per_file[u.path]) / (max(u.tokens, MIN_TOKENS) ** COST_EXPONENT)
            if ratio > best_ratio:
                best, best_ratio = u, ratio
        if best is None:
            break
        chosen.append(best)
        pool.remove(best)
        per_file[best.path] += 1
        remaining -= best.tokens

    order = {f.path: i for i, f in enumerate(ranking.files)}

    def render(units: list[Unit]) -> tuple[str, list[str]]:
        by_file: dict[str, list[Unit]] = defaultdict(list)
        for u in units:
            by_file[u.path].append(u)
        paths = sorted(by_file, key=lambda p: order.get(p, 10_000))
        sections = [header]
        for path in paths:
            parts = [f"### {path}"]
            for u in sorted(by_file[path], key=lambda u: u.start):
                where = f"L{u.start}-{u.end} " if u.start else ""
                parts.append(f"```{FENCE.get(lang.get(path, ''), '')}\n# {where}{u.label}\n{u.body}\n```")
            sections.append("\n".join(parts))
        return "\n\n".join(sections), paths

    # Unit costs are estimates (headings and fences add a little), so the budget is
    # enforced on the final text: drop the least valuable snippet until it fits.
    text, paths = render(chosen)
    tokens = count_tokens(text)
    while tokens > budget and chosen:
        chosen.remove(min(chosen, key=lambda u: u.value / u.tokens))
        text, paths = render(chosen)
        tokens = count_tokens(text)
    spans = [(u.path, u.start, min(u.end, u.start + MAX_BODY_LINES - 1))
             for u in chosen if u.start and not u.label.endswith("(outline)")]
    return Pack(text=text, tokens=tokens, budget=budget, files=paths, units=len(chosen), spans=spans)
