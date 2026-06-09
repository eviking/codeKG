"""
Extracts §1 Project Identity and §2 Repository Map from build files and
directory structure — no AST parsing needed here.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional


SKIP_DIRS = {
    ".git", ".gradle", ".mvn", "target", "build", "out", "node_modules",
    ".idea", ".vscode", "__pycache__", "generated", "gen",
}


class ProjectIdentity:
    """Describes the high-level identity of a scanned project. Watch out for naming stability here, because several downstream artifacts use this object to label generated summaries."""

    def __init__(self):
        self.name: Optional[str] = None
        self.group_id: Optional[str] = None
        self.artifact_id: Optional[str] = None
        self.version: Optional[str] = None
        self.description: Optional[str] = None
        self.build_tool: Optional[str] = None       # maven | gradle | ant
        self.java_version: Optional[str] = None
        self.primary_language: str = "java"
        self.root_path: Optional[str] = None


class DirectoryEntry:
    """Represents one directory discovered while classifying repository structure. Watch out for recursive expansion here, because callers use these entries to decide what parts of a repo deserve deeper parsing."""

    def __init__(self, path: str, description: str, package_roots: list[str]):
        self.path = path
        self.description = description
        self.package_roots = package_roots  # top-level Java package prefixes found here


def extract_project_identity(repo_path: str) -> ProjectIdentity:
    root = Path(repo_path)
    identity = ProjectIdentity()
    identity.root_path = str(root)
    identity.name = root.name

    pom = root / "pom.xml"
    gradle = root / "build.gradle"
    gradle_kts = root / "build.gradle.kts"

    if pom.exists():
        identity.build_tool = "maven"
        _parse_pom(pom, identity)
        identity.primary_language = "java"
    elif gradle.exists() or gradle_kts.exists():
        identity.build_tool = "gradle"
        gf = gradle_kts if gradle_kts.exists() else gradle
        _parse_gradle(gf, identity)
        identity.primary_language = "java"
    else:
        identity.primary_language = _detect_language(root)

    return identity


def _detect_language(root: Path) -> str:
    """Detect primary language by counting source files."""
    counts: dict[str, int] = {
        "java": 0, "python": 0, "cpp": 0, "apex": 0,
        "javascript": 0, "typescript": 0,
    }
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        s = p.suffix.lower()
        if s == ".java":
            counts["java"] += 1
        elif s == ".py":
            counts["python"] += 1
        elif s in {".cpp", ".cc", ".cxx", ".c++", ".h", ".hpp", ".hh", ".hxx"}:
            counts["cpp"] += 1
        elif s in {".cls", ".trigger", ".apex"}:
            counts["apex"] += 1
        elif s in {".ts", ".tsx"}:
            counts["typescript"] += 1
        elif s in {".js", ".jsx", ".mjs", ".cjs"}:
            counts["javascript"] += 1
    # Return whichever language has the most files; default java if all zero
    return max(counts, key=lambda k: counts[k]) if any(counts.values()) else "java"


def extract_repo_map(repo_path: str) -> list[DirectoryEntry]:
    """
    Walk the top-level directories and produce a one-line description for each
    based on what it contains: src/main/java presence, test indicators,
    build files, README content, etc.
    """
    root = Path(repo_path)
    entries: list[DirectoryEntry] = []

    for item in sorted(root.iterdir()):
        if not item.is_dir() or item.name in SKIP_DIRS or item.name.startswith("."):
            continue

        description = _infer_directory_purpose(item)
        package_roots = _find_package_roots(item)
        entries.append(DirectoryEntry(
            path=str(item.relative_to(root)),
            description=description,
            package_roots=package_roots,
        ))

    return entries


# ------------------------------------------------------------------

def _parse_pom(pom_path: Path, identity: ProjectIdentity):
    try:
        tree = ET.parse(pom_path)
        root = tree.getroot()
        ns = {"m": "http://maven.apache.org/POM/4.0.0"}

        def get(tag: str) -> Optional[str]:
            el = root.find(f"m:{tag}", ns) or root.find(tag)
            return el.text.strip() if el is not None and el.text else None

        identity.group_id = get("groupId")
        identity.artifact_id = get("artifactId")
        identity.version = get("version")
        identity.description = get("description")
        if identity.artifact_id:
            identity.name = identity.artifact_id

        # Java version from properties
        props = root.find("m:properties", ns) or root.find("properties")
        if props is not None:
            for el in props:
                tag = el.tag.split("}")[-1]
                if "java.version" in tag or "maven.compiler.source" in tag:
                    identity.java_version = el.text.strip() if el.text else None
                    break
    except (OSError, ET.ParseError):
        pass


def _parse_gradle(gradle_path: Path, identity: ProjectIdentity):
    try:
        text = gradle_path.read_text(errors="replace")

        m = re.search(r"""group\s*=\s*['"]([^'"]+)['"]""", text)
        if m:
            identity.group_id = m.group(1)

        m = re.search(r"""version\s*=\s*['"]([^'"]+)['"]""", text)
        if m:
            identity.version = m.group(1)

        m = re.search(r"""description\s*=\s*['"]([^'"]+)['"]""", text)
        if m:
            identity.description = m.group(1)

        m = re.search(r"""sourceCompatibility\s*=\s*['"]?([0-9.]+)['"]?""", text)
        if m:
            identity.java_version = m.group(1)

        m = re.search(r"""JavaVersion\.VERSION_(\d+)""", text)
        if m:
            identity.java_version = m.group(1)
    except OSError:
        pass


