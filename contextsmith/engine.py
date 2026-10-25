"""The public API: one Engine per repository."""

from __future__ import annotations

import sqlite3
import threading
import time
from collections import deque
from pathlib import Path

from contextsmith import gitinfo, store
from contextsmith.indexer import Indexer, IndexReport
from contextsmith.pack import Pack, build
from contextsmith.rank import Ranking, rank
from contextsmith.text import count_tokens, fts_query, query_terms


def find_root(path: Path) -> Path:
    out = gitinfo.git(path, "rev-parse", "--show-toplevel")
    return Path(out.strip()) if out else path.resolve()


class Engine:
    def __init__(self, path: str | Path = ".", db_path: str | Path | None = None):
        self.root = find_root(Path(path))
        if db_path is None:
            folder = self.root / ".contextsmith"
            folder.mkdir(exist_ok=True)
            ignore = folder / ".gitignore"
            if not ignore.exists():
                ignore.write_text("*\n", encoding="utf-8")
            db_path = folder / "index.db"
        self.db_path = Path(db_path)
        self.conn: sqlite3.Connection = store.connect(self.db_path)
        self._lock = threading.Lock()
        self._last_refresh = 0.0

    # ---------------------------------------------------------------- index

    def index(self, with_git: bool = True, semantic: bool | None = None, progress=None) -> IndexReport:
        """Index changed files.

        Embeddings are on by default when the `semantic` extra is installed; `semantic=False`
        turns them off and `semantic=True` insists on them. The choice is remembered.
        """
        from contextsmith import semantic as sem

        with self._lock:
            report = Indexer(self.root, self.conn).run(with_git=with_git)
            if semantic is None and store.get_meta(self.conn, "semantic") is None:
                semantic = sem.available()
            if semantic is not None:
                store.set_meta(self.conn, "semantic", "on" if semantic else "off")
                self.conn.commit()
            if store.get_meta(self.conn, "semantic") == "on":
                if not sem.available():
                    raise RuntimeError("Semantic search needs: pip install 'contextsmith[semantic]'")
                # Skip the vector sync when no file changed and the last sync finished.
                changed = report.files_parsed or report.files_removed
                if changed or semantic or store.get_meta(self.conn, "vectors_ok") != "1":
                    store.set_meta(self.conn, "vectors_ok", "0")
                    self.conn.commit()
                    report.embedded = sem.update(self.conn, progress=progress)
                    store.set_meta(self.conn, "vectors_ok", "1")
                    self.conn.commit()
            return report

    def ensure_indexed(self) -> None:
        if store.get_meta(self.conn, "indexed_at") is None:
            self.index()

    def refresh(self, min_interval: float = 2.0) -> IndexReport | None:
        """Re-index changed files, at most every `min_interval` seconds.

        Cheap when nothing changed (one stat per file), so long-running servers can call it
        before every query and never answer from a stale index.
        """
        now = time.monotonic()
        if now - self._last_refresh < min_interval:
            return None
        self._last_refresh = now
        return self.index()

    # ---------------------------------------------------------------- retrieval

    def rank(self, task: str, **kwargs) -> Ranking:
        self.ensure_indexed()
        return rank(self.conn, task, **kwargs)

    def context(self, task: str, budget: int = 4000, **kwargs) -> Pack:
        """The most useful context for `task`, within `budget` tokens."""
        ranking = self.rank(task, **kwargs)
        notes = self._notes_for(task, [f.path for f in ranking.files[:10]])
        note_text = ""
        if notes:
            note_text = "## Team notes\n" + "\n".join(
                f"- {n['text']}" + (f"  ({n['path']}{':' + n['symbol'] if n['symbol'] else ''})" if n["path"] else "")
                for n in notes
            )
        pack = build(self.conn, self.root, ranking, max(budget - count_tokens(note_text), 200), task)
        if note_text:
            pack.text = note_text + "\n\n" + pack.text
            pack.tokens = count_tokens(pack.text)
            pack.budget = budget
        return pack

    def search(self, query: str, limit: int = 20) -> list[dict]:
        ranking = self.rank(query, limit_symbols=limit)
        return [
            {"path": s.path, "name": s.qualname, "kind": s.kind, "lines": f"{s.start_line}-{s.end_line}",
             "signature": s.signature, "score": round(s.score, 4)}
            for s in ranking.symbols[:limit]
        ]

    # ---------------------------------------------------------------- graph

    def find_symbol(self, name: str, limit: int = 20) -> list[dict]:
        self.ensure_indexed()
        rows = self.conn.execute(
            "SELECT s.*, f.path FROM symbols s JOIN files f ON f.id=s.file_id "
            "WHERE s.name=? OR s.qualname=? OR s.qualname LIKE ? ORDER BY f.is_test, f.pagerank DESC LIMIT ?",
            (name, name, f"%.{name}", limit),
        ).fetchall()
        return [self._sym(r) for r in rows]

    def callers(self, name: str, limit: int = 50) -> list[dict]:
        return self._neighbours(name, "SELECT src AS other FROM edges WHERE dst=?", limit)

    def callees(self, name: str, limit: int = 50) -> list[dict]:
        return self._neighbours(name, "SELECT dst AS other FROM edges WHERE src=?", limit)

    def impact(self, name: str, depth: int = 3, limit: int = 200) -> dict:
        """Everything that (transitively) calls `name`: what a change could break."""
        self.ensure_indexed()
        start = [s["id"] for s in self.find_symbol(name)]
        seen = {sid: 0 for sid in start}
        queue = deque(start)
        while queue and len(seen) < limit:
            sid = queue.popleft()
            if seen[sid] >= depth:
                continue
            for r in self.conn.execute("SELECT src FROM edges WHERE dst=?", (sid,)):
                if r["src"] not in seen:
                    seen[r["src"]] = seen[sid] + 1
                    queue.append(r["src"])
        affected = [sid for sid in seen if sid not in start]
        rows = self._symbols_by_id(affected)
        for r in rows:
            r["depth"] = seen[r["id"]]
        rows.sort(key=lambda r: (r["depth"], r["path"]))
        return {"symbol": name, "callers": rows, "files": sorted({r["path"] for r in rows})}

    def related_files(self, path: str, limit: int = 15) -> list[dict]:
        self.ensure_indexed()
        row = self.conn.execute("SELECT id FROM files WHERE path=?", (path,)).fetchone()
        out: dict[str, dict] = {}
        if row:
            for r in self.conn.execute(
                "SELECT f.path, e.weight FROM file_edges e JOIN files f ON f.id=e.dst WHERE e.src=? "
                "UNION ALL SELECT f.path, e.weight FROM file_edges e JOIN files f ON f.id=e.src WHERE e.dst=?",
                (row["id"], row["id"]),
            ):
                out.setdefault(r["path"], {"path": r["path"], "code_link": 0.0, "changed_together": 0})
                out[r["path"]]["code_link"] += round(r["weight"], 2)
        for r in self.conn.execute(
            "SELECT b AS other, n FROM cochange WHERE a=? UNION ALL SELECT a AS other, n FROM cochange WHERE b=?",
            (path, path),
        ):
            out.setdefault(r["other"], {"path": r["other"], "code_link": 0.0, "changed_together": 0})
            out[r["other"]]["changed_together"] += r["n"]
        ranked = sorted(out.values(), key=lambda d: -(d["code_link"] + d["changed_together"]))
        return ranked[:limit]

    def overview(self) -> dict:
        self.ensure_indexed()
        c = self.conn
        langs = {r["language"]: r["n"] for r in c.execute(
            "SELECT language, COUNT(*) AS n FROM files GROUP BY language ORDER BY n DESC")}
        central = [r["path"] for r in c.execute(
            "SELECT path FROM files WHERE is_test=0 ORDER BY pagerank DESC LIMIT 15")]
        hot = [r["path"] for r in c.execute(
            "SELECT g.path FROM git_files g JOIN files f ON f.path=g.path WHERE f.is_test=0 "
            "ORDER BY g.commits DESC LIMIT 10")]
        return {
            "root": str(self.root),
            "files": c.execute("SELECT COUNT(*) FROM files").fetchone()[0],
            "symbols": c.execute("SELECT COUNT(*) FROM symbols").fetchone()[0],
            "call_edges": c.execute("SELECT COUNT(*) FROM edges").fetchone()[0],
            "semantic": self._semantic_status(),
            "languages": langs,
            "central_files": central,
            "most_changed_files": hot,
        }

    def _semantic_status(self) -> dict:
        from contextsmith import semantic as sem

        on = store.get_meta(self.conn, "semantic") == "on"
        out: dict = {"enabled": on, "installed": sem.available()}
        if on and sem.has_vectors(self.conn):
            out["vectors"] = self.conn.execute("SELECT COUNT(*) FROM symbol_vec").fetchone()[0]
            out["model"] = sem.DEFAULT_MODEL
        return out

    # ---------------------------------------------------------------- memory

    def add_note(self, text: str, path: str | None = None, symbol: str | None = None) -> int:
        with self.conn:
            cur = self.conn.execute("INSERT INTO notes(path, symbol, text) VALUES (?,?,?)", (path, symbol, text))
            self.conn.execute("INSERT INTO note_fts(rowid, text, path, symbol) VALUES (?,?,?,?)",
                              (cur.lastrowid, text, path or "", symbol or ""))
        return cur.lastrowid

    def notes(self) -> list[dict]:
        return [dict(r) for r in self.conn.execute("SELECT * FROM notes ORDER BY id")]

    def _notes_for(self, task: str, paths: list[str], limit: int = 5) -> list[sqlite3.Row]:
        found: dict[int, sqlite3.Row] = {}
        match = fts_query(query_terms(task))
        if match:
            try:
                for r in self.conn.execute(
                    "SELECT n.* FROM note_fts JOIN notes n ON n.id=note_fts.rowid WHERE note_fts MATCH ? "
                    "ORDER BY bm25(note_fts) LIMIT ?", (match, limit)):
                    found[r["id"]] = r
            except sqlite3.OperationalError:
                pass
        if paths:
            ph = ",".join("?" * len(paths))
            for r in self.conn.execute(f"SELECT * FROM notes WHERE path IN ({ph}) LIMIT ?", (*paths, limit)):
                found[r["id"]] = r
        return list(found.values())[:limit]

    # ---------------------------------------------------------------- helpers

    def _sym(self, r: sqlite3.Row) -> dict:
        return {"id": r["id"], "path": r["path"], "name": r["qualname"], "kind": r["kind"],
                "lines": f"{r['start_line']}-{r['end_line']}", "signature": r["signature"]}

    def _symbols_by_id(self, ids: list[int]) -> list[dict]:
        if not ids:
            return []
        ph = ",".join("?" * len(ids))
        rows = self.conn.execute(
            f"SELECT s.*, f.path FROM symbols s JOIN files f ON f.id=s.file_id WHERE s.id IN ({ph})", ids
        ).fetchall()
        return [self._sym(r) for r in rows]

    def _neighbours(self, name: str, sql: str, limit: int) -> list[dict]:
        self.ensure_indexed()
        ids: list[int] = []
        for s in self.find_symbol(name):
            ids.extend(r["other"] for r in self.conn.execute(sql, (s["id"],)))
        return self._symbols_by_id(list(dict.fromkeys(ids))[:limit])

    def close(self) -> None:
        self.conn.close()
