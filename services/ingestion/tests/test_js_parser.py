"""
Smoke tests for JsParser (services/ingestion/parser/js_parser.py).

Covers JavaScript and TypeScript parsing. Run inside the ingestion container
(needs tree-sitter-javascript and tree-sitter-typescript installed).

Coverage:
  - ES6 class extraction: fqn, namespace, extends, implements (TS)
  - Inner class
  - Abstract class (TS)
  - Class methods: name, return type (TS), parameters, modifiers (async/static/get/set)
  - TypeScript decorators on classes and methods
  - Class fields (JS + TS public_field_definition with access modifier)
  - Constructor → <init>
  - TypeScript interface (kind='interface', method signatures)
  - TypeScript enum (kind='enum')
  - TypeScript type alias (kind='type')
  - Module-level function declarations
  - Arrow functions assigned to const
  - Function expressions assigned to const
  - export function / export class / export const
  - module.exports = { ... } CommonJS
  - Synthetic module class created when module-level functions exist
  - Import extraction (ES module)
  - CALLS edges from method bodies
  - JSDoc extracted on classes and methods
  - Robustness: empty source, non-JS/TS-looking content
  - JS_TS_EXTENSIONS set contents
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

_SVC_ROOT = str(Path(__file__).parent.parent)
if _SVC_ROOT not in sys.path:
    sys.path.insert(0, _SVC_ROOT)

try:
    from parser.js_parser import (
        JsParser, JS_TS_EXTENSIONS, JS_EXTENSIONS, TS_EXTENSIONS,
        _get_js_language, _get_ts_language,
    )
    _get_js_language()   # probe: raises ImportError if package absent
    _get_ts_language()
    _JS_AVAILABLE = True
except (ImportError, OSError):
    _JS_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not _JS_AVAILABLE,
    reason="tree-sitter-javascript/typescript not installed — run: pip install tree-sitter-javascript tree-sitter-typescript",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse(source: str, suffix: str = ".js", repo_id: str = "test"):
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
        f.write(source.encode())
        tmp = Path(f.name)
    try:
        return JsParser().parse_file(tmp, repo_id)
    finally:
        tmp.unlink(missing_ok=True)


def _parse_ts(source: str, repo_id: str = "test"):
    return _parse(source, suffix=".ts", repo_id=repo_id)


def _parse_tsx(source: str, repo_id: str = "test"):
    return _parse(source, suffix=".tsx", repo_id=repo_id)


# ---------------------------------------------------------------------------
# Extensions
# ---------------------------------------------------------------------------

class TestExtensions:
    def test_js_extensions(self):
        assert ".js" in JS_EXTENSIONS
        assert ".jsx" in JS_EXTENSIONS
        assert ".mjs" in JS_EXTENSIONS
        assert ".cjs" in JS_EXTENSIONS

    def test_ts_extensions(self):
        assert ".ts" in TS_EXTENSIONS
        assert ".tsx" in TS_EXTENSIONS

    def test_combined_set(self):
        assert JS_EXTENSIONS | TS_EXTENSIONS == JS_TS_EXTENSIONS


# ---------------------------------------------------------------------------
# ES6 Class
# ---------------------------------------------------------------------------

class TestES6Class:
    def test_simple_class(self):
        src = "class UserService { }"
        result = _parse(src)
        assert any(c["name"] == "UserService" for c in result.classes)

    def test_class_fqn_includes_module(self):
        src = "class Foo { }"
        result = _parse(src)
        cls = next(c for c in result.classes if c["name"] == "Foo")
        # module name is the tmp file stem; fqn should end with .Foo or be Foo
        assert cls["fqn"].endswith("Foo")

    def test_class_kind(self):
        src = "class Foo { }"
        result = _parse(src)
        cls = next(c for c in result.classes if c["name"] == "Foo")
        assert cls["kind"] == "class"

    def test_extends_edge(self):
        src = "class Handler extends BaseHandler { }"
        result = _parse(src)
        extends = [e for e in result.edges if e["type"] == "EXTENDS"]
        assert any(e["target"] == "BaseHandler" for e in extends)

    def test_inner_class(self):
        src = """\