def _infer_directory_purpose(path: Path) -> str:
    name = path.name.lower()

    # Explicit name signals
    signals = {
        "server": "Core server logic",
        "core": "Core business logic",
        "api": "API layer (REST or RPC endpoints)",
        "web": "Web layer (controllers, filters, web config)",
        "service": "Service layer (business logic)",
        "services": "Service layer (business logic)",
        "domain": "Domain model (entities, value objects, repository interfaces)",
        "model": "Data model classes",
        "repository": "Data access layer (repositories, DAOs)",
        "repositories": "Data access layer (repositories, DAOs)",
        "persistence": "Persistence layer (JPA entities, repositories)",
        "infrastructure": "Infrastructure adapters (DB, messaging, external APIs)",
        "client": "Client libraries or API consumers",
        "common": "Shared utilities and cross-cutting concerns",
        "shared": "Shared utilities and cross-cutting concerns",
        "util": "Utility classes",
        "utils": "Utility classes",
        "config": "Configuration classes",
        "configuration": "Configuration classes",
        "security": "Security configuration and filters",
        "auth": "Authentication and authorisation",
        "test": "Test infrastructure and base classes",
        "tests": "Test suite",
        "integration": "Integration tests",
        "e2e": "End-to-end tests",
        "benchmark": "Performance benchmarks",
        "benchmarks": "Performance benchmarks",
        "migration": "Database migrations",
        "migrations": "Database migrations",
        "scripts": "Build and operational scripts",
        "docs": "Documentation",
        "dist": "Distribution / packaging",
        "distribution": "Distribution packaging (tar, deb, docker)",
        "plugin": "Plugin framework or specific plugin",
        "plugins": "Optional plugin modules",
        "module": "Feature module",
        "modules": "Optional feature modules",
        "proto": "Protobuf / gRPC schema definitions",
        "grpc": "gRPC service definitions and generated stubs",
        "kafka": "Kafka producers, consumers, and configuration",
        "messaging": "Messaging infrastructure (queues, events)",
        "event": "Event definitions and handlers",
        "events": "Event definitions and handlers",
    }

    for key, desc in signals.items():
        if key == name or name.startswith(key):
            return desc

    # Probe contents for clues
    has_main_java = (path / "src" / "main" / "java").exists()
    has_test_java = (path / "src" / "test" / "java").exists()
    has_pom = (path / "pom.xml").exists()
    has_gradle = (path / "build.gradle").exists() or (path / "build.gradle.kts").exists()
    has_readme = any(path.glob("README*"))

    if has_readme:
        readme = next(path.glob("README*"))
        try:
            first_line = readme.read_text(errors="replace").split("\n")[0].strip("# ").strip()
            if first_line and len(first_line) < 120:
                return first_line
        except OSError:
            pass

    if has_main_java and has_test_java:
        return "Java module with source and tests"
    if has_main_java:
        return "Java module"
    if has_test_java:
        return "Test module"
    if has_pom or has_gradle:
        return "Build sub-module"

    return "—"


def _find_package_roots(path: Path) -> list[str]:
    """Find the top-level Java package prefixes declared in this directory subtree."""
    packages: set[str] = set()
    for java_file in path.rglob("*.java"):
        if any(skip in java_file.parts for skip in SKIP_DIRS):
            continue
        try:
            text = java_file.read_text(errors="replace", encoding="utf-8")
            m = re.search(r"^\s*package\s+([\w.]+)\s*;", text, re.MULTILINE)
            if m:
                pkg = m.group(1)
                # Keep only the top 2 segments (e.g. com.example)
                parts = pkg.split(".")
                top = ".".join(parts[:2]) if len(parts) >= 2 else pkg
                packages.add(top)
        except OSError:
            pass
        if len(packages) >= 5:  # cap to avoid reading entire tree
            break
    return sorted(packages)
