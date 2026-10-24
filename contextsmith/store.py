"""SQLite storage: one file per indexed repository."""

from __future__ import annotations

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
    pagerank REAL NOT NULL DEFAULT 0
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
    name, qualname, signature, doc, path, tokenize='unicode61'
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


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA)
    return conn


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
