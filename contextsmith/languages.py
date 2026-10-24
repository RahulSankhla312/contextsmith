"""What each supported language looks like to the parser.

Tree-sitter gives every language its own node names. This module is the one place
that knows them, so the parser can stay language-agnostic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import PurePosixPath

EXTENSIONS: dict[str, str] = {
    ".py": "python",
    ".pyi": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".mts": "typescript",
    ".cts": "typescript",
    ".tsx": "tsx",
    ".java": "java",
    ".go": "go",
    ".rs": "rust",
}


@dataclass(frozen=True)
class LanguageSpec:
    name: str
    # node type -> symbol kind
    definitions: dict[str, str]
    # node types that call something
    calls: frozenset[str]
    # node types that import something
    imports: frozenset[str]
    # node types whose children are a class/impl body (for qualified names)
    containers: frozenset[str] = field(default_factory=frozenset)
    comment: str = "comment"


_JS_DEFS = {
    "function_declaration": "function",
    "generator_function_declaration": "function",
    "class_declaration": "class",
    "method_definition": "method",
}
_TS_DEFS = {
    **_JS_DEFS,
    "abstract_class_declaration": "class",
    "interface_declaration": "interface",
    "type_alias_declaration": "type",
    "enum_declaration": "enum",
}

SPECS: dict[str, LanguageSpec] = {
    "python": LanguageSpec(
        name="python",
        definitions={"function_definition": "function", "class_definition": "class"},
        calls=frozenset({"call"}),
        imports=frozenset({"import_statement", "import_from_statement"}),
        containers=frozenset({"class_definition"}),
    ),
    "javascript": LanguageSpec(
        name="javascript",
        definitions=_JS_DEFS,
        calls=frozenset({"call_expression", "new_expression"}),
        imports=frozenset({"import_statement"}),
        containers=frozenset({"class_declaration"}),
    ),
    "typescript": LanguageSpec(
        name="typescript",
        definitions=_TS_DEFS,
        calls=frozenset({"call_expression", "new_expression"}),
        imports=frozenset({"import_statement"}),
        containers=frozenset({"class_declaration", "abstract_class_declaration"}),
    ),
    "tsx": LanguageSpec(
        name="tsx",
        definitions=_TS_DEFS,
        calls=frozenset({"call_expression", "new_expression"}),
        imports=frozenset({"import_statement"}),
        containers=frozenset({"class_declaration", "abstract_class_declaration"}),
    ),
    "java": LanguageSpec(
        name="java",
        definitions={
            "class_declaration": "class",
            "interface_declaration": "interface",
            "enum_declaration": "enum",
            "record_declaration": "class",
            "method_declaration": "method",
            "constructor_declaration": "method",
        },
        calls=frozenset({"method_invocation", "object_creation_expression"}),
        imports=frozenset({"import_declaration"}),
        containers=frozenset(
            {"class_declaration", "interface_declaration", "enum_declaration", "record_declaration"}
        ),
        comment="block_comment",
    ),
    "go": LanguageSpec(
        name="go",
        definitions={
            "function_declaration": "function",
            "method_declaration": "method",
            "type_spec": "type",
        },
        calls=frozenset({"call_expression"}),
        imports=frozenset({"import_spec"}),
    ),
    "rust": LanguageSpec(
        name="rust",
        definitions={
            "function_item": "function",
            "struct_item": "struct",
            "enum_item": "enum",
            "trait_item": "trait",
            "impl_item": "impl",
            "mod_item": "module",
        },
        calls=frozenset({"call_expression"}),
        imports=frozenset({"use_declaration"}),
        containers=frozenset({"impl_item", "trait_item", "mod_item"}),
        comment="line_comment",
    ),
}


def language_for(path: str) -> str | None:
    return EXTENSIONS.get(PurePosixPath(path).suffix.lower())


def is_test_path(path: str) -> bool:
    """Heuristic: test files and test folders across the supported ecosystems."""
    p = path.lower().replace("\\", "/")
    name = p.rsplit("/", 1)[-1]
    return (
        "/tests/" in f"/{p}"
        or "/test/" in f"/{p}"
        or "/__tests__/" in f"/{p}"
        or name.startswith("test_")
        or name.endswith(("_test.py", "_test.go", ".test.ts", ".test.js", ".spec.ts", ".spec.js",
                          ".test.tsx", "test.java", "tests.rs"))
        or name == "conftest.py"
    )
