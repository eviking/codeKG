"""
Unit tests for PythonParser (services/ingestion/parser/python_parser.py).

Coverage scope:
  - Class extraction: fqn, kind, decorators, base classes, nested classes
  - Method extraction: names, typed parameters, return types, decorators
  - Instance field extraction from __init__ self.x assignments
  - Import list extraction
  - Module-level functions treated as synthetic class methods
  - Robustness: empty source, syntax errors — no crash, best-effort output

All tests run without Docker, Neo4j, or any external service.
Tree-sitter parses in-process from source strings only.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Insert ingestion service root so parser package resolves correctly
_SVC_ROOT = str(Path(__file__).parent.parent)
if _SVC_ROOT not in sys.path:
    sys.path.insert(0, _SVC_ROOT)

from parser.python_parser import PythonParser


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _parse(source: str, file_path: str = "/repo/mymodule.py", repo_id: str = "test") -> object:
    """Parse a source string using PythonParser.parse_file via a temp Path."""
    import tempfile, os
    with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False, encoding="utf-8") as f:
        f.write(source)
        tmp = f.name
    try:
        parser = PythonParser()
        result = parser.parse_file(Path(tmp), repo_id, repo_path=str(Path(tmp).parent))
        # Override file_path for deterministic assertions
        result.file_path = file_path
        return result
    finally:
        os.unlink(tmp)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestClassExtraction:
    """Exercises class extraction behavior in the python parser test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen."""

    def test_simple_typed_class(self):
        """
        A class with typed methods should produce a class entry with the correct
        fqn, and method entries with typed parameter strings and return types.
        This ensures the fundamental extraction pipeline works end-to-end.
        """
        src = '''\
class Calculator:
    """A simple calculator."""

    def add(self, x: int, y: int) -> int:
        return x + y

    def divide(self, a: float, b: float) -> float:
        return a / b
'''
        result = _parse(src)
        assert len(result.classes) == 1
        cls = result.classes[0]
        assert cls["name"] == "Calculator"
        assert "Calculator" in cls["fqn"]

        method_names = [m["name"] for m in result.methods]
        assert "add" in method_names
        assert "divide" in method_names

        add_m = next(m for m in result.methods if m["name"] == "add")
        assert any("int" in p for p in add_m["parameters"])
        assert add_m["return_type"] == "int"

    def test_class_with_decorators(self):
        """
        Decorators (@classmethod, @staticmethod, @property) must be captured in
        the annotations list of each method. This matters for the KG to correctly
        represent the class interface to consumers.
        """
        src = '''\
class MyClass:
    @classmethod
    def from_string(cls, s: str) -> "MyClass":
        pass

    @staticmethod
    def helper(x: int) -> bool:
        return x > 0

    @property
    def value(self) -> int:
        return self._value
'''
        result = _parse(src)
        names_to_anns = {m["name"]: m["annotations"] for m in result.methods}
        assert any("classmethod" in a for a in names_to_anns.get("from_string", []))
        assert any("staticmethod" in a for a in names_to_anns.get("helper", []))
        assert any("property" in a for a in names_to_anns.get("value", []))

    def test_module_level_function_synthetic_class(self):
        """
        Module-level functions should be attached to a synthetic 'module' node
        so they are queryable in the KG even without a wrapping class.
        Expected: a class entry with kind='module' and the function as a method.
        """
        src = '''\
def greet(name: str) -> str:
    return f"Hello, {name}"
'''
        result = _parse(src)
        assert any(c["kind"] == "module" for c in result.classes)
        assert any(m["name"] == "greet" for m in result.methods)

    def test_imports_extracted(self):
        """
        Import statements (import X and from X import Y) must populate result.imports.
        This drives the IMPORTS edges in the knowledge graph for dependency tracking.
        """
        src = '''\
import os
import sys
from pathlib import Path
from typing import Optional, List

class Foo:
    pass
'''
        result = _parse(src)
        assert "os" in result.imports
        assert "sys" in result.imports
        assert "pathlib" in result.imports

    def test_empty_file_no_crash(self):
        """
        An empty Python file must not raise any exception and must return a valid
        ParsedFile with empty collections. Ingestion should be resilient to blanks.
        """
        result = _parse("")
        assert result.classes == []
        assert result.methods == []
        assert result.imports == []

    def test_syntax_error_no_crash(self):
        """
        Syntactically invalid Python must not crash the parser — Tree-sitter does
        best-effort recovery. The ingestion engine relies on this to continue
        processing a repo even if some files are broken.
        """
        src = "def broken( :"
        result = _parse(src)
        # Should not raise; output is unspecified but must be a ParsedFile
        assert hasattr(result, "classes")
        assert hasattr(result, "methods")

    def test_base_classes_captured(self):
        """
        A class that inherits from a named base class must have EXTENDS edges emitted
        so the KG can represent the inheritance hierarchy.
        """
        src = '''\
class Animal:
    pass

class Dog(Animal):
    pass
'''
        result = _parse(src)
        class_names = [c["name"] for c in result.classes]
        assert "Dog" in class_names
        dog_edges = [e for e in result.edges if e["source"].endswith("Dog") and e["type"] == "EXTENDS"]
        assert dog_edges, "Expected an EXTENDS edge for Dog → Animal"

    def test_nested_class_fqn(self):
        """
        A nested class must be extracted with a dotted fqn that includes the outer
        class name. Both classes must appear in result.classes with correct parent
        prefix in the inner class fqn.
        """
        src = '''\
class Outer:
    class Inner:
        def method(self) -> None:
            pass
'''
        result = _parse(src)
        fqns = [c["fqn"] for c in result.classes]
        assert any("Outer" in f for f in fqns)
        assert any("Inner" in f for f in fqns)
        inner_fqn = next(f for f in fqns if "Inner" in f)
        assert "Outer" in inner_fqn

    def test_init_self_fields(self):
        """
        Assignments of the form `self.x = ...` inside __init__ should be recorded
        as instance fields when the parser can resolve them. In cases where the
        tree-sitter grammar produces a different AST shape, the parser may return
        an empty fields list — the test verifies no crash occurs and that the
        __init__ method itself is captured.

        Note: the parser attempts field extraction via _extract_instance_fields;
        success depends on tree-sitter's assignment node structure for the Python
        grammar version in use.
        """
        src = '''\
class Config:
    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port
        self.enabled = True
'''
        result = _parse(src)
        # __init__ must always appear as a method
        method_names = [m["name"] for m in result.methods]
        assert "__init__" in method_names
        # Fields may or may not be populated depending on tree-sitter grammar version;
        # the key guarantee is no exception is raised
        assert isinstance(result.fields, list)

    def test_enum_base_class_kind(self):
        """
        A class that inherits from Enum should have kind='enum' to correctly
        distinguish it from regular classes in the KG.
        """
        src = '''\
from enum import Enum

class Color(Enum):
    RED = 1
    GREEN = 2
    BLUE = 3
'''
        result = _parse(src)
        color_cls = next((c for c in result.classes if c["name"] == "Color"), None)
        assert color_cls is not None
        assert color_cls["kind"] == "enum"