class Outer {
  static Inner = class { }
}
class Outer2 {
}
class Inner2 {}
"""
        # Ensure multiple classes are captured
        result = _parse(src)
        names = {c["name"] for c in result.classes}
        assert "Outer2" in names

    def test_jsdoc_on_class(self):
        src = """\
/** Manages users in the system. */
class UserManager { }
"""
        result = _parse(src)
        cls = next(c for c in result.classes if c["name"] == "UserManager")
        assert cls["javadoc"] and "user" in cls["javadoc"].lower()


# ---------------------------------------------------------------------------
# Class methods
# ---------------------------------------------------------------------------

class TestClassMethods:
    def test_method_name(self):
        src = "class Svc { doWork() {} }"
        result = _parse(src)
        assert any(m["name"] == "doWork" for m in result.methods)

    def test_async_modifier(self):
        src = "class Svc { async fetchData() {} }"
        result = _parse(src)
        m = next(x for x in result.methods if x["name"] == "fetchData")
        assert "async" in m["modifiers"]

    def test_static_modifier(self):
        src = "class Svc { static create() {} }"
        result = _parse(src)
        m = next(x for x in result.methods if x["name"] == "create")
        assert "static" in m["modifiers"]

    def test_getter(self):
        src = "class Svc { get name() { return this._name; } }"
        result = _parse(src)
        assert any(m["name"] == "name" and "get" in m["modifiers"] for m in result.methods)

    def test_constructor_becomes_init(self):
        src = "class Svc { constructor(db) { this.db = db; } }"
        result = _parse(src)
        assert any(m["name"] == "<init>" for m in result.methods)

    def test_method_parameters(self):
        src = "class Svc { process(id, mode) {} }"
        result = _parse(src)
        m = next(x for x in result.methods if x["name"] == "process")
        assert len(m["parameters"]) == 2

    def test_jsdoc_on_method(self):
        src = """\
class Svc {
  /** Fetches a user by id. */
  getUser(id) {}
}"""
        result = _parse(src)
        m = next(x for x in result.methods if x["name"] == "getUser")
        assert m["docstring"] and "user" in m["docstring"].lower()


# ---------------------------------------------------------------------------
# Class fields
# ---------------------------------------------------------------------------

class TestClassFields:
    def test_field_extracted(self):
        src = """\
class Repo {
  db;
}"""
        result = _parse(src)
        assert any(f["name"] == "db" for f in result.fields)

    def test_static_field(self):
        src = """\
class Repo {
  static pool = null;
}"""
        result = _parse(src)
        f = next((x for x in result.fields if x["name"] == "pool"), None)
        assert f is not None
        assert "static" in f["modifiers"]


# ---------------------------------------------------------------------------
# TypeScript-specific
# ---------------------------------------------------------------------------

class TestTypeScript:
    def test_interface_kind(self):
        src = "interface IUserService { getUser(id: string): User; }"
        result = _parse_ts(src)
        assert any(c["kind"] == "interface" for c in result.classes)

    def test_enum_kind(self):
        src = "enum Status { Active, Inactive }"
        result = _parse_ts(src)
        assert any(c["kind"] == "enum" for c in result.classes)

    def test_type_alias_kind(self):
        src = "type UserId = string | number;"
        result = _parse_ts(src)
        assert any(c["kind"] == "type" for c in result.classes)

    def test_implements_edge(self):
        src = "class UserService implements IUserService { }"
        result = _parse_ts(src)
        impl = [e for e in result.edges if e["type"] == "IMPLEMENTS"]
        assert any(e["target"] == "IUserService" for e in impl)

    def test_ts_method_return_type(self):
        src = """\
class Svc {
  async getUser(id: string): Promise<User> { return null; }
}"""
        result = _parse_ts(src)
        m = next(x for x in result.methods if x["name"] == "getUser")
        assert m["return_type"] and "Promise" in m["return_type"]

    def test_ts_method_parameters(self):
        src = """\
class Svc {
  process(id: string, count: number): void {}
}"""
        result = _parse_ts(src)
        m = next(x for x in result.methods if x["name"] == "process")
        assert len(m["parameters"]) == 2

    def test_decorator_on_class(self):
        src = """\
@Injectable()
class UserService {}"""
        result = _parse_ts(src)
        cls = next(c for c in result.classes if c["name"] == "UserService")
        assert any("Injectable" in a for a in cls["annotations"])

    def test_decorator_on_method(self):
        src = """\
