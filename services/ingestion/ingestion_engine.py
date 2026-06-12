"""
Ingestion engine — orchestrates full baseline scan and incremental commit updates.
Uses multi-process parsing (one process per CPU core) for full scans.
"""
from __future__ import annotations

import time
from pathlib import Path

import git

from parser.java_parser import JavaParser
from parser.python_parser import PythonParser
from parser.cpp_parser import CppParser, CPP_EXTENSIONS
from parser.apex_parser import ApexParser, APEX_EXTENSIONS
from parser.js_parser import JsParser, JS_TS_EXTENSIONS
from parser.scip_emitter import SCIPEmitter
from parser.api_extractor import ApiExtractor
from parser.concurrency_extractor import ConcurrencyExtractor
from parser.build_extractor import BuildExtractor, extract_modules
from parser.repo_structure import extract_project_identity, extract_repo_map
from kg.writer import KGWriter
from pattern_detector import detect_patterns, save_patterns_to_kg
from shared.config import cfg
from policy_scanner import scan_policies
from kg.object_model import build_object_models
from kg.enrichment import enrich_classes
from kg.call_chain import build_call_chains
from kg.hygiene import compute_hygiene
from claude_md_writer import write_claude_md

try:
    from shared.codekg_logging.codekg_logger import get_logger
except ImportError:
    import logging
    class _FallbackLogger:
        """Very small logger used when the shared logging stack is unavailable. Watch out for missing structured fields here, because this class favors resilience over feature parity."""

        def __init__(self, name): self._l = logging.getLogger(name)
        def info(self, m, **k): self._l.info(m)
        def debug(self, m, **k): self._l.debug(m)
        def warning(self, m, **k): self._l.warning(m)
        def error(self, m, **k): self._l.error(m)
        def timed(self, op, **k):
            import contextlib
            return contextlib.nullcontext()
    def get_logger(name, **k): return _FallbackLogger(name)

log = get_logger(__name__, service="ingestion")


# ------------------------------------------------------------------
# C++ concurrency extractor (regex-based, no Java AST)
# ------------------------------------------------------------------

def _extract_cpp_concurrency(file_path, parsed) -> tuple:
    """
    Regex scan a C++ source file for std::thread, std::mutex, std::async,
    std::future, and thread-safety comments. Returns (pools, asyncs, facts)
    in the same format as ConcurrencyExtractor for Java.
    """
    from parser.concurrency_extractor import ThreadPoolDeclaration, AsyncMethod, ConcurrencyFact
    import re as _re

    pools: list = []
    asyncs: list = []
    facts: list = []

    try:
        text = file_path.read_text(errors="replace")
    except OSError:
        return pools, asyncs, facts

    file_str = str(file_path)

    # For FQN attribution — use first class in file, else filename stem
    default_fqn = parsed.classes[0]["fqn"] if parsed.classes else file_path.stem

    # Thread pools: std::thread, ThreadPool, std::jthread
    for m in _re.finditer(r'\bstd::(thread|jthread)\b', text):
        line = text[:m.start()].count("\n") + 1
        pools.append(ThreadPoolDeclaration(
            class_fqn=default_fqn,
            field_name="thread",
            pool_type=f"std::{m.group(1)}",
            file_path=file_str,
            line=line,
        ))

    # Async: std::async, std::future, std::promise
    for pattern, mechanism in [
        (r'\bstd::async\b', "std::async"),
        (r'\bstd::future\b', "std::future"),
        (r'\bstd::promise\b', "std::promise"),
    ]:
        for m in _re.finditer(pattern, text):
            line = text[:m.start()].count("\n") + 1
            asyncs.append(AsyncMethod(
                class_fqn=default_fqn,
                method_name=mechanism,
                mechanism=mechanism,
                file_path=file_str,
                line=line,
            ))
            break  # one signal per file per type is enough

    # Synchronization facts: std::mutex, std::lock_guard, std::unique_lock, std::atomic
    for pattern, fact_type in [
        (r'\bstd::mutex\b', "synchronized_method"),
        (r'\bstd::lock_guard\b', "synchronized_method"),
        (r'\bstd::unique_lock\b', "synchronized_method"),
        (r'\bstd::shared_mutex\b', "synchronized_method"),
        (r'\bstd::atomic\b', "volatile_field"),
        (r'\bvolatile\b', "volatile_field"),
    ]:
        if _re.search(pattern, text):
            facts.append(ConcurrencyFact(
                class_fqn=default_fqn,
                fact_type=fact_type,
                detail=pattern.strip(r"\b").replace("\\b", ""),
                file_path=file_str,
            ))

    return pools, asyncs, facts


