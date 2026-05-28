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
    build_tool: str                         # maven | gradle
    java_version: Optional[str] = None
    test_framework: str = "junit5"          # junit4 | junit5 | testng
    spring_boot_version: Optional[str] = None
    key_dependencies: list[str] = field(default_factory=list)
    build_commands: dict[str, str] = field(default_factory=dict)  # label → command


@dataclass
class TestCategory:
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

        except Exception:
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

        except Exception:
            pass
        return info

    def _extract_test_categories(self, root: Path, build_info: BuildInfo) -> list[TestCategory]:
        categories: dict[str, TestCategory] = {}

        for java_file in root.rglob("*.java"):
            if not any(part in ("test", "tests", "it", "integration-test")
                       for part in java_file.parts):
                continue
            try:
                src = java_file.read_bytes()
            except Exception:
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
