"""Build and incrementally update the index for one repository."""

from __future__ import annotations

import hashlib
import math
import os
import posixpath
import sqlite3
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

from contextsmith import gitinfo, store
from contextsmith.languages import is_test_path, language_for
from contextsmith.parser import parse
from contextsmith.text import identifier_tokens, path_tokens

MAX_FILE_BYTES = 1_500_000
SKIP_DIRS = {
    ".git", "node_modules", ".venv", "venv", "env", "dist", "build", "__pycache__",
    ".contextsmith", "target", "vendor", ".mypy_cache", ".pytest_cache", ".tox", ".next",
}


@dataclass
class IndexReport:
    files_seen: int = 0
    files_parsed: int = 0
    files_removed: int = 0
    symbols: int = 0
    edges: int = 0
    seconds: float = 0.0

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def list_files(root: Path) -> list[str]:
    out = gitinfo.git(root, "ls-files", "-co", "--exclude-standard")
    if out is not None:
        paths = [p.strip() for p in out.splitlines() if p.strip()]
    else:
        paths = []
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
            for f in filenames:
                paths.append(os.path.relpath(os.path.join(dirpath, f), root).replace("\\", "/"))
    # `git ls-files` still lists tracked files deleted from disk, so check existence.
    return sorted(
        p for p in paths
        if language_for(p)
        and not any(part in SKIP_DIRS for part in p.split("/")[:-1])
        and (root / p).is_file()
    )


def _looks_generated(data: bytes) -> bool:
    if not data:
        return False
    lines = data.count(b"\n") + 1
    return len(data) / lines > 400  # minified bundles have enormous lines


def _module_keys(path: str) -> list[str]:
    """Names other files might use to import this one."""
    stem, _ = posixpath.splitext(path)
    if stem.endswith("/__init__") or stem.endswith("/index") or stem.endswith("/mod"):
        stem = stem.rsplit("/", 1)[0]
    parts = [p for p in stem.split("/") if p]
    keys = []
    for i in range(len(parts)):
        keys.append(".".join(parts[i:]))
    return keys


def _resolve_import(module: str, importer: str, keys: dict[str, set[int]]) -> set[int]:
    m = module.strip()
    if m.startswith((".", "/")) and ("/" in m or m.startswith("./") or m.startswith("../")):
        # JS-style relative path
        base = posixpath.dirname(importer)
        m = posixpath.normpath(posixpath.join(base, m))
    m = m.replace("::", ".").replace("/", ".").lstrip(".")
    for prefix in ("crate.", "super.", "self."):
        if m.startswith(prefix):
            m = m[len(prefix):]
    m = m.rstrip(".*").replace("{", "").replace("}", "")
    parts = [p for p in m.split(".") if p]
    for cut in range(len(parts), max(len(parts) - 3, 0), -1):
        hit = keys.get(".".join(parts[:cut]))
        if hit:
            return hit
    return set()


