from __future__ import annotations

import pytest

from contextsmith.languages import is_test_path, language_for
from contextsmith.parser import parse
from contextsmith.text import query_terms, split_identifier

SAMPLES = {
    "python": (b'''
import os
from pkg.util import helper

class Repo:
    """Stores things."""
    def save(self, item):
        helper(item)
        os.path.join("a", "b")

def top():
    return Repo().save(1)
''', {"Repo": "class", "save": "method", "top": "function"}, {"helper", "join", "Repo", "save"}, {"os", "pkg.util"}),
    "javascript": (b'''
import { api } from "./api";
// Loads a user.
function loadUser(id) { return api.get(id); }
const render = (u) => format(u);
class View { show() { render(1); } }
''', {"loadUser": "function", "render": "function", "View": "class", "show": "method"},
        {"get", "format", "render"}, {"./api"}),
    "typescript": (b'''
import { db } from "../db";
interface User { id: number }
export class UserService {
  find(id: number): User { return db.query(id); }
}
type Id = number;
''', {"User": "interface", "UserService": "class", "find": "method", "Id": "type"}, {"query"}, {"../db"}),
    "java": (b'''
import java.util.List;
public class OrderService {
  public Order place(Cart c) { return repo.save(new Order(c)); }
}
''', {"OrderService": "class", "place": "method"}, {"save", "Order"}, {"java.util.List"}),
    "go": (b'''
package main
import "fmt"
type Server struct{}
func (s *Server) Start() { fmt.Println("hi"); run() }
func run() {}
''', {"Server": "type", "Start": "method", "run": "function"}, {"Println", "run"}, {"fmt"}),
    "rust": (b'''
use crate::store::Db;
struct Cache {}
impl Cache {
    fn get(&self) -> u32 { compute(1) }
}
fn compute(x: u32) -> u32 { x }
''', {"Cache": "impl", "get": "method", "compute": "function"}, {"compute"}, {"crate::store::Db"}),
}


@pytest.mark.parametrize("language", sorted(SAMPLES))
def test_each_language_yields_symbols_calls_and_imports(language):
    source, symbols, calls, imports = SAMPLES[language]
    parsed = parse(source, language)
    found = {s.name: s.kind for s in parsed.symbols}
    for name, kind in symbols.items():
        assert name in found, (language, name, found)
        if language != "rust" or name != "Cache":
            assert found[name] == kind, (language, name, found[name])
    assert calls <= {c for _, c in parsed.calls}, (language, parsed.calls)
    assert imports <= set(parsed.imports), (language, parsed.imports)


def test_methods_get_qualified_names_docs_and_line_ranges():
    parsed = parse(SAMPLES["python"][0], "python")
    save = next(s for s in parsed.symbols if s.name == "save")
    assert save.qualname == "Repo.save"
    assert save.signature.startswith("def save(self, item)")
    repo = next(s for s in parsed.symbols if s.name == "Repo")
    assert repo.doc == "Stores things."
    assert repo.start_line < save.start_line <= save.end_line <= repo.end_line


def test_calls_are_attributed_to_the_enclosing_function():
    parsed = parse(SAMPLES["python"][0], "python")
    by_index = {i: s.name for i, s in enumerate(parsed.symbols)}
    callers = {by_index.get(i) for i, name in parsed.calls if name == "helper"}
    assert callers == {"save"}


def test_identifier_splitting_and_query_terms():
    assert split_identifier("getUserName") == ["get", "user", "name"]
    assert split_identifier("parse_HTTPResponse") == ["parse", "http", "response"]
    terms = query_terms("Calling apply_discount() with a coupon returns the wrong total")
    assert terms[0] == "apply_discount"
    assert "the" not in terms and "coupon" in terms


def test_language_and_test_detection():
    assert language_for("src/app/main.tsx") == "tsx"
    assert language_for("README.md") is None
    assert is_test_path("tests/test_cart.py") and is_test_path("pkg/foo_test.go")
    assert not is_test_path("shop/cart.py")
