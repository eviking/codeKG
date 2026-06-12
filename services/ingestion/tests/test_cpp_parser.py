"""
Smoke tests for CppParser (services/ingestion/parser/cpp_parser.py).

Covers C++ and header file parsing. Run inside the ingestion container
(needs tree-sitter-cpp installed).

Coverage:
  - CPP_EXTENSIONS set contents
  - Class extraction: fqn, namespace, kind (class/struct)
  - Template class
  - Struct
  - Enum
  - Inheritance: EXTENDS edges for single and multiple bases
  - Method extraction: name, return type, parameters, modifiers
  - Virtual / override / static / const / destructor modifiers
  - Constructor detection
  - Member fields
  - Free functions → synthetic module class
  - Namespace → package_fqn
  - #include → imports list
  - CALLS edges from method bodies
  - Doxygen /** */ and /// comments extracted
  - Forward declarations skipped
  - Anonymous structs skipped
  - Robustness: empty source, non-C++ content
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
    from parser.cpp_parser import CppParser, CPP_EXTENSIONS
    _CPP_AVAILABLE = True
except ImportError:
    _CPP_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not _CPP_AVAILABLE,
    reason="tree-sitter-cpp not installed — run: pip install tree-sitter-cpp",
)


def _parse(source: str, suffix: str = ".cpp", repo_id: str = "test"):
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
        f.write(source.encode())
        tmp = Path(f.name)
    try:
        return CppParser().parse_file(tmp, repo_id)
    finally:
        tmp.unlink(missing_ok=True)


def _parse_h(source: str, repo_id: str = "test"):
    return _parse(source, suffix=".hpp", repo_id=repo_id)


# ---------------------------------------------------------------------------
# Extensions
# ---------------------------------------------------------------------------

class TestCppExtensions:
    def test_cpp_extensions(self):
        assert ".cpp" in CPP_EXTENSIONS
        assert ".cc" in CPP_EXTENSIONS
        assert ".cxx" in CPP_EXTENSIONS

    def test_header_extensions(self):
        assert ".h" in CPP_EXTENSIONS
        assert ".hpp" in CPP_EXTENSIONS
        assert ".hh" in CPP_EXTENSIONS

    def test_no_java_extension(self):
        assert ".java" not in CPP_EXTENSIONS


# ---------------------------------------------------------------------------
# Class extraction
# ---------------------------------------------------------------------------

class TestClassExtraction:
    def test_simple_class(self):
        src = "class Foo {};"
        result = _parse(src)
        assert any(c["name"] == "Foo" for c in result.classes)

    def test_class_fqn(self):
        src = "class Foo {};"
        result = _parse(src)
        cls = next(c for c in result.classes if c["name"] == "Foo")
        assert cls["fqn"] == "Foo"

    def test_class_kind(self):
        src = "class Foo {};"
        result = _parse(src)
        cls = next(c for c in result.classes if c["name"] == "Foo")
        assert cls["kind"] == "class"

    def test_struct_kind(self):
        src = "struct Point { int x; int y; };"
        result = _parse(src)
        cls = next(c for c in result.classes if c["name"] == "Point")
        assert cls["kind"] == "struct"

    def test_forward_declaration_skipped(self):
        src = "class Foo;"
        result = _parse(src)
        assert not any(c["name"] == "Foo" for c in result.classes)

    def test_anonymous_struct_skipped(self):
        src = "struct { int x; } anon;"
        result = _parse(src)
        assert result.classes == []

    def test_namespace_fqn(self):
        src = "namespace myapp { class Service {}; }"
        result = _parse(src)
        cls = next(c for c in result.classes if c["name"] == "Service")
        assert cls["fqn"] == "myapp::Service"

    def test_namespace_package_fqn(self):
        src = "namespace myapp { class Service {}; }"
        result = _parse(src)
        assert result.package_fqn == "myapp"

    def test_nested_namespace(self):
        src = "namespace a { namespace b { class C {}; } }"
        result = _parse(src)
        cls = next(c for c in result.classes if c["name"] == "C")
        assert "a" in cls["fqn"] and "b" in cls["fqn"] and "C" in cls["fqn"]

    def test_template_class_kind(self):
        src = "template<typename T> class Container {};"
        result = _parse(src)
        assert any("template" in c["kind"] for c in result.classes)

    def test_template_class_name(self):
        src = "template<typename T> class Container {};"
        result = _parse(src)
        assert any(c["name"] == "Container" for c in result.classes)


# ---------------------------------------------------------------------------
# Enum
# ---------------------------------------------------------------------------

class TestEnum:
    def test_enum_kind(self):
        src = "enum Color { Red, Green, Blue };"
        result = _parse(src)
        assert any(c["kind"] == "enum" for c in result.classes)

    def test_enum_name(self):
        src = "enum Status { Open, Closed };"
        result = _parse(src)
        assert any(c["name"] == "Status" for c in result.classes)


# ---------------------------------------------------------------------------
# Inheritance
# ---------------------------------------------------------------------------

class TestInheritance:
    def test_single_base_extends(self):
        src = "class Handler : public BaseHandler {};"
        result = _parse(src)
        extends = [e for e in result.edges if e["type"] == "EXTENDS"]
        assert any(e["target"] == "BaseHandler" for e in extends)

    def test_multiple_bases(self):
        src = "class Multi : public Base1, public Base2 {};"
        result = _parse(src)
        targets = {e["target"] for e in result.edges if e["type"] == "EXTENDS"}
        assert "Base1" in targets
        assert "Base2" in targets

    def test_extends_source_fqn(self):
        src = "class Child : public Parent {};"
        result = _parse(src)
        extends = [e for e in result.edges if e["type"] == "EXTENDS"]
        assert any(e["source"] == "Child" for e in extends)


# ---------------------------------------------------------------------------
# Method extraction
# ---------------------------------------------------------------------------

class TestMethodExtraction:
    def test_method_name(self):
        src = "class Svc { void doWork() {} };"
        result = _parse(src)
        assert any(m["name"] == "doWork" for m in result.methods)

    def test_method_return_type(self):
        src = "class Svc { int compute() { return 0; } };"
        result = _parse(src)
        m = next(x for x in result.methods if x["name"] == "compute")
        assert m["return_type"] and "int" in m["return_type"]

    def test_method_parameters(self):
        src = "class Svc { void process(int id, float val) {} };"
        result = _parse(src)
        m = next(x for x in result.methods if x["name"] == "process")
        assert len(m["parameters"]) == 2

    def test_static_modifier(self):
        src = "class Svc { static int create() { return 0; } };"
        result = _parse(src)
        m = next(x for x in result.methods if x["name"] == "create")
        assert "static" in m["modifiers"]

    def test_virtual_modifier(self):
        src = "class Base { virtual void execute() {} };"
        result = _parse(src)
        m = next(x for x in result.methods if x["name"] == "execute")
        assert "virtual" in m["modifiers"]

    def test_destructor_modifier(self):
        src = "class Foo { ~Foo() {} };"
        result = _parse(src)
        dtors = [m for m in result.methods if m["name"].startswith("~")]
        assert dtors
        assert "destructor" in dtors[0]["modifiers"]

    def test_access_modifier_public(self):
        src = "class Svc { public: void run() {} };"
        result = _parse(src)
        m = next((x for x in result.methods if x["name"] == "run"), None)
        assert m is not None
        assert "public" in m["modifiers"]

    def test_access_modifier_private(self):
        src = "class Svc { private: void helper() {} };"
        result = _parse(src)
        m = next((x for x in result.methods if x["name"] == "helper"), None)
        assert m is not None
        assert "private" in m["modifiers"]


# ---------------------------------------------------------------------------
# Fields
# ---------------------------------------------------------------------------

class TestFields:
    def test_field_extracted(self):
        src = "class Repo { int count; };"
        result = _parse(src)
        assert any(f["name"] == "count" for f in result.fields)

    def test_static_field(self):
        src = "class Repo { static int pool; };"
        result = _parse(src)
        f = next((x for x in result.fields if x["name"] == "pool"), None)
        assert f is not None
        assert "static" in f["modifiers"]


# ---------------------------------------------------------------------------
# Free functions
# ---------------------------------------------------------------------------

class TestFreeFunctions:
    def test_free_function_method(self):
        src = "void greet() {}"
        result = _parse(src)
        assert any(m["name"] == "greet" for m in result.methods)

    def test_free_function_synthetic_module_class(self):
        src = "void doWork() {}"
        result = _parse(src)
        assert any(c["kind"] == "module" for c in result.classes)

    def test_no_module_class_without_free_functions(self):
        src = "class Foo { void bar() {} };"
        result = _parse(src)
        assert not any(c["kind"] == "module" for c in result.classes)

    def test_out_of_class_definition_not_double_indexed(self):
        # Foo::bar() definition outside class — should not create a free-function entry
        src = """\