class Indexer:
    def __init__(self, root: Path, conn: sqlite3.Connection):
        self.root = root
        self.conn = conn

    def run(self, with_git: bool = True) -> IndexReport:
        t0 = time.perf_counter()
        report = IndexReport()
        conn = self.conn
        paths = list_files(self.root)
        report.files_seen = len(paths)
        known = {r["path"]: (r["id"], r["sha1"]) for r in conn.execute("SELECT id, path, sha1 FROM files")}
        current = set(paths)

        with conn:
            for path in set(known) - current:
                store.delete_file(conn, known[path][0])
                report.files_removed += 1
            for path in paths:
                full = self.root / path
                try:
                    data = full.read_bytes()
                except OSError:
                    continue
                if len(data) > MAX_FILE_BYTES or _looks_generated(data):
                    continue
                sha = hashlib.sha1(data).hexdigest()
                if path in known and known[path][1] == sha:
                    continue
                if path in known:
                    store.delete_file(conn, known[path][0])
                self._index_file(path, data, sha)
                report.files_parsed += 1

            report.edges = self._resolve()
            if with_git:
                self._git()
            store.set_meta(conn, "indexed_at", str(int(time.time())))

        report.symbols = conn.execute("SELECT COUNT(*) FROM symbols").fetchone()[0]
        report.seconds = round(time.perf_counter() - t0, 2)
        return report

    # ------------------------------------------------------------------ files

    def _index_file(self, path: str, data: bytes, sha: str) -> None:
        conn = self.conn
        language = language_for(path)
        text = data.decode("utf-8", "replace")
        try:
            parsed = parse(data, language)
        except Exception:  # noqa: BLE001 - one unparsable file must not stop the index
            parsed = None
        cur = conn.execute(
            "INSERT INTO files(path, language, sha1, lines, is_test) VALUES (?,?,?,?,?)",
            (path, language, sha, text.count("\n") + 1, int(is_test_path(path))),
        )
        file_id = cur.lastrowid
        conn.execute(
            "INSERT INTO file_fts(rowid, path, body) VALUES (?,?,?)",
            (file_id, path_tokens(path), identifier_tokens(text[:400_000])),
        )
        if parsed is None:
            return
        ids: list[int] = []
        ptoks = path_tokens(path)
        for sym in parsed.symbols:
            parent = ids[sym.parent] if sym.parent is not None else None
            cur = conn.execute(
                "INSERT INTO symbols(file_id, name, qualname, kind, start_line, end_line, signature, doc, parent_id)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (file_id, sym.name, sym.qualname, sym.kind, sym.start_line, sym.end_line,
                 sym.signature, sym.doc, parent),
            )
            sid = cur.lastrowid
            ids.append(sid)
            conn.execute(
                "INSERT INTO symbol_fts(rowid, name, qualname, signature, doc, path) VALUES (?,?,?,?,?,?)",
                (sid, identifier_tokens(sym.name), identifier_tokens(sym.qualname),
                 identifier_tokens(sym.signature), sym.doc, ptoks),
            )
        conn.executemany(
            "INSERT INTO raw_calls(file_id, caller_id, callee_name) VALUES (?,?,?)",
            [(file_id, ids[c] if c is not None else None, name) for c, name in parsed.calls],
        )
        conn.executemany(
            "INSERT INTO imports(file_id, module) VALUES (?,?)",
            [(file_id, m) for m in dict.fromkeys(parsed.imports)],
        )

    # ------------------------------------------------------------------ graph

    def _resolve(self) -> int:
        conn = self.conn
        files = {r["id"]: r["path"] for r in conn.execute("SELECT id, path FROM files")}
        keys: dict[str, set[int]] = defaultdict(set)
        for fid, path in files.items():
            for k in _module_keys(path):
                keys[k].add(fid)

        imported: dict[int, set[int]] = defaultdict(set)
        for r in conn.execute("SELECT file_id, module FROM imports"):
            for dst in _resolve_import(r["module"], files[r["file_id"]], keys):
                if dst != r["file_id"]:
                    imported[r["file_id"]].add(dst)

        by_name: dict[str, list[tuple[int, int]]] = defaultdict(list)
        for r in conn.execute("SELECT id, name, file_id FROM symbols"):
            by_name[r["name"]].append((r["id"], r["file_id"]))

        edges: Counter = Counter()
        file_calls: Counter = Counter()
        for r in conn.execute("SELECT file_id, caller_id, callee_name FROM raw_calls"):
            cands = by_name.get(r["callee_name"])
            if not cands:
                continue
            src_file = r["file_id"]
            same = [c for c in cands if c[1] == src_file]
            via_import = [c for c in cands if c[1] in imported.get(src_file, ())]
            chosen = same or via_import or (cands if len(cands) <= 2 else [])
            for sid, fid in chosen:
                if r["caller_id"] is not None and r["caller_id"] != sid:
                    edges[(r["caller_id"], sid)] += 1
                if fid != src_file:
                    file_calls[(src_file, fid)] += 1

        conn.execute("DELETE FROM edges")
        conn.executemany("INSERT INTO edges(src, dst, weight) VALUES (?,?,?)",
                         [(a, b, w) for (a, b), w in edges.items()])

        weights: Counter = Counter()
        for src, dsts in imported.items():
            for dst in dsts:
                weights[(src, dst)] += 1.0
        for (src, dst), n in file_calls.items():
            weights[(src, dst)] += math.log1p(n)
        conn.execute("DELETE FROM file_edges")
        conn.executemany("INSERT INTO file_edges(src, dst, weight) VALUES (?,?,?)",
                         [(a, b, w) for (a, b), w in weights.items()])
        self._pagerank(list(files), weights)
        return len(edges)

    def _pagerank(self, nodes: list[int], weights: Counter, iterations: int = 30) -> None:
        if not nodes:
            return
        n = len(nodes)
        out: dict[int, list[tuple[int, float]]] = defaultdict(list)
        out_total: Counter = Counter()
        for (a, b), w in weights.items():
            out[a].append((b, w))
            out_total[a] += w
        rank = dict.fromkeys(nodes, 1.0 / n)
        damping = 0.85
        for _ in range(iterations):
            dangling = sum(rank[v] for v in nodes if out_total[v] == 0)
            nxt = dict.fromkeys(nodes, (1 - damping) / n + damping * dangling / n)
            for a, targets in out.items():
                share = damping * rank[a] / out_total[a]
                for b, w in targets:
                    if b in nxt:
                        nxt[b] += share * w
            rank = nxt
        top = max(rank.values()) or 1.0
        self.conn.executemany("UPDATE files SET pagerank=? WHERE id=?",
                              [(rank[v] / top, v) for v in nodes])

    # ------------------------------------------------------------------ git

    def _git(self) -> None:
        conn = self.conn
        head = gitinfo.head(self.root)
        if not head or store.get_meta(conn, "git_head") == head:
            return
        stats = gitinfo.read_history(self.root)
        indexed = {r["path"] for r in conn.execute("SELECT path FROM files")}
        conn.execute("DELETE FROM git_files")
        conn.execute("DELETE FROM cochange")
        conn.execute("DELETE FROM history_fts")
        conn.executemany(
            "INSERT INTO git_files(path, commits, last_ts, authors) VALUES (?,?,?,?)",
            [(p, n, stats.last_ts.get(p, 0), len(stats.authors[p]))
             for p, n in stats.commits.items() if p in indexed],
        )
        partners: dict[str, list[tuple[int, str]]] = defaultdict(list)
        for (a, b), n in stats.cochange.items():
            if a in indexed and b in indexed and n >= 2:
                partners[a].append((n, b))
                partners[b].append((n, a))
        rows = set()
        for a, lst in partners.items():
            for n, b in sorted(lst, reverse=True)[:40]:
                rows.add((min(a, b), max(a, b), n))
        conn.executemany("INSERT OR REPLACE INTO cochange(a, b, n) VALUES (?,?,?)", list(rows))
        conn.executemany(
            "INSERT INTO history_fts(path, messages) VALUES (?,?)",
            [(p, identifier_tokens(" ".join(msgs))) for p, msgs in stats.messages.items() if p in indexed],
        )
        store.set_meta(conn, "git_head", head)
