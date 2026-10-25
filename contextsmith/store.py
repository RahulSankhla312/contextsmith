"""SQLite storage: one file per indexed repository."""

from __future__ import annotations

import contextlib
import sqlite3
from pathlib import Path

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;

CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY,
    path TEXT UNIQUE NOT NULL,
    language TEXT NOT NULL,
    sha1 TEXT NOT NULL,
    lines INTEGER NOT NULL,
    is_test INTEGER NOT NULL DEFAULT 0,
    pagerank REAL NOT NULL DEFAULT 0,
    mtime_ns INTEGER NOT NULL DEFAULT 0,
    size INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS symbols (
    id INTEGER PRIMARY KEY,
    file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    qualname TEXT NOT NULL,
    kind TEXT NOT NULL,
    start_line INTEGER NOT NULL,
    end_line INTEGER NOT NULL,
    signature TEXT NOT NULL,
    doc TEXT NOT NULL DEFAULT '',
    parent_id INTEGER
);
CREATE INDEX IF NOT EXISTS symbols_name ON symbols(name);
CREATE INDEX IF NOT EXISTS symbols_file ON symbols(file_id);

-- Calls as written in the source; resolved into `edges` after every index run.
CREATE TABLE IF NOT EXISTS raw_calls (
    file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    caller_id INTEGER,
    callee_name TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS raw_calls_file ON raw_calls(file_id);

CREATE TABLE IF NOT EXISTS imports (
    file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    module TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS edges (
    src INTEGER NOT NULL,
    dst INTEGER NOT NULL,
    weight INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (src, dst)
);
CREATE INDEX IF NOT EXISTS edges_dst ON edges(dst);

CREATE TABLE IF NOT EXISTS file_edges (
    src INTEGER NOT NULL,
    dst INTEGER NOT NULL,
    weight REAL NOT NULL,
    PRIMARY KEY (src, dst)
);

CREATE VIRTUAL TABLE IF NOT EXISTS symbol_fts USING fts5(
    name, qualname, signature, doc, path, body, tokenize='unicode61'
);
CREATE VIRTUAL TABLE IF NOT EXISTS file_fts USING fts5(path, body, tokenize='unicode61');

CREATE TABLE IF NOT EXISTS git_files (
    path TEXT PRIMARY KEY,
    commits INTEGER NOT NULL,
    last_ts INTEGER NOT NULL,
    authors INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS cochange (
    a TEXT NOT NULL,
    b TEXT NOT NULL,
    n INTEGER NOT NULL,
    PRIMARY KEY (a, b)
);
CREATE VIRTUAL TABLE IF NOT EXISTS history_fts USING fts5(path UNINDEXED, messages);

CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY,
    path TEXT,
    symbol TEXT,
    text TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE VIRTUAL TABLE IF NOT EXISTS note_fts USING fts5(text, path, symbol);
"""


SCHEMA_VERSION = "3"

# Everything rebuilt from the source tree. Notes, settings and the embedding cache are not.
DERIVED = ["vec_symbols", "symbol_vec", "symbol_fts", "file_fts", "history_fts", "edges", "file_edges",
           "raw_calls", "imports", "symbols", "git_files", "cochange", "files"]
DERIVED_META = ["indexed_at", "git_head", "resolved", "vectors_ok"]


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
    version = get_meta(conn, "schema_version")
    has_index = conn.execute("SELECT 1 FROM sqlite_master WHERE name='files'").fetchone()
    if has_index and version != SCHEMA_VERSION:
        _reset_derived(conn)
    conn.executescript(SCHEMA)
    set_meta(conn, "schema_version", SCHEMA_VERSION)
    conn.commit()
    return conn


def _reset_derived(conn: sqlite3.Connection) -> None:
    """An index from another version: drop what the next index run rebuilds (cheap, and
    embeddings come back from the cache), keep the team's notes."""
    try:  # dropping the vector table needs its module loaded
        import sqlite_vec

        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
    except Exception:  # noqa: BLE001
        pass
    for table in DERIVED:
        with contextlib.suppress(sqlite3.OperationalError):
            conn.execute(f"DROP TABLE IF EXISTS {table}")
    conn.executemany("DELETE FROM meta WHERE key=?", [(k,) for k in DERIVED_META])
    conn.commit()


def get_meta(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row["value"] if row else None


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO meta(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )


def delete_file(conn: sqlite3.Connection, file_id: int) -> None:
    ids = [r[0] for r in conn.execute("SELECT id FROM symbols WHERE file_id=?", (file_id,))]
    if ids:
        conn.executemany("DELETE FROM symbol_fts WHERE rowid=?", [(i,) for i in ids])
    conn.execute("DELETE FROM file_fts WHERE rowid=?", (file_id,))
    conn.execute("DELETE FROM files WHERE id=?", (file_id,))
