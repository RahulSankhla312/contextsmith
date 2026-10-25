"""Hybrid retrieval: which files and symbols matter for a task.

Each signal produces its own ranking; reciprocal-rank fusion combines them. RRF only uses
positions, so signals on different scales (BM25, edge weights, co-change counts) combine
without hand-tuned normalisation, and one noisy signal cannot swamp the rest.
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field

from contextsmith import semantic
from contextsmith.text import clean_task, fts_query, mentioned_identifiers, mentioned_paths, query_terms

# A small k lets the top of each list count for more; 8-15 scored the same, 60 clearly worse.
RRF_K = 15

# Tuned by grid search (bench/tune.py) on 89 SWE-bench Lite issues from 8 repositories, then
# checked on Django, which tuning never saw. Signals at 0 hurt *file* ranking in that search:
# symbol BM25, PageRank and graph neighbours favour hub files, and exact-name mentions and
# co-change added noise once embeddings were in. They stay available as weights, symbol BM25
# still picks the snippets inside the pack, and co-change powers `related_files`.
DEFAULT_WEIGHTS = {
    "file_bm25": 1.0,
    "semantic": 1.5,  # only when the index has embeddings (the `semantic` extra)
    "path_mention": 2.0,
    "history": 0.5,
    "symbol_mention": 0.0,
    "cochange": 0.0,
    "symbol_bm25": 0.0,
    "graph": 0.0,
    "pagerank": 0.0,
}
RERANK_TOP = 20
# How snippets (functions, classes) are scored: the file's relevance, scaled by how well the
# symbol itself matches (its best rank in symbol BM25 or embedding search). Tuned for
# `hunk_recall` with bench/tune_pack.py.
SYMBOL_K = 5.0  # a symbol at rank SYMBOL_K gets half the credit of the best match
SYMBOL_FLOOR = 0.2  # share of a snippet's value that comes from its file alone
FILE_POWER = 1.0
LIMIT_SYMBOLS = 60  # snippet candidates handed to the packer
# A name defined in more files than this (get, run, __init__) identifies nothing.
MAX_DEFINITIONS = 8


@dataclass
class RankedFile:
    path: str
    score: float
    reasons: dict[str, int] = field(default_factory=dict)  # signal -> rank in that signal


@dataclass
class RankedSymbol:
    id: int
    path: str
    name: str
    qualname: str
    kind: str
    start_line: int
    end_line: int
    signature: str
    doc: str
    score: float


@dataclass
class Ranking:
    terms: list[str]
    files: list[RankedFile]
    symbols: list[RankedSymbol]


def _bm25(conn: sqlite3.Connection, sql: str, match: str, limit: int) -> list[sqlite3.Row]:
    if not match:
        return []
    try:
        return conn.execute(sql, (match, limit)).fetchall()
    except sqlite3.OperationalError:
        return []


def _file_of(conn: sqlite3.Connection, ids: list[int]) -> dict[int, int]:
    out: dict[int, int] = {}
    for i in range(0, len(ids), 500):
        chunk = ids[i : i + 500]
        out.update((r[0], r[1]) for r in conn.execute(
            f"SELECT id, file_id FROM symbols WHERE id IN ({','.join('?' * len(chunk))})", chunk))
    return out


def file_card(conn: sqlite3.Connection, path: str, limit: int = 12) -> str:
    """A short text describing a file for the re-ranker: path plus its main definitions."""
    rows = conn.execute(
        "SELECT s.signature, s.doc FROM symbols s JOIN files f ON f.id=s.file_id WHERE f.path=? "
        "AND s.parent_id IS NULL ORDER BY s.start_line LIMIT ?", (path, limit)).fetchall()
    parts = [path] + [f"{r['signature']} {r['doc'][:80]}".strip() for r in rows]
    return "\n".join(parts)[:1500]


def _rerank(conn: sqlite3.Connection, task: str, files: list[RankedFile], k: int) -> list[RankedFile]:
    """Re-order the top files by fusing their fused rank with a cross-encoder's rank."""
    head, tail = files[:RERANK_TOP], files[RERANK_TOP:]
    scores = semantic.rerank(task, [file_card(conn, f.path) for f in head])
    by_ce = sorted(range(len(head)), key=lambda i: -scores[i])
    ce_rank = {i: r for r, i in enumerate(by_ce)}
    fused = sorted(range(len(head)), key=lambda i: -(1 / (k + i + 1) + 1 / (k + ce_rank[i] + 1)))
    out = []
    for i in fused:
        f = head[i]
        f.reasons["rerank"] = ce_rank[i] + 1
        out.append(f)
    return out + tail