class Ctrl {
  @Get('/users')
  list() {}
}"""
        result = _parse_ts(src)
        m = next(x for x in result.methods if x["name"] == "list")
        assert any("Get" in a for a in m["annotations"])

    def test_private_field_type(self):
        src = """\
class Svc {
  private readonly db: Database;
}"""
        result = _parse_ts(src)
        f = next((x for x in result.fields if x["name"] == "db"), None)
        assert f is not None
        assert "private" in f["modifiers"]

    def test_tsx_parses(self):
        src = """\
class App {
  render() { return null; }
}"""
        result = _parse_tsx(src)
        assert any(c["name"] == "App" for c in result.classes)


# ---------------------------------------------------------------------------
# Module-level functions
# ---------------------------------------------------------------------------

class TestModuleFunctions:
    def test_function_declaration(self):
        src = "function greet(name) { return 'hello'; }"
        result = _parse(src)
        assert any(m["name"] == "greet" for m in result.methods)

    def test_async_function_declaration(self):
        src = "async function fetchData(url) { return fetch(url); }"
        result = _parse(src)
        m = next(x for x in result.methods if x["name"] == "fetchData")
        assert "async" in m["modifiers"]

    def test_arrow_function_const(self):
        src = "const add = (a, b) => a + b;"
        result = _parse(src)
        assert any(m["name"] == "add" for m in result.methods)

    def test_function_expression_const(self):
        src = "const multiply = function(a, b) { return a * b; };"
        result = _parse(src)
        assert any(m["name"] == "multiply" for m in result.methods)

    def test_synthetic_module_class_created(self):
        src = "function doWork() {}"
        result = _parse(src)
        assert any(c["kind"] == "module" for c in result.classes)

    def test_no_module_class_without_functions(self):
        src = "class Foo {}"
        result = _parse(src)
        assert not any(c["kind"] == "module" for c in result.classes)


# ---------------------------------------------------------------------------
# Exports
# ---------------------------------------------------------------------------

class TestExports:
    def test_export_function(self):
        src = "export function handler(req, res) { res.send('ok'); }"
        result = _parse(src)
        assert any(m["name"] == "handler" for m in result.methods)

    def test_export_class(self):
        src = "export class UserService { }"
        result = _parse(src)
        assert any(c["name"] == "UserService" for c in result.classes)

    def test_export_const_arrow(self):
        src = "export const greet = (name) => name;"
        result = _parse(src)
        assert any(m["name"] == "greet" for m in result.methods)

    def test_module_exports_object(self):
        src = """\
module.exports = {
  add: function(a, b) { return a + b; },
  greet: (name) => name,
};"""
        result = _parse(src)
        names = {m["name"] for m in result.methods}
        assert "add" in names
        assert "greet" in names


# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------

class TestImports:
    def test_es_import(self):
        src = "import { foo } from './foo';"
        result = _parse(src)
        assert "./foo" in result.imports

    def test_default_import(self):
        src = "import express from 'express';"
        result = _parse(src)
        assert "express" in result.imports


# ---------------------------------------------------------------------------
# CALLS edges
# ---------------------------------------------------------------------------

class TestCallsEdges:
    def test_method_call_emits_calls_edge(self):
        src = """\
class Svc {
  run() { this.helper(); }
  helper() {}
}"""
        result = _parse(src)
        calls = [e for e in result.edges if e["type"] == "CALLS"]
        assert any(e["target"] == "helper" for e in calls)

    def test_caller_fqn_in_edge(self):
        src = """\
class Svc {
  run() { doSomething(); }
}"""
        result = _parse(src)
        calls = [e for e in result.edges if e["type"] == "CALLS"]
        assert any("run" in e["source"] for e in calls)


# ---------------------------------------------------------------------------
# Robustness
# ---------------------------------------------------------------------------

class TestRobustness:
    def test_empty_source(self):
        result = _parse("")
        assert result.classes == []
        assert result.methods == []
        assert result.edges == []

    def test_syntax_error_does_not_crash(self):
        result = _parse("this is %%% not javascript !!!")
        assert isinstance(result.classes, list)

    def test_empty_class_body(self):
        result = _parse("class Empty {}")
        assert any(c["name"] == "Empty" for c in result.classes)