# ------------------------------------------------------------------
# Top-level worker function — must be defined at module level so
# multiprocessing can pickle it. Each worker gets its own parser
# instances (Tree-sitter parsers are not process-safe to share).
# ------------------------------------------------------------------

def _parse_file_worker(args: tuple) -> dict | None:
    """
    Language-aware file parser worker. Dispatches to Java, Python, or C++ parser
    based on file extension. Returns a dict with all parsed facts or None on error.
    """
    file_str, repo_id = args[:2]
    repo_path = args[2] if len(args) > 2 else ""
    file_path = Path(file_str)
    ext = file_path.suffix.lower()

    try:
        scip_doc = None
        endpoints = []
        pools, asyncs, facts = [], [], []

        if ext == ".java":
            parser = JavaParser()
            scip = SCIPEmitter()
            api_ext = ApiExtractor()
            conc_ext = ConcurrencyExtractor()
            parsed = parser.parse_file(file_path, repo_id)
            scip_doc = scip.emit(parsed)
            endpoints = api_ext.extract_file(file_path, repo_id)
            pools, asyncs, facts = conc_ext.extract_file(file_path)

        elif ext == ".py":
            parser = PythonParser()
            parsed = parser.parse_file(file_path, repo_id, repo_path=repo_path)

        elif ext in CPP_EXTENSIONS:
            parser = CppParser()
            parsed = parser.parse_file(file_path, repo_id)
            pools, asyncs, facts = _extract_cpp_concurrency(file_path, parsed)

        elif ext in APEX_EXTENSIONS:
            parser = ApexParser()
            parsed = parser.parse_file(file_path, repo_id)

        elif ext in JS_TS_EXTENSIONS:
            from parser.concurrency_extractor import AsyncMethod, ConcurrencyFact
            import re as _re
            parser = JsParser()
            parsed = parser.parse_file(file_path, repo_id)
            # Detect async/Promise-based concurrency from parsed method modifiers
            for cls in parsed.classes:
                fqn = cls.get("fqn", file_path.stem)
                for m in parsed.methods:
                    if m.get("class_fqn") == fqn and "async" in m.get("modifiers", []):
                        asyncs.append(AsyncMethod(
                            class_fqn=fqn,
                            method_name=m["name"],
                            mechanism="async/await",
                            file_path=str(file_path),
                            line=m.get("start_line", 0),
                        ))

        else:
            return None  # unsupported extension

        return {
            "parsed": parsed,
            "scip_doc": scip_doc,
            "endpoints": endpoints,
            "pools": pools,
            "asyncs": asyncs,
            "concurrency_facts": facts,
            "file": file_str,
            "error": None,
        }
    except Exception as exc:
        return {"file": file_str, "error": str(exc), "parsed": None}


