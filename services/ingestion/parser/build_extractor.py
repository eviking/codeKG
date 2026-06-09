"""
§9 Build & Test extractor.

Extracts from build files and test class structure:
- Build tool + key commands
- Test framework (JUnit 4/5, TestNG, Spring Boot Test)
- Test categories and their base classes
- Test naming patterns
- Key dependencies (frameworks, databases, messaging)
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import tree_sitter_java as tsjava
from tree_sitter import Language, Parser, Node

JAVA_LANGUAGE = Language(tsjava.language())


@dataclass
class BuildInfo:
    """Summarizes the build and test stack discovered for a repository. Watch out for default values here, because downstream prompts assume these fields are always populated sensibly."""

    build_tool: str                         # maven | gradle
    java_version: Optional[str] = None
    test_framework: str = "junit5"          # junit4 | junit5 | testng
    spring_boot_version: Optional[str] = None
    key_dependencies: list[str] = field(default_factory=list)
    build_commands: dict[str, str] = field(default_factory=dict)  # label → command


@dataclass
class TestCategory:
    """Groups tests by annotation or base-class signal. Watch out for the description text here, because it is surfaced directly in generated onboarding material."""

    annotation: str                         # e.g. @SpringBootTest, @DataJpaTest
    base_class: Optional[str]               # e.g. AbstractIntegrationTest
    description: str
    example_classes: list[str] = field(default_factory=list)


WELL_KNOWN_TEST_ANNOTATIONS = {
    "@SpringBootTest": "Full application context integration test",
    "@DataJpaTest": "JPA slice test — only loads JPA layer, uses in-memory DB",
    "@WebMvcTest": "MVC slice test — only loads web layer",
    "@RestClientTest": "REST client slice test",
    "@DataMongoTest": "MongoDB slice test",
    "@DataRedisTest": "Redis slice test",
    "@ExtendWith(MockitoExtension.class)": "Pure unit test with Mockito mocks",
    "@RunWith(MockitoJUnitRunner.class)": "JUnit 4 unit test with Mockito mocks",
    "@TestContainers": "Integration test using Docker containers via Testcontainers",
    "@Testcontainers": "Integration test using Docker containers via Testcontainers",
}

FRAMEWORK_SIGNALS = {
    "spring-boot": "Spring Boot",
    "spring-web": "Spring MVC",
    "spring-webflux": "Spring WebFlux (reactive)",
    "spring-data-jpa": "Spring Data JPA",
    "spring-data-mongodb": "Spring Data MongoDB",
    "spring-kafka": "Spring Kafka",
    "spring-security": "Spring Security",
    "quarkus": "Quarkus",
    "micronaut": "Micronaut",
    "hibernate": "Hibernate ORM",
    "jackson": "Jackson JSON",
    "gson": "Gson JSON",
    "grpc": "gRPC",
    "kafka-clients": "Apache Kafka",
    "postgresql": "PostgreSQL JDBC",
    "mysql": "MySQL JDBC",
    "mongodb": "MongoDB driver",
    "redis": "Redis client",
    "elasticsearch": "Elasticsearch client",
    "testcontainers": "Testcontainers",
    "mockito": "Mockito",
    "assertj": "AssertJ",
    "lombok": "Lombok",
    "mapstruct": "MapStruct",
    "openapi": "OpenAPI / Swagger",
    "micrometer": "Micrometer metrics",
}


def _text(node: Node, src: bytes) -> str:
    return src[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


class BuildExtractor:
    """Inspects repository build files and test layouts to infer tooling. Watch out for mixed-language repos here, because this extractor is optimized for Java conventions and falls back heuristically elsewhere."""


    def __init__(self):
        self._parser = Parser(JAVA_LANGUAGE)

    def extract(self, repo_path: str) -> tuple[BuildInfo, list[TestCategory]]:
        root = Path(repo_path)
        build_info = self._extract_build_info(root)
        test_categories = self._extract_test_categories(root, build_info)
        return build_info, test_categories

    # ------------------------------------------------------------------

    def _extract_build_info(self, root: Path) -> BuildInfo:
        pom = root / "pom.xml"
        gradle = root / "build.gradle"
        gradle_kts = root / "build.gradle.kts"

        if pom.exists():
            return self._parse_pom(pom)
        elif gradle.exists() or gradle_kts.exists():
            gf = gradle_kts if gradle_kts.exists() else gradle
            return self._parse_gradle(root, gf)

        # Node.js / JavaScript / TypeScript project
        if (root / "package.json").exists():
            return self._parse_package_json(root)

        # Salesforce / Apex project
        if (root / "sfdx-project.json").exists() or (root / ".forceignore").exists():
            return self._parse_sfdx(root)

        # C++ build systems
        if (root / "CMakeLists.txt").exists():
            return self._parse_cmake(root)
        if (root / "meson.build").exists():
            return self._parse_meson(root)
        if (root / "BUILD").exists() or (root / "BUILD.bazel").exists() or (root / "WORKSPACE").exists():
            return self._parse_bazel(root)
        if (root / "Makefile").exists() or (root / "makefile").exists() or (root / "GNUmakefile").exists():
            return self._parse_makefile(root)
        if (root / "conanfile.txt").exists() or (root / "conanfile.py").exists():
            return BuildInfo(build_tool="conan")

        return BuildInfo(build_tool="unknown")

    def _parse_pom(self, pom: Path) -> BuildInfo:
        info = BuildInfo(build_tool="maven")
        info.build_commands = {
            "Build": "mvn package -DskipTests",
            "Test": "mvn test",
            "Integration test": "mvn verify",
            "Single test": "mvn test -Dtest=ClassName#methodName",
            "Clean build": "mvn clean package",
        }
        try:
            tree = ET.parse(pom)
            root = tree.getroot()
            ns = {"m": "http://maven.apache.org/POM/4.0.0"}

            def find(path):
                el = root.find(path, ns)
                if el is None:
                    el = root.find(path.replace("m:", ""))
                return el

            props = find("m:properties")
            if props is not None:
                for el in props:
                    tag = el.tag.split("}")[-1]
                    val = el.text.strip() if el.text else ""
                    if "java.version" in tag or "maven.compiler" in tag:
                        info.java_version = val
                    if "spring-boot.version" in tag or "spring.boot.version" in tag:
                        info.spring_boot_version = val

            # Collect dependency artifact IDs
            deps = root.findall(".//m:dependency/m:artifactId", ns) + \
                   root.findall(".//dependency/artifactId")
            for dep in deps:
                if dep.text:
                    artifact = dep.text.strip().lower()
                    for signal, label in FRAMEWORK_SIGNALS.items():
                        if signal in artifact:
                            if label not in info.key_dependencies:
                                info.key_dependencies.append(label)

            # Detect test framework
            all_deps_text = " ".join(d.text or "" for d in deps)
            if "junit-jupiter" in all_deps_text or "junit-platform" in all_deps_text:
                info.test_framework = "junit5"
            elif "junit" in all_deps_text:
                info.test_framework = "junit4"
            elif "testng" in all_deps_text:
                info.test_framework = "testng"

        except (OSError, ET.ParseError):
            pass
        return info

    def _parse_gradle(self, root: Path, gradle_file: Path) -> BuildInfo:
        info = BuildInfo(build_tool="gradle")
        wrapper = root / "gradlew"
        cmd = "./gradlew" if wrapper.exists() else "gradle"
        info.build_commands = {
            "Build": f"{cmd} assemble",
            "Test": f"{cmd} test",
            "Single test": f"{cmd} test --tests 'com.example.MyTest'",
            "Check": f"{cmd} check",
        }
        try:
            text = gradle_file.read_text(errors="replace")

            m = re.search(r"sourceCompatibility\s*=\s*['\"]?([0-9.]+)['\"]?", text)
            if m:
                info.java_version = m.group(1)
            m = re.search(r"JavaVersion\.VERSION_(\d+)", text)
            if m:
                info.java_version = m.group(1)

            m = re.search(r"""id\s*['"]org\.springframework\.boot['"]\s+version\s+['"]([^'"]+)['"]""", text)
            if m:
                info.spring_boot_version = m.group(1)

            for signal, label in FRAMEWORK_SIGNALS.items():
                if signal in text.lower() and label not in info.key_dependencies:
                    info.key_dependencies.append(label)

            if "junit-jupiter" in text or "useJUnitPlatform" in text:
                info.test_framework = "junit5"
            elif "junit:junit" in text:
                info.test_framework = "junit4"
            elif "testng" in text.lower():
                info.test_framework = "testng"

        except OSError:
            pass
        return info

    def _parse_package_json(self, root: Path) -> BuildInfo:
        import json as _json
        info = BuildInfo(build_tool="npm")
        try:
            data = _json.loads((root / "package.json").read_text(errors="replace"))
        except (OSError, ValueError):
            return info

        scripts = data.get("scripts", {})

        # Determine package manager
        if (root / "yarn.lock").exists():
            info.build_tool = "yarn"
            pm = "yarn"
        elif (root / "pnpm-lock.yaml").exists():
            info.build_tool = "pnpm"
            pm = "pnpm"
        elif (root / "bun.lockb").exists():
            info.build_tool = "bun"
            pm = "bun"
        else:
            pm = "npm"

        # Build commands from scripts
        run = f"{pm} run" if pm != "npm" else "npm run"
        for label in ("build", "start", "dev", "test", "lint", "typecheck"):
            if label in scripts:
                info.build_commands[label.capitalize()] = f"{run} {label}"
        if "test" not in scripts:
            info.build_commands["Test"] = f"{pm} test"

        # Node/engine version
        engines = data.get("engines", {})
        if "node" in engines:
            info.java_version = f"node-{engines['node']}"

        # Key dependencies from package.json deps + devDeps
        all_deps = {}
        all_deps.update(data.get("dependencies", {}))
        all_deps.update(data.get("devDependencies", {}))

        _NODE_SIGNALS = {
            "express": "Express.js",
            "fastify": "Fastify",
            "koa": "Koa",
            "hapi": "Hapi",
            "nestjs": "NestJS",
            "@nestjs/core": "NestJS",
            "next": "Next.js",
            "nuxt": "Nuxt",
            "react": "React",
            "vue": "Vue",
            "angular": "Angular",
            "svelte": "Svelte",
            "graphql": "GraphQL",
            "apollo": "Apollo",
            "typeorm": "TypeORM",
            "sequelize": "Sequelize",
            "mongoose": "Mongoose",
            "prisma": "Prisma",
            "knex": "Knex",
            "pg": "PostgreSQL (pg)",
            "mysql2": "MySQL",
            "mongodb": "MongoDB",
            "redis": "Redis",
            "ioredis": "ioredis",
            "kafka": "Kafka",
            "amqplib": "RabbitMQ",
            "jest": "Jest",
            "mocha": "Mocha",
            "vitest": "Vitest",
            "jasmine": "Jasmine",
            "chai": "Chai",
            "supertest": "Supertest",
            "axios": "Axios",
            "socket.io": "Socket.IO",
            "winston": "Winston",
            "pino": "Pino",
            "dotenv": "dotenv",
            "webpack": "Webpack",
            "vite": "Vite",
            "esbuild": "esbuild",
            "typescript": "TypeScript",
            "zod": "Zod",
            "joi": "Joi",
            "passport": "Passport.js",
            "jsonwebtoken": "JWT",
            "bcrypt": "bcrypt",
        }
        for pkg_name in all_deps:
            name_lower = pkg_name.lower().lstrip("@")
            for signal, label in _NODE_SIGNALS.items():
                if signal in name_lower or name_lower.startswith(signal.lstrip("@")):
                    if label not in info.key_dependencies:
                        info.key_dependencies.append(label)

        # Detect test framework
        if "jest" in all_deps or "vitest" in all_deps or "mocha" in all_deps:
            info.test_framework = (
                "jest" if "jest" in all_deps else
                "vitest" if "vitest" in all_deps else "mocha"
            )

        return info

    def _parse_sfdx(self, root: Path) -> BuildInfo:
        import json as _json
        info = BuildInfo(build_tool="sfdx")
        info.build_commands = {
            "Deploy": "sf project deploy start --source-dir force-app",
            "Deploy (legacy)": "sfdx force:source:deploy -p force-app",
            "Run tests": "sf apex run test --test-level RunLocalTests",
            "Pull from org": "sf project retrieve start",
        }
        try:
            sfdx_json = (root / "sfdx-project.json").read_text(errors="replace")
            data = _json.loads(sfdx_json)
            # API version
            api_ver = data.get("sourceApiVersion")
            if api_ver:
                info.java_version = f"api-{api_ver}"  # reuse field for API version
            # Plugins / dependencies
            plugins = data.get("plugins", {})
            for key in plugins:
                info.key_dependencies.append(key)
            # Package directories
            pkg_dirs = [p.get("path", "") for p in data.get("packageDirectories", [])]
            if pkg_dirs:
                info.key_dependencies.append(f"pkg-dirs: {', '.join(pkg_dirs)}")
        except (OSError, ValueError):
            pass
        return info

    def _parse_cmake(self, root: Path) -> BuildInfo:
        info = BuildInfo(build_tool="cmake")
        info.build_commands = {
            "Configure": "cmake -B build -DCMAKE_BUILD_TYPE=Release",
            "Build": "cmake --build build",
            "Test": "ctest --test-dir build",
            "Clean": "cmake --build build --target clean",
        }
        try:
            text = (root / "CMakeLists.txt").read_text(errors="replace")
            m = re.search(r"cmake_minimum_required\s*\(\s*VERSION\s+([\d.]+)", text, re.IGNORECASE)
            if m:
                info.java_version = f"cmake-{m.group(1)}"  # reuse java_version field for cmake version
            m = re.search(r'project\s*\(\s*(\w+)', text, re.IGNORECASE)
            if m:
                pass  # project name could be stored if needed
            # Detect C++ standard
            for std in ("23", "20", "17", "14", "11"):
                if f"CMAKE_CXX_STANDARD {std}" in text or f"cxx_std_{std}" in text:
                    info.key_dependencies.append(f"C++{std}")
                    break
            # Detect test frameworks in CMakeLists
            if "gtest" in text.lower() or "googletest" in text.lower():
                info.test_framework = "gtest"
                info.key_dependencies.append("GoogleTest")
            elif "catch2" in text.lower():
                info.test_framework = "catch2"
                info.key_dependencies.append("Catch2")
            elif "boost_test" in text.lower() or "boost::unit_test" in text.lower():
                info.test_framework = "boost-test"
                info.key_dependencies.append("Boost.Test")
            # Common dependencies
            for signal, label in [
                ("boost", "Boost"), ("qt5", "Qt5"), ("qt6", "Qt6"),
                ("openssl", "OpenSSL"), ("protobuf", "Protobuf"),
                ("grpc", "gRPC"), ("abseil", "Abseil"), ("fmt", "fmtlib"),
                ("spdlog", "spdlog"), ("eigen", "Eigen"), ("opencv", "OpenCV"),
            ]:
                if signal in text.lower() and label not in info.key_dependencies:
                    info.key_dependencies.append(label)
        except OSError:
            pass
        return info

    def _parse_meson(self, root: Path) -> BuildInfo:
        info = BuildInfo(build_tool="meson")
        info.build_commands = {
            "Configure": "meson setup builddir",
            "Build": "meson compile -C builddir",
            "Test": "meson test -C builddir",
        }
        try:
            text = (root / "meson.build").read_text(errors="replace")
            for std in ("c++23", "c++20", "c++17", "c++14", "c++11"):
                if std in text:
                    info.key_dependencies.append(std.upper())
                    break
        except OSError:
            pass
        return info

    def _parse_bazel(self, root: Path) -> BuildInfo:
        info = BuildInfo(build_tool="bazel")
        info.build_commands = {
            "Build": "bazel build //...",
            "Test": "bazel test //...",
            "Run": "bazel run //:target",
        }
        return info

    def _parse_makefile(self, root: Path) -> BuildInfo:
        info = BuildInfo(build_tool="make")
        for name in ("Makefile", "makefile", "GNUmakefile"):
            mf = root / name
            if not mf.exists():
                continue
            try:
                text = mf.read_text(errors="replace")
                info.build_commands = {"Build": "make", "Test": "make test", "Clean": "make clean"}
                for std in ("c++23", "c++20", "c++17", "c++14", "c++11",
                            "-std=c++2b", "-std=c++20", "-std=c++17", "-std=c++14"):
                    if std in text:
                        label = std.replace("-std=", "").replace("c++2b", "C++23").upper()
                        if not label.startswith("C++"):
                            label = "C++" + label[3:]
                        info.key_dependencies.append(label)
                        break
            except OSError:
                pass
            break
        return info

    def _extract_test_categories(self, root: Path, build_info: BuildInfo) -> list[TestCategory]:
        categories: dict[str, TestCategory] = {}

        for java_file in root.rglob("*.java"):
            if not any(part in ("test", "tests", "it", "integration-test")
                       for part in java_file.parts):
                continue
            try:
                src = java_file.read_bytes()
            except OSError:
                continue

            tree = self._parser.parse(src)
            self._scan_test_file(tree.root_node, src, str(java_file), categories)

        return list(categories.values())

    def _scan_test_file(self, root: Node, src: bytes, file_path: str,
                        categories: dict[str, TestCategory]):
        pkg = ""
        for node in root.children:
            if node.type == "package_declaration":
                for child in node.children:
                    if child.type in ("scoped_identifier", "identifier"):
                        pkg = _text(child, src)
            elif node.type == "class_declaration":
                self._scan_test_class(node, src, pkg, file_path, categories)

    def _scan_test_class(self, class_node: Node, src: bytes, pkg: str,
                         file_path: str, categories: dict[str, TestCategory]):
        name_node = class_node.child_by_field_name("name")
        if not name_node:
            return
        class_name = _text(name_node, src)
        class_fqn = f"{pkg}.{class_name}" if pkg else class_name

        superclass_node = class_node.child_by_field_name("superclass")
        base_class = None
        if superclass_node:
            base_class = _text(superclass_node, src).replace("extends", "").strip()

        for child in class_node.children:
            if child.type != "modifiers":
                continue
            mods_text = _text(child, src)
            for ann, desc in WELL_KNOWN_TEST_ANNOTATIONS.items():
                # Match @SpringBootTest, @DataJpaTest, etc.
                ann_simple = ann.split("(")[0]
                if ann_simple in mods_text:
                    key = ann_simple
                    if key not in categories:
                        categories[key] = TestCategory(
                            annotation=ann_simple,
                            base_class=base_class,
                            description=desc,
                            example_classes=[],
                        )
                    cat = categories[key]
                    if class_fqn not in cat.example_classes:
                        cat.example_classes.append(class_fqn)
                    # Update base class if consistent
                    if base_class and cat.base_class is None:
                        cat.base_class = base_class


# ---------------------------------------------------------------------------
# Module discovery — top-level function
# ---------------------------------------------------------------------------

@dataclass
class ModuleInfo:
    """Represents one discovered module or service directory. Watch out for name and path normalization here, because later index generation uses this object to build stable file names."""

    module_id: str           # e.g. "x-pack/plugin/ml"
    name: str                # human label, e.g. "ml"
    path: str                # absolute path to submodule root
    pkg_prefix: str          # best-guess package prefix (derived from path)
    build_tool: str          # maven | gradle


def extract_modules(repo_path: str) -> list[ModuleInfo]:
    """
    Auto-discover build submodules from:
      - settings.gradle / settings.gradle.kts  (Gradle multi-project)
      - root pom.xml <modules> section           (Maven multi-module)

    Returns one ModuleInfo per discovered submodule.
    """
    root = Path(repo_path)
    modules: list[ModuleInfo] = []

    # ---- Gradle: settings.gradle or settings.gradle.kts ----
    for settings_file in ("settings.gradle", "settings.gradle.kts"):
        sf = root / settings_file
        if sf.exists():
            try:
                text = sf.read_text(errors="replace")
                seen: set[str] = set()

                def _add_gradle_module(raw: str):
                    rel = raw.replace(":", "/").lstrip("/")
                    if rel in seen:
                        return
                    seen.add(rel)
                    modules.append(ModuleInfo(
                        module_id=rel,
                        name=rel.split("/")[-1],
                        path=str(root / rel),
                        pkg_prefix=_path_to_pkg_prefix(rel),
                        build_tool="gradle",
                    ))

                # Style 1: include(':x-pack:plugin:ml') or include("server")
                for m in re.finditer(r"""include\s*\(\s*['"]([^'"]+)['"]\s*\)""", text):
                    _add_gradle_module(m.group(1))

                # Style 2: include 'x-pack:plugin:ml'  (no parens — common in ES)
                for m in re.finditer(r"""^include\s+['"]([^'"]+)['"]""", text, re.MULTILINE):
                    _add_gradle_module(m.group(1))

                # Style 3: ES pattern — a List/def variable holding project paths,
                # then `include varName.toArray(...)` or `include(*varName)`
                # Find list-literal blocks: [ 'a:b', 'c:d', ... ] that precede an include
                # We look for any quoted string containing a colon (Gradle project separator)
                # within 5000 chars before an "include projects" / "include(*" call
                if re.search(r"include\s+\w+", text):
                    for block_match in re.finditer(
                        r"\[([^\]]{10,5000})\]", text, re.DOTALL
                    ):
                        block = block_match.group(1)
                        # Only process blocks that look like project lists
                        # (majority of items must have colons or slashes)
                        candidates = re.findall(r"""['"]([^'"]{3,80})['"]""", block)
                        colon_count = sum(1 for c in candidates if ":" in c or "/" in c)
                        if candidates and colon_count / len(candidates) >= 0.5:
                            for c in candidates:
                                if ":" in c or "/" in c:
                                    _add_gradle_module(c)

            except OSError:
                pass
            break  # only one settings file

    # ---- Maven: root pom.xml <modules> ----
    pom = root / "pom.xml"
    if not modules and pom.exists():
        try:
            tree = ET.parse(pom)
            ns = {"m": "http://maven.apache.org/POM/4.0.0"}
            for mod_el in (tree.getroot().findall(".//m:modules/m:module", ns) +
                           tree.getroot().findall(".//modules/module")):
                if mod_el.text:
                    rel = mod_el.text.strip()
                    sub_path = root / rel
                    name = rel.split("/")[-1]
                    pkg_prefix = _path_to_pkg_prefix(rel)
                    modules.append(ModuleInfo(
                        module_id=rel,
                        name=name,
                        path=str(sub_path),
                        pkg_prefix=pkg_prefix,
                        build_tool="maven",
                    ))
        except (OSError, ET.ParseError):
            pass

    # ---- Filesystem fallback ----
    # For repos like ES that use dynamic helpers (addSubProjects) we can't
    # parse module paths from settings.gradle.  Walk the filesystem and treat
    # every directory that has its own build.gradle/pom.xml as a submodule.
    # Skip directories that are already covered by the parsed list above.
    # Determine build tool from root
    fs_build_tool = "gradle"
    if (root / "pom.xml").exists() and not any(
        (root / f).exists() for f in ("build.gradle", "build.gradle.kts")
    ):
        fs_build_tool = "maven"

    seen_paths = {m.path for m in modules}
    for bf in root.rglob("build.gradle"):
        subdir = bf.parent
        if subdir == root:
            continue
        # Skip hidden dirs, build output dirs, and already-covered paths
        parts = subdir.parts
        if any(p.startswith(".") or p in ("build", "out", "target", ".gradle") for p in parts):
            continue
        sub_str = str(subdir)
        if sub_str in seen_paths:
            continue
        seen_paths.add(sub_str)
        rel = str(subdir.relative_to(root))
        modules.append(ModuleInfo(
            module_id=rel,
            name=subdir.name,
            path=sub_str,
            pkg_prefix=_path_to_pkg_prefix(rel),
            build_tool=fs_build_tool,
        ))

    # ---- Salesforce: package directories from sfdx-project.json ----
    if not modules:
        sfdx_json = root / "sfdx-project.json"
        if sfdx_json.exists():
            try:
                import json as _json
                data = _json.loads(sfdx_json.read_text(errors="replace"))
                for pkg in data.get("packageDirectories", []):
                    rel = pkg.get("path", "").strip("/")
                    if not rel:
                        continue
                    sub = root / rel
                    modules.append(ModuleInfo(
                        module_id=rel,
                        name=rel.split("/")[-1],
                        path=str(sub),
                        pkg_prefix=rel.split("/")[-1],
                        build_tool="sfdx",
                    ))
            except (OSError, ValueError):
                pass

    # ---- C++: CMake subdirectory discovery ----
    # For C++ repos with no Gradle/Maven modules found above, discover subdirectories
    # that have their own CMakeLists.txt (add_subdirectory pattern).
    if not modules:
        cmake_root = root / "CMakeLists.txt"
        if cmake_root.exists():
            try:
                text = cmake_root.read_text(errors="replace")
                for m in re.finditer(r'add_subdirectory\s*\(\s*([^\s)]+)', text):
                    rel = m.group(1).strip()
                    sub = root / rel
                    if sub.is_dir():
                        modules.append(ModuleInfo(
                            module_id=rel,
                            name=rel.split("/")[-1],
                            path=str(sub),
                            pkg_prefix=rel.split("/")[-1],
                            build_tool="cmake",
                        ))
            except OSError:
                pass
        # Fallback: any subdirectory containing CMakeLists.txt is a module
        if not modules:
            for cmake_file in root.rglob("CMakeLists.txt"):
                subdir = cmake_file.parent
                if subdir == root:
                    continue
                parts = subdir.parts
                if any(p.startswith(".") or p in ("build", "out", "_build") for p in parts):
                    continue
                rel = str(subdir.relative_to(root))
                if rel not in {m.module_id for m in modules}:
                    modules.append(ModuleInfo(
                        module_id=rel,
                        name=subdir.name,
                        path=str(subdir),
                        pkg_prefix=subdir.name,
                        build_tool="cmake",
                    ))

    # ---- Node.js workspace module discovery ----
    # Workspaces field in package.json lists sub-package globs.
    # Also scan `packages/`, `apps/`, `libs/` directories for nested package.json.
    if not modules and (root / "package.json").exists():
        import json as _json
        try:
            pkg_data = _json.loads((root / "package.json").read_text(errors="replace"))
            ws_patterns = pkg_data.get("workspaces", [])
            # workspaces can be a list of globs OR {"packages": [...]}
            if isinstance(ws_patterns, dict):
                ws_patterns = ws_patterns.get("packages", [])
            seen_paths = {m.path for m in modules}
            for pattern in ws_patterns:
                # Simple glob: packages/*, apps/*, etc.
                base = pattern.rstrip("/*")
                base_dir = root / base
                if base_dir.is_dir():
                    for sub in sorted(base_dir.iterdir()):
                        if sub.is_dir() and (sub / "package.json").exists():
                            sub_str = str(sub)
                            if sub_str not in seen_paths:
                                seen_paths.add(sub_str)
                                rel = str(sub.relative_to(root))
                                modules.append(ModuleInfo(
                                    module_id=rel,
                                    name=sub.name,
                                    path=sub_str,
                                    pkg_prefix=sub.name,
                                    build_tool="npm-workspace",
                                ))
        except (OSError, ValueError):
            pass
        # Fallback: conventional monorepo dirs
        if not modules:
            for ws_dir in ("packages", "apps", "libs", "services"):
                top = root / ws_dir
                if not top.is_dir():
                    continue
                for sub in sorted(top.iterdir()):
                    if sub.is_dir() and (sub / "package.json").exists():
                        rel = str(sub.relative_to(root))
                        modules.append(ModuleInfo(
                            module_id=rel,
                            name=sub.name,
                            path=str(sub),
                            pkg_prefix=sub.name,
                            build_tool="npm-workspace",
                        ))

    # ---- Python fallback: top-level packages ----
    # If no build-tool modules found, discover Python packages as modules.
    # Walk one level deep looking for directories with __init__.py.
    # For a repo like Django, this gives: django/db, django/http, django/contrib, etc.
    if not modules:
        skip_dirs = {"build", "dist", "node_modules", ".git", "__pycache__",
                     ".tox", ".venv", "venv", "env", ".eggs", "docs", "tests"}

        def _has_python_files(d: Path) -> bool:
            return any(d.rglob("*.py"))

        def _add_package(top: Path, name: str, pkg_prefix: str):
            rel = str(top.relative_to(root))
            modules.append(ModuleInfo(
                module_id=rel,
                name=name,
                path=str(top),
                pkg_prefix=pkg_prefix,
                build_tool="python",
            ))

        for top in sorted(root.iterdir()):
            if not top.is_dir() or top.name.startswith(".") or top.name in skip_dirs:
                continue
            # Standard Python package: has __init__.py (e.g. django/)
            if (top / "__init__.py").exists():
                _add_package(top, top.name, top.name)
                # Second level sub-packages (e.g. django/db, django/contrib)
                for sub in sorted(top.iterdir()):
                    if not sub.is_dir() or sub.name.startswith("_") or sub.name in skip_dirs:
                        continue
                    if (sub / "__init__.py").exists():
                        _add_package(sub, f"{top.name}/{sub.name}", f"{top.name}.{sub.name}")

        # ---- Service-layout fallback ----
        # For microservice repos (e.g. services/ingestion/, services/api/) where
        # the top-level grouping dir has no __init__.py but its children contain
        # Python source.  Treat each named service subdirectory as a module.
        if not modules:
            SERVICE_ROOTS = {"services", "src", "apps", "packages", "libs", "modules"}
            for top in sorted(root.iterdir()):
                if not top.is_dir() or top.name not in SERVICE_ROOTS:
                    continue
                for svc in sorted(top.iterdir()):
                    if not svc.is_dir() or svc.name.startswith(".") or svc.name in skip_dirs:
                        continue
                    if _has_python_files(svc):
                        _add_package(svc, f"{top.name}/{svc.name}", svc.name)

        # ---- Shared/common directory fallback ----
        # Treat top-level non-service dirs that contain Python (but no __init__.py)
        # as logical modules if they have Python content and a meaningful name.
        if not modules:
            LOGICAL_DIRS = {"shared", "common", "lib", "core", "utils", "tools"}
            for top in sorted(root.iterdir()):
                if not top.is_dir() or top.name not in LOGICAL_DIRS:
                    continue
                if _has_python_files(top):
                    _add_package(top, top.name, top.name)

    return modules


def _path_to_pkg_prefix(rel_path: str) -> str:
    """
    Heuristic: convert a submodule path like 'x-pack/plugin/ml'
    into a likely package prefix like 'ml'.
    Returns the last path segment with hyphens removed.
    """
    return rel_path.split("/")[-1].replace("-", "").replace("_", "")
