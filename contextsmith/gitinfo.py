"""Signals from git history: churn, recency, co-change and commit messages per file.

Files that keep changing together are usually related even when no import or call
connects them (a model and its migration, a handler and its schema). No other
code-context tool ranks with this, and it costs one `git log`.
"""

from __future__ import annotations

import subprocess
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from itertools import combinations
from pathlib import Path

# A commit touching more files than this is a bulk change (rename, format, vendoring)
# and says nothing about which files belong together.
MAX_FILES_FOR_COCHANGE = 30


@dataclass
class GitStats:
    head: str = ""
    commits: Counter = field(default_factory=Counter)
    last_ts: dict[str, int] = field(default_factory=dict)
    authors: dict[str, set] = field(default_factory=lambda: defaultdict(set))
    cochange: Counter = field(default_factory=Counter)
    messages: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))


def git(root: Path, *args: str) -> str | None:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=root,
            capture_output=True,
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.decode("utf-8", "replace")


def head(root: Path) -> str:
    """The current commit. Read from .git directly when possible: a subprocess costs
    ~0.2 s on Windows, and the MCP server asks before every answer."""
    try:
        gitdir = root / ".git"
        ref = (gitdir / "HEAD").read_text(encoding="utf-8").strip()
        if not ref.startswith("ref: "):
            return ref  # detached HEAD: the commit itself
        name = ref[5:]
        loose = gitdir / name
        if loose.is_file():
            return loose.read_text(encoding="utf-8").strip()
        for line in (gitdir / "packed-refs").read_text(encoding="utf-8").splitlines():
            if line.endswith(" " + name):
                return line.split(" ", 1)[0]
    except OSError:  # worktrees and submodules keep .git as a file: ask git
        pass
    out = git(root, "rev-parse", "HEAD")
    return out.strip() if out else ""


def read_history(root: Path, max_commits: int = 3000) -> GitStats:
    stats = GitStats(head=head(root))
    out = git(
        root,
        "log",
        f"-n{max_commits}",
        "--no-merges",
        "--name-only",
        "--format=%x1e%H%x1f%at%x1f%an%x1f%s",
    )
    if not out:
        return stats
    for record in out.split("\x1e"):
        record = record.strip()
        if not record:
            continue
        header, _, body = record.partition("\n")
        parts = header.split("\x1f")
        if len(parts) < 4:
            continue
        _sha, ts, author, subject = parts[0], parts[1], parts[2], parts[3]
        files = [f.strip() for f in body.splitlines() if f.strip()]
        for f in files:
            stats.commits[f] += 1
            stats.last_ts[f] = max(stats.last_ts.get(f, 0), int(ts or 0))
            stats.authors[f].add(author)
            if len(stats.messages[f]) < 40:
                stats.messages[f].append(subject)
        if 2 <= len(files) <= MAX_FILES_FOR_COCHANGE:
            for a, b in combinations(sorted(set(files)), 2):
                stats.cochange[(a, b)] += 1
    return stats
