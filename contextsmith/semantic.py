"""Semantic retrieval: local embeddings + a vector index inside the same SQLite file.

Optional (``pip install contextsmith[semantic]``) and fully local: ONNX models via
fastembed, vectors in sqlite-vec when the extension loads, numpy brute force otherwise.

Design choices, each measured:
- **What is embedded:** a short summary per symbol (path, qualified name, signature, first
  docstring sentence), not the body. Embedding cost grows steeply with text length on CPU
  (≈30x slower for whole bodies), and the summary is what identifies "which function is this
  about". Bodies stay in the BM25 index.
- **Content-addressed cache:** vectors are keyed by a hash of (model, summary), so a symbol
  that did not change is never embedded twice — across re-indexes and git checkouts.
- **Test files are skipped:** they rank below source files anyway and would double the cost.
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
from functools import lru_cache

DEFAULT_MODEL = os.environ.get("CTXSMITH_EMBED_MODEL", "BAAI/bge-small-en-v1.5")
RERANK_MODEL = os.environ.get("CTXSMITH_RERANK_MODEL", "Xenova/ms-marco-MiniLM-L-6-v2")
BATCH = 64


def _model_dir() -> str:
    """Where ONNX models live: a stable folder, not fastembed's default under the temp dir."""
    return os.environ.get("FASTEMBED_CACHE_PATH") or os.path.join(
        os.path.expanduser("~"), ".cache", "contextsmith", "models")

SCHEMA = """
CREATE TABLE IF NOT EXISTS embed_cache (
    hash TEXT PRIMARY KEY,
    vec BLOB NOT NULL
);
CREATE TABLE IF NOT EXISTS symbol_vec (
    symbol_id INTEGER PRIMARY KEY,
    hash TEXT NOT NULL
);
"""


def available() -> bool:
    try:
        import fastembed  # noqa: F401
        import numpy  # noqa: F401
    except ImportError:
        return False
    return True


def _np():
    import numpy as np

    return np


@lru_cache(maxsize=2)
def _embedder(model: str):
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    from fastembed import TextEmbedding

    return TextEmbedding(model, cache_dir=_model_dir())


@lru_cache(maxsize=1)
def _reranker(model: str):
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    from fastembed.rerank.cross_encoder import TextCrossEncoder

    return TextCrossEncoder(model, cache_dir=_model_dir())


def embed(texts: list[str], model: str = DEFAULT_MODEL):
    np = _np()
    vecs = np.asarray(list(_embedder(model).embed(texts, batch_size=BATCH)), dtype=np.float32)
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    return vecs / np.maximum(norms, 1e-9)


@lru_cache(maxsize=256)
def _query_vec(text: str, model: str):
    return embed([text], model)[0]


def summary(path: str, qualname: str, signature: str, doc: str) -> str:
    first = doc.split(". ")[0][:160] if doc else ""
    return f"{path} :: {qualname}\n{signature[:200]}\n{first}".strip()


def _hash(model: str, text: str) -> str:
    return hashlib.sha1(f"{model}\0{text}".encode()).hexdigest()


# ----------------------------------------------------------------- vector index


class VectorIndex:
    """sqlite-vec when it loads; otherwise an in-memory numpy matrix."""

    def __init__(self, conn: sqlite3.Connection, dim: int):
        self.conn = conn
        self.dim = dim
        self.native = _load_vec(conn)
        if self.native:
            conn.execute(
                f"CREATE VIRTUAL TABLE IF NOT EXISTS vec_symbols USING vec0(embedding float[{dim}] distance_metric=cosine)"
            )
        self._matrix = None
        self._ids = None

    def upsert(self, rows: list[tuple[int, bytes]]) -> None:
        if self.native and rows:
            self.conn.executemany("DELETE FROM vec_symbols WHERE rowid=?", [(r[0],) for r in rows])
            self.conn.executemany("INSERT INTO vec_symbols(rowid, embedding) VALUES (?, ?)", rows)
        self._matrix = None

    def delete_missing(self) -> None:
        if self.native:
            self.conn.execute(
                "DELETE FROM vec_symbols WHERE rowid NOT IN (SELECT symbol_id FROM symbol_vec)"
            )
        self._matrix = None

    def search(self, query, k: int = 100) -> list[tuple[int, float]]:
        """(symbol_id, similarity) pairs, best first."""
        np = _np()
        if self.native:
            rows = self.conn.execute(
                "SELECT rowid, distance FROM vec_symbols WHERE embedding MATCH ? AND k = ? ORDER BY distance",
                (query.astype(np.float32).tobytes(), k),
            ).fetchall()
            return [(r[0], 1.0 - r[1]) for r in rows]
        if self._matrix is None:
            rows = self.conn.execute(
                "SELECT v.symbol_id, c.vec FROM symbol_vec v JOIN embed_cache c ON c.hash=v.hash"
            ).fetchall()
            if not rows:
                return []
            self._ids = np.array([r[0] for r in rows])
            self._matrix = np.vstack([np.frombuffer(r[1], dtype=np.float32) for r in rows])
        sims = self._matrix @ query
        top = np.argsort(-sims)[:k]
        return [(int(self._ids[i]), float(sims[i])) for i in top]


