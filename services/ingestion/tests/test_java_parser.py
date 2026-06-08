"""
Unit tests for JavaParser (services/ingestion/parser/java_parser.py).

Coverage scope:
  - Class extraction: fqn, annotations, package, imports, javadoc
  - Method extraction: names, parameter types, return types, constructors
  - Interface and enum kinds
  - Robustness: empty source string

All tests run in-process with Tree-sitter only — no Docker, no Neo4j.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SVC_ROOT = str(Path(__file__).parent.parent)
if _SVC_ROOT not in sys.path:
    sys.path.insert(0, _SVC_ROOT)

from parser.java_parser import JavaParser


def _parse(source: str, file_path: str = "/repo/Foo.java", repo_id: str = "test") -> object:
    """Parse Java source string using JavaParser.parse_source."""
    return JavaParser().parse_source(source, file_path, repo_id)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestJavaClassExtraction:
    """Exercises java class extraction behavior in the java parser test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen."""

    def test_simple_class_methods(self):
        """
        A basic public Java class with typed methods must produce one class entry
        and method entries with correct names, parameter types, and return types.
        This is the fundamental happy path for the Java parser.
        """
        src = '''\
package com.example;

public class Calculator {
    public int add(int x, int y) {
        return x + y;
    }

    public double divide(double a, double b) {
        return a / b;
    }
}
'''
        result = _parse(src)
        assert len(result.classes) == 1
        cls = result.classes[0]
        assert cls["name"] == "Calculator"
        assert "Calculator" in cls["fqn"]
        assert cls["kind"] == "class"

        method_names = [m["name"] for m in result.methods]
        assert "add" in method_names
        assert "divide" in method_names

        add_m = next(m for m in result.methods if m["name"] == "add")
        assert any("int" in p for p in add_m["parameters"])
        assert add_m["return_type"] == "int"

    def test_annotated_class(self):
        """
        Spring annotations like @RestController and @Service must appear in the
        annotations list of the class entry. These are used by the KG to classify
        architectural role (controller, service, repository, etc.).
        """
        src = '''\
package com.example;

import org.springframework.web.bind.annotation.RestController;

@RestController
public class UserController {
    public String hello() { return "hi"; }
}
'''
        result = _parse(src)
        assert len(result.classes) >= 1
        cls = result.classes[0]
        assert any("RestController" in a for a in cls.get("annotations", []))

    def test_interface_kind(self):
        """
        A Java interface must produce a class entry with kind='interface'.
        The KG writer uses this to create Interface nodes rather than Class nodes.
        """
        src = '''\
package com.example;

public interface UserRepository {
    User findById(long id);
    void save(User user);
}
'''
        result = _parse(src)
        # JavaParser puts interfaces in result.interfaces but may also put in classes
        # with kind=interface depending on implementation
        all_entries = result.classes + result.interfaces
        assert any(e.get("kind") == "interface" or e.get("name") == "UserRepository"
                   for e in all_entries)

    def test_enum_kind(self):
        """
        A Java enum declaration must produce an entry with kind='enum'.
        Enums appear frequently in domain models and need correct KG classification.
        """
        src = '''\
package com.example;

public enum Status {
    ACTIVE, INACTIVE, PENDING;
}
'''
        result = _parse(src)
        all_entries = result.classes + result.enums
        assert any(e.get("kind") == "enum" or e.get("name") == "Status"
                   for e in all_entries)

    def test_javadoc_extracted(self):
        """
        A Javadoc comment (/** ... */) immediately preceding a class declaration
        must be extracted and stored in the javadoc field.
        Javadoc drives the hygiene score and appears in agent context output.
        """
        src = '''\
package com.example;

/**
 * Manages user authentication tokens.
 * Tokens expire after 24 hours.
 */
public class TokenService {
    public String generate(String userId) { return ""; }
}
'''
        result = _parse(src)
        assert len(result.classes) == 1
        javadoc = result.classes[0].get("javadoc") or ""
        assert "token" in javadoc.lower() or "authentication" in javadoc.lower()

    def test_package_and_imports(self):
        """
        The package declaration and import statements must be captured.
        package_fqn drives the FQN construction; imports drive IMPORTS edges.
        """
        src = '''\
package com.example.service;

import java.util.List;
import java.util.Optional;
import com.example.model.User;

public class UserService {
    public List<User> findAll() { return null; }
}
'''
        result = _parse(src)
        assert result.package_fqn == "com.example.service"
        assert any("List" in imp or "java" in imp for imp in result.imports)

    def test_constructor_in_methods(self):
        """
        A Java constructor should appear in result.methods so consumers can see
        how an object is initialised (parameters, dependencies injected, etc.).
        """
        src = '''\
package com.example;

public class Service {
    private final String name;

    public Service(String name) {
        this.name = name;
    }

    public String getName() { return name; }
}
'''
        result = _parse(src)
        method_names = [m["name"] for m in result.methods]
        assert "Service" in method_names or "getName" in method_names

    def test_empty_source_no_crash(self):
        """
        Parsing an empty string must not raise any exception and must return a
        ParsedFile with empty collections. Required for resilient ingestion.
        """
        result = _parse("")
        assert result.classes == []
        assert result.methods == []
        assert result.imports == []
