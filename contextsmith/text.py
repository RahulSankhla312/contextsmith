"""Identifier splitting, query terms and token counting."""

from __future__ import annotations

import re
from functools import lru_cache

_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_CAMEL = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+")
_PATHLIKE = re.compile(r"(?:[\w.-]+/)+[\w.-]+\.(?:py|pyi|js|jsx|mjs|ts|tsx|java|go|rs)\b")

STOPWORDS = frozenset(
    """
    a an and are as at be been but by can could did do does doesn for from had has have how
    i if in into is it its just like may me might more most my no not of on or our should so
    some such than that the their them then there these they this those to too was we were
    what when where which while who why will with would you your also get got use used using
    want need make made see seems seem work works working expected actual instead however
    still only any all each other same new one two way case cases thing example e g eg ie
    self cls true false none null def return import from class function var let const
    """.split()
)


def split_identifier(word: str) -> list[str]:
    """getUserName -> [get, user, name]; parse_args -> [parse, args]."""
    parts: list[str] = []
    for chunk in word.split("_"):
        if chunk:
            parts.extend(p.lower() for p in _CAMEL.findall(chunk))
    return parts


def identifier_tokens(text: str) -> str:
    """Text for full-text indexing: original identifiers plus their split parts."""
    out: list[str] = []
    for ident in _IDENT.findall(text):
        low = ident.lower()
        out.append(low)
        parts = split_identifier(ident)
        if len(parts) > 1:
            out.extend(parts)
    return " ".join(out)


def path_tokens(path: str) -> str:
    return identifier_tokens(re.sub(r"[/\\.\-]", " ", path))


def query_terms(text: str, limit: int = 80) -> list[str]:
    """The terms of a task or issue that are worth searching for, most specific first.

    Code-looking identifiers (snake_case, camelCase, dotted, called) rank above plain words,
    because an issue's tracebacks and names point at the code far more precisely.
    """
    code_like: list[str] = []
    words: list[str] = []
    for m in _IDENT.finditer(text):
        ident = m.group(0)
        nxt = text[m.end() : m.end() + 1]
        camel = any(c.isupper() for c in ident[1:]) and not ident.isupper()
        looks_code = "_" in ident or camel or nxt in ("(", ".")
        low = ident.lower()
        if len(low) < 3 or low in STOPWORDS:
            continue
        (code_like if looks_code else words).append(low)
        if looks_code:
            code_like.extend(p for p in split_identifier(ident) if len(p) > 2 and p not in STOPWORDS)
    seen: set[str] = set()
    ordered: list[str] = []
    for t in code_like + words:
        if t not in seen:
            seen.add(t)
            ordered.append(t)
    return ordered[:limit]


_HTML_COMMENT = re.compile(r"<!--.*?-->", re.S)
_DOTTED = re.compile(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+")


def clean_task(text: str) -> str:
    """Drop issue-template boilerplate (HTML comments, checklists) that only adds noise."""
    text = _HTML_COMMENT.sub(" ", text)
    keep = []
    for line in text.splitlines():
        s = line.strip().lower()
        if s.startswith(("- [ ]", "- [x]", "* [ ]", "* [x]")) or "pip list" in s:
            continue
        keep.append(line)
    return "\n".join(keep)


def mentioned_identifiers(text: str) -> tuple[set[str], set[str]]:
    """Identifiers named in a task, and dotted pairs like Config.from_file."""
    names = {m.group(0) for m in _IDENT.finditer(text) if len(m.group(0)) >= 3}
    names = {n for n in names if n.lower() not in STOPWORDS}
    pairs: set[str] = set()
    for m in _DOTTED.finditer(text):
        parts = m.group(0).split(".")
        pairs.update(f"{a}.{b}" for a, b in zip(parts, parts[1:], strict=False))
    return names, pairs


def mentioned_paths(text: str) -> list[str]:
    return [m.group(0).lstrip("./") for m in _PATHLIKE.finditer(text.replace("\\", "/"))]


def fts_query(terms: list[str]) -> str:
    return " OR ".join(f'"{t}"' for t in terms if t.replace("_", "").isalnum())


@lru_cache(maxsize=1)
def _encoder():
    try:
        import tiktoken

        return tiktoken.get_encoding("cl100k_base")
    except Exception:  # noqa: BLE001 - offline or not installed: fall back to an estimate
        return None


def count_tokens(text: str) -> int:
    enc = _encoder()
    if enc is None:
        return max(1, len(text) // 4)
    return len(enc.encode(text, disallowed_special=()))