def _load_vec(conn: sqlite3.Connection) -> bool:
    try:
        import sqlite_vec

        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        return True
    except Exception:  # noqa: BLE001 - missing extension or a Python built without loading
        return False


# ----------------------------------------------------------------- indexing


def update(conn: sqlite3.Connection, model: str = DEFAULT_MODEL, progress=None) -> int:
    """Bring vectors in line with the current symbols. Returns how many texts were embedded.

    Every symbol's summary hash is compared with the one its vector was made from, so a
    symbol id that SQLite reused after a file changed can never keep a stale vector.
    """
    np = _np()
    conn.executescript(SCHEMA)
    linked = dict(conn.execute("SELECT symbol_id, hash FROM symbol_vec").fetchall())
    rows = conn.execute(
        "SELECT s.id, s.qualname, s.signature, s.doc, f.path FROM symbols s JOIN files f ON f.id=s.file_id "
        "WHERE f.is_test=0"
    ).fetchall()
    todo: dict[str, str] = {}
    links: list[tuple[int, str]] = []
    current: set[int] = set()
    for r in rows:
        text = summary(r["path"], r["qualname"], r["signature"], r["doc"])
        h = _hash(model, text)
        current.add(r["id"])
        if linked.get(r["id"]) != h:
            links.append((r["id"], h))
            todo.setdefault(h, text)
    gone = [(i,) for i in linked if i not in current]
    conn.executemany("DELETE FROM symbol_vec WHERE symbol_id=?", gone)
    have = set()
    hashes = list(todo)
    for i in range(0, len(hashes), 500):
        chunk = hashes[i : i + 500]
        have.update(r[0] for r in conn.execute(
            f"SELECT hash FROM embed_cache WHERE hash IN ({','.join('?' * len(chunk))})", chunk))
    missing = [h for h in hashes if h not in have]
    for i in range(0, len(missing), 256):
        batch = missing[i : i + 256]
        vecs = embed([todo[h] for h in batch], model)
        conn.executemany("INSERT OR REPLACE INTO embed_cache(hash, vec) VALUES (?, ?)",
                         [(h, v.astype(np.float32).tobytes()) for h, v in zip(batch, vecs, strict=True)])
        conn.commit()
        if progress:
            progress(min(i + 256, len(missing)), len(missing))
    conn.executemany("INSERT OR REPLACE INTO symbol_vec(symbol_id, hash) VALUES (?, ?)", links)
    dim = _dim(conn)
    if dim:
        index = VectorIndex(conn, dim)
        index.delete_missing()
        if index.native:
            changed = [i for i, _ in links]
            # Also backfill rows absent from vec_symbols (e.g. the index was built without sqlite-vec).
            changed += [r[0] for r in conn.execute(
                "SELECT symbol_id FROM symbol_vec WHERE symbol_id NOT IN (SELECT rowid FROM vec_symbols)")]
            vecs = []
            for i in range(0, len(changed), 500):
                chunk = changed[i : i + 500]
                vecs += conn.execute(
                    "SELECT v.symbol_id, c.vec FROM symbol_vec v JOIN embed_cache c ON c.hash=v.hash "
                    f"WHERE v.symbol_id IN ({','.join('?' * len(chunk))})", chunk).fetchall()
            index.upsert([(r[0], r[1]) for r in dict((r[0], r) for r in vecs).values()])
    conn.commit()
    return len(missing)


def _dim(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT vec FROM embed_cache LIMIT 1").fetchone()
    return len(row[0]) // 4 if row else 0


def has_vectors(conn: sqlite3.Connection) -> bool:
    try:
        return conn.execute("SELECT 1 FROM symbol_vec LIMIT 1").fetchone() is not None
    except sqlite3.OperationalError:
        return False


# ----------------------------------------------------------------- retrieval


_QUERY_CHARS = 1200


def query_text(task: str) -> str:
    """The part of a task worth embedding: the title and opening description."""
    return " ".join(task.split())[:_QUERY_CHARS]


def search(conn: sqlite3.Connection, task: str, k: int = 100, model: str = DEFAULT_MODEL) -> list[tuple[int, float]]:
    dim = _dim(conn)
    if not dim:
        return []
    q = _query_vec(query_text(task), model)
    return VectorIndex(conn, dim).search(q, k)


def rerank(task: str, docs: list[str], model: str = RERANK_MODEL) -> list[float]:
    """Cross-encoder relevance scores for (task, doc) pairs."""
    return [float(s) for s in _reranker(model).rerank(query_text(task), docs)]