class IngestionEngine:
    """Coordinates repository scans from parsing through graph writes. Watch out for batch sizing and timeout behavior here, because this class is where large-repo performance problems tend to surface first."""


    WORKER_COUNT = cfg.ingestion.worker_count if cfg.ingestion.worker_count > 0 else None
    BATCH_SIZE   = cfg.ingestion.parse_batch_size

    def __init__(self, writer: KGWriter):
        self._writer = writer
        log.info("Ingestion engine initialised",
                 workers=self.WORKER_COUNT,
                 batch_size=self.BATCH_SIZE)

    def full_scan(self, repo_path: str, repo_id: str):
        """
        Full baseline scan — producer/consumer with batched writes.
        Main thread parses files; a writer thread drains results into Neo4j in
        batches, so parse and write run concurrently without multiprocessing OOM risk.
        """

        path = Path(repo_path)

        # Directories to exclude from scanning — vendor, virtual envs, generated output
        _SKIP_DIRS = {
            ".venv", "venv", "env", ".env",
            "node_modules", "__pycache__", ".git",
            "build", "dist", ".eggs", ".tox",
            "site-packages",                    # any depth venv packages
            ".gradle", ".mvn", "target",        # Java build output
        }

        def _excluded(f: Path) -> bool:
            return any(part in _SKIP_DIRS for part in f.parts)

        source_files = [
            f for f in (
                list(path.rglob("*.java")) +
                list(path.rglob("*.py")) +
                [f for ext in CPP_EXTENSIONS for f in path.rglob(f"*{ext}")] +
                [f for ext in APEX_EXTENSIONS for f in path.rglob(f"*{ext}")] +
                [f for ext in JS_TS_EXTENSIONS for f in path.rglob(f"*{ext}")]
            )
            if not _excluded(f)
        ]
        # Deduplicate (rglob patterns can overlap on case-insensitive FS)
        source_files = list(dict.fromkeys(source_files))
        total = len(source_files)

        log.info("Full scan started",
                 repo_id=repo_id, files=total, path=repo_path)

        try:
            repo = git.Repo(repo_path)
            last_commit = repo.head.commit.hexsha if not repo.head.is_detached else None
        except Exception as exc:
            log.warning("Cannot open git repo — commit SHA unavailable",
                        repo_id=repo_id, path=repo_path, error=str(exc))
            last_commit = None
        self._writer.current_commit = last_commit or "unknown"

        with log.timed("extract_project_identity", repo_id=repo_id):
            identity = extract_project_identity(repo_path)

        with log.timed("extract_build_info", repo_id=repo_id):
            build_info, test_categories = BuildExtractor().extract(repo_path)

        with log.timed("upsert_repository", repo_id=repo_id):
            self._writer.upsert_repository(
                repo_id=repo_id,
                name=identity.name or path.name,
                path=str(path),
                language=identity.primary_language,
                java_version=identity.java_version or build_info.java_version,
                build_tool=build_info.build_tool,
                description=identity.description,
                test_framework=build_info.test_framework,
                build_commands=build_info.build_commands,
                key_dependencies=build_info.key_dependencies,
            )
            self._writer.upsert_test_categories(repo_id, test_categories)

        with log.timed("extract_repo_map", repo_id=repo_id):
            dir_entries = extract_repo_map(repo_path)
            self._writer.upsert_directory_entries(repo_id, dir_entries)

        with log.timed("extract_modules", repo_id=repo_id):
            discovered_modules = extract_modules(repo_path)
            if discovered_modules:
                self._writer.upsert_modules(repo_id, discovered_modules)
                log.info("Modules discovered",
                         repo_id=repo_id, count=len(discovered_modules))

        # ── Phase 1: Parse all files (CPU-bound, no Neo4j pressure) ──────────
        parsed_results: list = []
        endpoints_all:  list = []
        pools_all:      list = []
        asyncs_all:     list = []
        facts_all:      list = []

        completed    = 0
        parse_errors = 0
        parse_start  = time.perf_counter()

        for java_file in source_files:
            result = _parse_file_worker((str(java_file), repo_id, repo_path))

            if result is None:
                parse_errors += 1
                continue

            if result["error"]:
                parse_errors += 1
                log.warning("Parse error",
                            repo_id=repo_id,
                            file=result["file"],
                            error=result["error"])
                continue

            parsed_results.append(result["parsed"])
            if result["endpoints"]:
                endpoints_all.extend(result["endpoints"])
            if result["pools"]:
                pools_all.extend(result["pools"])
            if result["asyncs"]:
                asyncs_all.extend(result["asyncs"])
            if result["concurrency_facts"]:
                facts_all.extend(result["concurrency_facts"])
            completed += 1

            if completed % 500 == 0 or completed == total:
                pct = int(completed / total * 100)
                elapsed = round((time.perf_counter() - parse_start) * 1000)
                log.info("Parse progress",
                         repo_id=repo_id,
                         progress=f"{completed}/{total} ({pct}%)",
                         errors=parse_errors,
                         elapsed_ms=elapsed)

        parse_elapsed_ms = round((time.perf_counter() - parse_start) * 1000)
        log.info("Parse phase complete",
                 repo_id=repo_id, parsed=completed, errors=parse_errors,
                 elapsed_ms=parse_elapsed_ms)

        # ── Phase 2: Write to Neo4j in controlled batches (throttled) ────────
        write_errors = 0
        write_start  = time.perf_counter()

        for i in range(0, len(parsed_results), self.BATCH_SIZE):
            batch = parsed_results[i : i + self.BATCH_SIZE]
            try:
                self._writer.write_parsed_batch(batch)
            except Exception as exc:
                write_errors += len(batch)
                log.error("KG batch write error", repo_id=repo_id,
                          batch=i // self.BATCH_SIZE, exc=exc)
            time.sleep(0.1)  # brief pause between batches — keeps Neo4j breathing

        if endpoints_all:
            try:
                self._writer.upsert_api_endpoints(repo_id, endpoints_all)
            except Exception as exc:
                log.error("KG endpoints write error", repo_id=repo_id, exc=exc)

        if pools_all or asyncs_all or facts_all:
            try:
                self._writer.upsert_concurrency_facts(
                    repo_id, pools_all, asyncs_all, facts_all)
            except Exception as exc:
                log.error("KG concurrency write error", repo_id=repo_id, exc=exc)

        total_elapsed_ms = round((time.perf_counter() - write_start) * 1000)
        errors = parse_errors + write_errors
        rate = round(completed / ((parse_elapsed_ms + total_elapsed_ms) / 1000)) if completed else 0

        with log.timed("wire_edges", repo_id=repo_id):
            self._writer.wire_edges(repo_id)

        with log.timed("detect_patterns", repo_id=repo_id):
            try:
                pattern_results = detect_patterns(self._writer._driver, repo_id)
                save_patterns_to_kg(self._writer._driver, pattern_results, repo_id)
                log.info("Pattern detection complete",
                         repo_id=repo_id, patterns=len(pattern_results))
            except Exception as exc:
                log.warning("Pattern detection failed", repo_id=repo_id, exc=str(exc))

        with log.timed("scan_policies", repo_id=repo_id):
            try:
                policy_results = scan_policies(self._writer._driver, repo_id)
                log.info("Policy scan complete",
                         repo_id=repo_id, policies=len(policy_results))
            except Exception as exc:
                log.warning("Policy scan failed", repo_id=repo_id, exc=str(exc))

        with log.timed("build_object_models", repo_id=repo_id):
            try:
                om_count = build_object_models(self._writer._driver, repo_id)
                log.info("Object models built", repo_id=repo_id, count=om_count)
            except Exception as exc:
                log.warning("Object model build failed", repo_id=repo_id, exc=str(exc))

        with log.timed("enrich_classes", repo_id=repo_id):
            try:
                en_count = enrich_classes(self._writer._driver, repo_id)
                log.info("Class enrichment complete", repo_id=repo_id, count=en_count)
            except Exception as exc:
                log.warning("Class enrichment failed", repo_id=repo_id, exc=str(exc))

        with log.timed("build_call_chains", repo_id=repo_id):
            try:
                cc_count = build_call_chains(self._writer._driver, repo_id)
                log.info("Call chains built", repo_id=repo_id, count=cc_count)
            except Exception as exc:
                log.warning("Call chain build failed", repo_id=repo_id, exc=str(exc))

        with log.timed("compute_hygiene", repo_id=repo_id):
            try:
                hygiene = compute_hygiene(self._writer._driver, repo_id)
                log.info("Hygiene scoring complete", repo_id=repo_id,
                         score=hygiene.get("repo_score"),
                         grade=hygiene.get("repo_grade"),
                         overhead_pct=hygiene.get("overhead_pct"))
            except Exception as exc:
                log.warning("Hygiene scoring failed", repo_id=repo_id, exc=str(exc))

        # Always write a commit marker so the watcher stops retriggering full scans.
        # If git is unavailable (e.g. path mapping issue), write "unknown" as a sentinel.
        self._writer.update_last_commit(repo_id, last_commit or "unknown")

        write_claude_md(self._writer._driver, repo_id, repo_path)

        log.info("Full scan complete",
                 repo_id=repo_id,
                 parsed=completed,
                 errors=errors,
                 elapsed_ms=total_elapsed_ms,
                 files_per_sec=rate,
                 commit=last_commit[:12] if last_commit else "unknown")

    def incremental_update(self, repo_path: str, repo_id: str,
                           from_commit: str, to_commit: str):
        """
        Incremental update — single-threaded (typically only a handful of files).
        """
        start = time.perf_counter()

        repo = git.Repo(repo_path)
        self._writer.current_commit = to_commit
        diff = repo.commit(from_commit).diff(to_commit)
        _SUPPORTED = {".java", ".py"} | CPP_EXTENSIONS | APEX_EXTENSIONS | JS_TS_EXTENSIONS
        changed = [d for d in diff
                   if Path(d.a_path or d.b_path or "").suffix.lower() in _SUPPORTED]

        log.info("Incremental update started",
                 repo_id=repo_id,
                 from_commit=from_commit[:8],
                 to_commit=to_commit[:8],
                 changed_files=len(changed))

        errors = 0

        for d in changed:
            if d.deleted_file:
                full_path = str(Path(repo_path) / d.a_path)
                log.debug("File deleted", repo_id=repo_id, file=d.a_path)
                self._writer.delete_file_nodes(full_path, repo_id)

            elif d.new_file or d.b_path:
                target = d.b_path or d.a_path
                full_path = Path(repo_path) / target
                action = "added" if d.new_file else "modified"
                log.debug(f"File {action}", repo_id=repo_id, file=target)

                if not d.new_file:
                    self._writer.delete_file_nodes(str(full_path), repo_id)

                try:
                    with log.timed("parse_file", repo_id=repo_id, file=target):
                        result = _parse_file_worker((str(full_path), repo_id, repo_path))

                    if result and not result["error"]:
                        self._writer.upsert_parsed_file(result["parsed"])
                        self._writer.upsert_scip_document(result["scip_doc"])
                        if result["endpoints"]:
                            self._writer.upsert_api_endpoints(repo_id, result["endpoints"])
                        if result["pools"] or result["asyncs"] or result["concurrency_facts"]:
                            self._writer.upsert_concurrency_facts(
                                repo_id,
                                result["pools"],
                                result["asyncs"],
                                result["concurrency_facts"],
                            )
                    elif result:
                        errors += 1
                        log.warning("Parse error", repo_id=repo_id,
                                    file=target, error=result["error"])
                except Exception as exc:
                    errors += 1
                    log.error("Incremental parse failed",
                              repo_id=repo_id, file=target, exc=exc)

        self._writer.update_last_commit(repo_id, to_commit)

        try:
            pattern_results = detect_patterns(self._writer._driver, repo_id)
            save_patterns_to_kg(self._writer._driver, pattern_results, repo_id)
            log.info("Pattern detection complete",
                     repo_id=repo_id, patterns=len(pattern_results))
        except Exception as exc:
            log.warning("Pattern detection failed", repo_id=repo_id, exc=str(exc))

        try:
            policy_results = scan_policies(self._writer._driver, repo_id)
            log.info("Policy scan complete",
                     repo_id=repo_id, policies=len(policy_results))
        except Exception as exc:
            log.warning("Policy scan failed", repo_id=repo_id, exc=str(exc))

        # Rebuild object models + enrichments for changed classes + 1-hop neighbours
        try:
            affected_fqns = self._affected_fqns(repo_id, changed)
            fqn_filter = affected_fqns or None
            om_count = build_object_models(
                self._writer._driver, repo_id, fqn_filter=fqn_filter
            )
            enrich_classes(self._writer._driver, repo_id, fqn_filter=fqn_filter)
            build_call_chains(self._writer._driver, repo_id, fqn_filter=fqn_filter)
            log.info("Object models updated", repo_id=repo_id, count=om_count)
        except Exception as exc:
            log.warning("Object model update failed", repo_id=repo_id, exc=str(exc))

        elapsed_ms = round((time.perf_counter() - start) * 1000)

        write_claude_md(self._writer._driver, repo_id, repo_path)

        log.info("Incremental update complete",
                 repo_id=repo_id,
                 from_commit=from_commit[:8],
                 to_commit=to_commit[:8],
                 changed=len(changed),
                 errors=errors,
                 elapsed_ms=elapsed_ms)

    def _affected_fqns(self, repo_id: str, diff_items) -> set[str]:
        """
        Return FQNs of classes in changed files + any class that imports them
        (so their 'dependents' snapshot field also gets refreshed).
        """
        changed_paths = set()
        for d in diff_items:
            p = d.b_path or d.a_path
            if p and Path(p).suffix.lower() in ({".java", ".py"} | CPP_EXTENSIONS):
                changed_paths.add(p)
        if not changed_paths:
            return set()

        with self._writer._driver.session() as s:
            rows = s.run("""
                MATCH (c:Class {repo_id: $repo_id})
                WHERE any(p IN $paths WHERE c.file_path ENDS WITH p)
                OPTIONAL MATCH (importer:Class {repo_id: $repo_id})-[:IMPORTS]->(c)
                RETURN collect(DISTINCT c.fqn) + collect(DISTINCT importer.fqn) AS fqns
            """, repo_id=repo_id, paths=list(changed_paths)).single()
            return set(rows["fqns"]) if rows else set()
