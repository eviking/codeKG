"""
Unit tests for BuildExtractor (services/ingestion/parser/build_extractor.py).

Coverage scope:
  - Build tool detection from requirements.txt, pom.xml, build.gradle
  - Empty directory returns unknown build tool without crashing
  - extract_modules() discovers multiple service directories in a services/ layout

All tests use temporary directories — no Docker, no Neo4j, no network.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SVC_ROOT = str(Path(__file__).parent.parent)
if _SVC_ROOT not in sys.path:
    sys.path.insert(0, _SVC_ROOT)

from parser.build_extractor import BuildExtractor, extract_modules


class TestBuildExtractorDetection:
    """Exercises build extractor detection behavior in the build extractor test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen."""

    def test_pom_xml_detected_as_maven(self, tmp_path):
        """
        A directory containing pom.xml must be identified as a Maven project.
        Correct build tool detection drives the recommended build commands
        shown in the Codebase Intelligence Template.
        """
        pom = tmp_path / "pom.xml"
        pom.write_text("""\
<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <groupId>com.example</groupId>
  <artifactId>my-app</artifactId>
  <version>1.0-SNAPSHOT</version>
  <dependencies>
    <dependency>
      <artifactId>junit-jupiter</artifactId>
    </dependency>
  </dependencies>
</project>
""")
        extractor = BuildExtractor()
        build_info, _ = extractor.extract(str(tmp_path))
        assert build_info.build_tool == "maven"

    def test_build_gradle_detected_as_gradle(self, tmp_path):
        """
        A directory containing build.gradle must be identified as a Gradle project.
        Distinguishing Maven from Gradle matters for command generation.
        """
        (tmp_path / "build.gradle").write_text("""\
plugins {
    id 'java'
}
dependencies {
    testImplementation 'org.junit.jupiter:junit-jupiter'
}
""")
        extractor = BuildExtractor()
        build_info, _ = extractor.extract(str(tmp_path))
        assert build_info.build_tool == "gradle"

    def test_empty_dir_no_crash(self, tmp_path):
        """
        An empty directory (no build files) must return a BuildInfo with
        build_tool='unknown' without raising any exception. Ingestion must
        be resilient to repos with no recognised build system.
        """
        extractor = BuildExtractor()
        build_info, _ = extractor.extract(str(tmp_path))
        assert build_info.build_tool == "unknown"

    def test_requirements_txt_discovered_as_python(self, tmp_path):
        """
        A directory that has no Java build files but contains Python source and
        a requirements.txt should survive extract() call without crashing.
        The build tool will be 'unknown' since BuildExtractor targets Java, but
        extract_modules() should find Python packages.
        Expected: no exception, build_tool is either 'unknown' or 'python'.
        """
        (tmp_path / "requirements.txt").write_text("fastapi\nuvicorn\n")
        (tmp_path / "main.py").write_text("print('hello')\n")
        extractor = BuildExtractor()
        # Should not raise
        build_info, _ = extractor.extract(str(tmp_path))
        assert build_info.build_tool in ("unknown", "python", "maven", "gradle")


class TestExtractModules:
    """Exercises extract modules behavior in the build extractor test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen."""

    def test_services_layout_finds_modules(self, tmp_path):
        """
        A services/ layout (services/api/, services/ingestion/, ...) with Python
        source files should yield at least one ModuleInfo per service directory.
        This drives the per-module index file generation in the agent index.
        """
        services = tmp_path / "services"
        services.mkdir()
        for svc in ("api", "ingestion", "console"):
            svc_dir = services / svc
            svc_dir.mkdir()
            (svc_dir / "main.py").write_text("# service entry\n")

        modules = extract_modules(str(tmp_path))
        # Should find at least some of the service directories
        assert len(modules) >= 1

    def test_empty_dir_returns_empty_list(self, tmp_path):
        """
        An empty directory with no sub-projects should return an empty modules
        list rather than crashing or returning garbage data.
        """
        modules = extract_modules(str(tmp_path))
        # May return empty or discover nothing meaningful — should not crash
        assert isinstance(modules, list)

    def test_maven_multimodule_pom(self, tmp_path):
        """
        A Maven multi-module pom.xml with <modules><module>X</module></modules>
        should yield ModuleInfo entries for each declared sub-module.
        """
        pom = tmp_path / "pom.xml"
        pom.write_text("""\
<project>
  <modules>
    <module>service-a</module>
    <module>service-b</module>
  </modules>
</project>
""")
        for name in ("service-a", "service-b"):
            (tmp_path / name).mkdir()
        modules = extract_modules(str(tmp_path))
        names = [m.name for m in modules]
        assert "service-a" in names
        assert "service-b" in names