def _mentions(conn: sqlite3.Connection, task: str, paths: dict) -> list[str]:
    names, pairs = mentioned_identifiers(task)
    if not names:
        return []
    names = list(names)[:300]
    rows = []
    for i in range(0, len(names), 200):
        chunk = names[i : i + 200]
        rows += conn.execute(
            f"SELECT name, qualname, file_id FROM symbols WHERE name IN ({','.join('?' * len(chunk))})", chunk
        ).fetchall()
    files_per_name: dict[str, set[int]] = defaultdict(set)
    for r in rows:
        files_per_name[r["name"]].add(r["file_id"])
    score: dict[int, float] = defaultdict(float)
    for r in rows:
        n = len(files_per_name[r["name"]])
        if n > MAX_DEFINITIONS:
            continue
        bonus = 3.0 if any(r["qualname"].endswith(p) for p in pairs if p.endswith("." + r["name"])) else 1.0
        score[r["file_id"]] += bonus / n
    ranked = sorted(score.items(), key=lambda kv: -kv[1])
    return [paths[f][0] for f, _ in ranked if f in paths][:50]


def rank(
    conn: sqlite3.Connection,
    task: str,
    *,
    limit_files: int = 50,
    limit_symbols: int | None = None,
    weights: dict[str, float] | None = None,
    test_penalty: float = 0.5,
    rrf_k: int | None = None,
    rerank: bool = False,
) -> Ranking:
    w = {**DEFAULT_WEIGHTS, **(weights or {})}
    k = RRF_K if rrf_k is None else rrf_k
    task = clean_task(task)
    terms = query_terms(task)
    match = fts_query(terms)
    lists: dict[str, list[str]] = {}

    paths = {r["id"]: (r["path"], r["is_test"], r["pagerank"])
             for r in conn.execute("SELECT id, path, is_test, pagerank FROM files")}
    path_to_id = {p: i for i, (p, _, _) in paths.items()}

    # 1. Whole-file BM25 (what "search the repo" tools do).
    if w["file_bm25"]:
        rows = _bm25(conn,
                     "SELECT rowid FROM file_fts WHERE file_fts MATCH ? ORDER BY bm25(file_fts, 2.0, 1.0) LIMIT ?",
                     match, 200)
        lists["file_bm25"] = [paths[r[0]][0] for r in rows if r[0] in paths]

    # 2. Symbol BM25: names, signatures and docstrings, weighted above bodies.
    sym_rows = _bm25(
        conn,
        "SELECT s.id, s.file_id, bm25(symbol_fts, 4.0, 2.0, 2.0, 1.0, 1.0, 0.5) AS score "
        "FROM symbol_fts JOIN symbols s ON s.id = symbol_fts.rowid "
        "WHERE symbol_fts MATCH ? ORDER BY score LIMIT ?",
        match, 400,
    )
    symbol_rank = {r["id"]: i for i, r in enumerate(sym_rows)}
    if w["symbol_bm25"]:
        seen: list[str] = []
        for r in sym_rows:
            p = paths.get(r["file_id"], ("",))[0]
            if p and p not in seen:
                seen.append(p)
        lists["symbol_bm25"] = seen[:200]

    # 2a. Semantic: nearest symbol summaries by embedding (when the index has vectors).
    sem_rank: dict[int, int] = {}
    if w.get("semantic") and semantic.has_vectors(conn):
        hits = semantic.search(conn, task, k=150)
        sem_rank = {sid: i for i, (sid, _) in enumerate(hits)}
        file_of = _file_of(conn, [sid for sid, _ in hits])
        per_file: dict[str, list[float]] = defaultdict(list)
        for sid, sim in hits:
            fid = file_of.get(sid)
            if fid in paths:
                per_file[paths[fid][0]].append(sim)
        # A file is as relevant as its best symbol, plus a little for each further strong match.
        agg = {p: sims[0] + 0.1 * sum(sims[1:3]) for p, sims in per_file.items()}
        lists["semantic"] = [p for p, _ in sorted(agg.items(), key=lambda kv: -kv[1])]

    # 2b. Names the task mentions exactly (Config.from_file, register_hook). A name defined
    #     in one file nearly decides the answer; one defined in many says little.
    if w.get("symbol_mention"):
        lists["symbol_mention"] = _mentions(conn, task, paths)

    # 3. Commit history: files whose past commit messages match the task.
    if w["history"]:
        rows = _bm25(conn,
                     "SELECT path FROM history_fts WHERE history_fts MATCH ? ORDER BY bm25(history_fts) LIMIT ?",
                     match, 100)
        lists["history"] = [r["path"] for r in rows if r["path"] in path_to_id]

    # 4. Paths named in the task (tracebacks, "in foo/bar.py").
    if w["path_mention"]:
        mentioned = mentioned_paths(task)
        hits: list[str] = []
        for m in mentioned:
            for p in path_to_id:
                if (p == m or p.endswith("/" + m) or m.endswith("/" + p)) and p not in hits:
                    hits.append(p)
        lists["path_mention"] = hits

    # Seeds for graph and co-change expansion: the strongest lexical hits so far.
    seed_scores: dict[str, float] = defaultdict(float)
    for name in ("path_mention", "symbol_mention", "file_bm25", "semantic", "symbol_bm25"):
        for i, p in enumerate(lists.get(name, [])[:10]):
            seed_scores[p] += 1.0 / (i + 1)
    seeds = [p for p, _ in sorted(seed_scores.items(), key=lambda kv: -kv[1])[:8]]

    # 5. Call/import graph neighbours of the seeds.
    if w["graph"] and seeds:
        neigh: dict[str, float] = defaultdict(float)
        for p in seeds:
            fid = path_to_id[p]
            for r in conn.execute(
                "SELECT dst AS other, weight FROM file_edges WHERE src=? "
                "UNION ALL SELECT src AS other, weight FROM file_edges WHERE dst=?",
                (fid, fid),
            ):
                if r["other"] in paths:
                    neigh[paths[r["other"]][0]] += r["weight"] * seed_scores[p]
        lists["graph"] = [p for p, _ in sorted(neigh.items(), key=lambda kv: -kv[1])][:50]

    # 6. Files that historically change together with the seeds.
    if w["cochange"] and seeds:
        co: dict[str, float] = defaultdict(float)
        for p in seeds:
            for r in conn.execute(
                "SELECT b AS other, n FROM cochange WHERE a=? UNION ALL SELECT a AS other, n FROM cochange WHERE b=?",
                (p, p),
            ):
                if r["other"] in path_to_id:
                    co[r["other"]] += r["n"] * seed_scores[p]
        lists["cochange"] = [p for p, _ in sorted(co.items(), key=lambda kv: -kv[1])][:50]

    # 7. Global importance, as a gentle prior among files that already matched.
    if w["pagerank"]:
        candidates = {p for lst in lists.values() for p in lst}
        lists["pagerank"] = sorted(candidates, key=lambda p: -paths[path_to_id[p]][2])

    scores: dict[str, float] = defaultdict(float)
    reasons: dict[str, dict[str, int]] = defaultdict(dict)
    for name, lst in lists.items():
        weight = w.get(name, 0.0)
        for i, p in enumerate(lst):
            scores[p] += weight / (k + i + 1)
            reasons[p][name] = i + 1
    for p in scores:
        if paths[path_to_id[p]][1]:
            scores[p] *= test_penalty

    files = [RankedFile(p, s, reasons[p]) for p, s in sorted(scores.items(), key=lambda kv: -kv[1])]
    if rerank and files and semantic.available():
        files = _rerank(conn, task, files, k)
    files = files[:limit_files]
    file_score = {f.path: f.score for f in files}

    symbols: list[RankedSymbol] = []
    ids = list(dict.fromkeys([r["id"] for r in sym_rows] + list(sem_rank)[:100]))
    if ids:
        placeholders = ",".join("?" * len(ids))
        rows = conn.execute(
            f"SELECT s.*, f.path FROM symbols s JOIN files f ON f.id = s.file_id WHERE s.id IN ({placeholders})",
            ids,
        ).fetchall()
        top = files[0].score if files else 1.0
        for r in rows:
            fs = (file_score.get(r["path"], 0.0) / (top or 1.0)) ** FILE_POWER
            best = min(symbol_rank.get(r["id"], 10_000), sem_rank.get(r["id"], 10_000))
            ss = SYMBOL_K / (SYMBOL_K + best)
            symbols.append(RankedSymbol(
                id=r["id"], path=r["path"], name=r["name"], qualname=r["qualname"], kind=r["kind"],
                start_line=r["start_line"], end_line=r["end_line"], signature=r["signature"],
                doc=r["doc"], score=fs * (SYMBOL_FLOOR + (1 - SYMBOL_FLOOR) * ss),
            ))
        symbols.sort(key=lambda s: -s.score)
    return Ranking(terms=terms, files=files, symbols=symbols[:limit_symbols or LIMIT_SYMBOLS])
