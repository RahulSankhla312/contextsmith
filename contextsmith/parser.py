"""Turn one source file into symbols, calls and imports, using tree-sitter."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import cache

from contextsmith.languages import SPECS, LanguageSpec

_IDENT_TYPES = {
    "identifier",
    "field_identifier",
    "property_identifier",
    "type_identifier",
    "shorthand_property_identifier",
    "private_property_identifier",
}
_MEMBER_TYPES = {
    "attribute": "attribute",
    "member_expression": "property",
    "selector_expression": "field",
    "field_expression": "field",
    "scoped_identifier": "name",
    "generic_type": "type",
}
_JS_FUNCTION_VALUES = {"arrow_function", "function_expression", "function", "generator_function"}
_LAST_IDENT = re.compile(r"([A-Za-z_$][A-Za-z0-9_$]*)\W*$")


@dataclass
class Symbol:
    name: str
    qualname: str
    kind: str
    start_line: int
    end_line: int
    signature: str
    doc: str = ""
    parent: int | None = None


@dataclass
class ParsedFile:
    language: str
    symbols: list[Symbol] = field(default_factory=list)
    # (index of the calling symbol, or None at module level; called name)
    calls: list[tuple[int | None, str]] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)


@cache
def _parser(language: str):
    from tree_sitter_language_pack import get_parser

    return get_parser(language)


def _text(node, source: bytes) -> str:
    return source[node.start_byte : node.end_byte].decode("utf-8", "replace")


def _last_ident(text: str) -> str:
    text = re.sub(r"<.*>", "", text)  # drop generics
    m = _LAST_IDENT.search(text.replace("::", ".").strip())
    return m.group(1) if m else ""


def _callee(node, source: bytes) -> str:
    target = (
        node.child_by_field_name("function")
        or node.child_by_field_name("name")
        or node.child_by_field_name("constructor")
        or node.child_by_field_name("type")
    )
    if target is None:
        return ""
    for _ in range(4):  # unwrap a.b.c() / pkg::f() / obj->method()
        if target.type in _IDENT_TYPES:
            return _text(target, source)
        field_name = _MEMBER_TYPES.get(target.type)
        inner = target.child_by_field_name(field_name) if field_name else None
        if inner is None:
            break
        target = inner
    return _last_ident(_text(target, source))


def _name(node, source: bytes, spec: LanguageSpec) -> str:
    n = node.child_by_field_name("name")
    if n is not None:
        return _last_ident(_text(n, source)) or _text(n, source)
    if spec.name == "rust" and node.type == "impl_item":
        t = node.child_by_field_name("type")
        return _last_ident(_text(t, source)) if t is not None else "impl"
    return ""


def _signature(node, source: bytes) -> str:
    body = node.child_by_field_name("body")
    end = body.start_byte if body is not None else node.end_byte
    sig = source[node.start_byte : end].decode("utf-8", "replace")
    if body is None:
        sig = sig.splitlines()[0] if sig else ""
    sig = " ".join(sig.split()).rstrip(":{ ").strip()
    return sig[:240]


def _python_doc(node, source: bytes) -> str:
    body = node.child_by_field_name("body")
    if body is None or not body.named_children:
        return ""
    first = body.named_children[0]
    # Older grammars wrap the docstring in an expression_statement; newer ones don't.
    if first.type == "expression_statement" and first.named_children:
        first = first.named_children[0]
    if first.type != "string":
        return ""
    content = next((c for c in first.named_children if c.type == "string_content"), None)
    raw = _text(content, source) if content is not None else _text(first, source).strip("\"' \n")
    return " ".join(raw.split())[:300]


def _comment_doc(node, source: bytes) -> str:
    lines: list[str] = []
    prev = node.prev_named_sibling
    while prev is not None and "comment" in prev.type and len(lines) < 6:
        lines.insert(0, _text(prev, source))
        prev = prev.prev_named_sibling
    text = " ".join(lines)
    text = re.sub(r"(/\*\*?|\*/|^\s*\*|//+|#)", " ", text)
    return " ".join(text.split())[:300]


def _import(node, source: bytes, language: str) -> list[str]:
    if language == "python":
        if node.type == "import_from_statement":
            m = node.child_by_field_name("module_name")
            return [_text(m, source)] if m is not None else []
        return [
            _text(c, source).split(" as ")[0]
            for c in node.named_children
            if c.type in ("dotted_name", "aliased_import")
        ]
    if language in ("javascript", "typescript", "tsx"):
        src = node.child_by_field_name("source")
        return [_text(src, source).strip("'\"`")] if src is not None else []
    if language == "go":
        p = node.child_by_field_name("path")
        return [_text(p, source).strip('"`')] if p is not None else []
    if language == "java":
        t = _text(node, source).replace("import", "").replace("static", "").strip(" ;\n")
        return [t]
    if language == "rust":
        a = node.child_by_field_name("argument")
        return [_text(a, source)] if a is not None else []
    return []


def parse(source: bytes, language: str) -> ParsedFile:
    spec = SPECS[language]
    tree = _parser(language).parse(source)
    out = ParsedFile(language=language)
    js_like = language in ("javascript", "typescript", "tsx")

    # (node, index of enclosing symbol, qualified-name prefix)
    stack: list[tuple[object, int | None, str]] = [(tree.root_node, None, "")]
    while stack:
        node, current, prefix = stack.pop()
        kind = spec.definitions.get(node.type)
        name = ""
        if kind is None and js_like and node.type == "variable_declarator":
            value = node.child_by_field_name("value")
            if value is not None and value.type in _JS_FUNCTION_VALUES:
                kind = "function"
        if kind is not None:
            name = _name(node, source, spec)
        if kind is not None and name:
            if kind == "function" and current is not None and out.symbols[current].kind in (
                "class", "impl", "trait", "interface", "struct",
            ):
                kind = "method"
            qualname = f"{prefix}.{name}" if prefix else name
            doc = _python_doc(node, source) if language == "python" else _comment_doc(node, source)
            out.symbols.append(
                Symbol(
                    name=name,
                    qualname=qualname,
                    kind=kind,
                    start_line=node.start_point[0] + 1,
                    end_line=node.end_point[0] + 1,
                    signature=_signature(node, source),
                    doc=doc,
                    parent=current,
                )
            )
            current = len(out.symbols) - 1
            prefix = qualname
        elif node.type in spec.calls:
            callee = _callee(node, source)
            if callee:
                out.calls.append((current, callee))
        elif node.type in spec.imports:
            out.imports.extend(i for i in _import(node, source, language) if i)

        for child in reversed(node.named_children):
            stack.append((child, current, prefix))
    return out