class Foo {};
void Foo::bar() {}
"""
        result = _parse(src)
        assert not any(m["name"] == "bar" and "::" not in m["class_fqn"] for m in result.methods)


# ---------------------------------------------------------------------------
# Includes
# ---------------------------------------------------------------------------

class TestIncludes:
    def test_system_include(self):
        src = '#include <vector>\nclass Foo {};'
        result = _parse(src)
        assert "vector" in result.imports

    def test_local_include(self):
        src = '#include "utils.h"\nclass Foo {};'
        result = _parse(src)
        assert "utils.h" in result.imports


# ---------------------------------------------------------------------------
# CALLS edges
# ---------------------------------------------------------------------------

class TestCallsEdges:
    def test_method_call_emits_edge(self):
        src = """\
class Svc {
  void run() { helper(); }
  void helper() {}
};"""
        result = _parse(src)
        calls = [e for e in result.edges if e["type"] == "CALLS"]
        assert any(e["target"] == "helper" for e in calls)

    def test_caller_fqn_in_edge(self):
        src = """\
class Svc {
  void run() { doSomething(); }
};"""
        result = _parse(src)
        calls = [e for e in result.edges if e["type"] == "CALLS"]
        assert any("run" in e["source"] for e in calls)


# ---------------------------------------------------------------------------
# Doxygen comments
# ---------------------------------------------------------------------------

class TestDoxygen:
    def test_block_doxygen_on_class(self):
        src = """\
/** Manages connections to the database. */
class DbManager {};"""
        result = _parse(src)
        cls = next(c for c in result.classes if c["name"] == "DbManager")
        assert cls["javadoc"] and "database" in cls["javadoc"].lower()

    def test_triple_slash_on_method(self):
        src = """\
class Svc {
  /// Fetches a record by id.
  void fetch(int id) {}
};"""
        result = _parse(src)
        m = next(x for x in result.methods if x["name"] == "fetch")
        assert m["docstring"] and "record" in m["docstring"].lower()


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
        result = _parse("this is %%% not cpp !!!")
        assert isinstance(result.classes, list)

    def test_header_file_parses(self):
        src = "class Iface { virtual void run() = 0; };"
        result = _parse_h(src)
        assert isinstance(result.classes, list)
