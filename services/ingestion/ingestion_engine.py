"""
Ingestion engine — orchestrates full baseline scan and incremental commit updates.
"""
from __future__ import annotations

import logging
from pathlib import Path

import git

from parser.java_parser import JavaParser
from parser.scip_emitter import SCIPEmitter
from parser.api_extractor import ApiExtractor
from parser.concurrency_extractor import ConcurrencyExtractor
from parser.build_extractor import BuildExtractor
from parser.repo_structure import extract_project_identity, extract_repo_map
from kg.writer import KGWriter

log = logging.getLogger(__name__)


class IngestionEngine:

    def __init__(self, writer: KGWriter):
        self._parser = JavaParser()
        self._scip = SCIPEmitter()
        self._api_extractor = ApiExtractor()
        self._concurrency_extractor = ConcurrencyExtractor()
        self._build_extractor = BuildExtractor()
        self._writer = writer

    def full_scan(self, repo_path: str, repo_id: str):
        """
        Walk every .java file in the repo and upsert into the KG.
        Also extracts project identity, repo map, build info, API surface,
        and concurrency model.
        Intended for initial onboarding of a repository.
        """
        path = Path(repo_path)
        java_files = list(path.rglob("*.java"))
        log.info("Full scan: %s — %d Java files found", repo_id, len(java_files))

        # Register the repository node
        repo = git.Repo(repo_path)
        last_commit = repo.head.commit.hexsha if not repo.head.is_detached else None
        self._writer.current_commit = last_commit or "unknown"

        # §1 Project identity + §9 build info
        identity = extract_project_identity(repo_path)
        build_info, test_categories = self._build_extractor.extract(repo_path)
        self._writer.upsert_repository(
            repo_id=repo_id,
            name=identity.name or path.name,
            path=str(path),
            java_version=identity.java_version or build_info.java_version,
            build_tool=build_info.build_tool,
            description=identity.description,
            test_framework=build_info.test_framework,
            build_commands=build_info.build_commands,
            key_dependencies=build_info.key_dependencies,
        )
        self._writer.upsert_test_categories(repo_id, test_categories)

        # §2 Repository map
        dir_entries = extract_repo_map(repo_path)
        self._writer.upsert_directory_entries(repo_id, dir_entries)

        # Per-file pass
        for i, java_file in enumerate(java_files):
            try:
                # §6 Structural facts — parse then emit via SCIP interchange
                parsed = self._parser.parse_file(java_file, repo_id)
                self._writer.upsert_parsed_file(parsed)
                # Also write SCIP document (language-agnostic path)
                scip_doc = self._scip.emit(parsed)
                self._writer.upsert_scip_document(scip_doc)

                # §7 API surface
                endpoints = self._api_extractor.extract_file(java_file, repo_id)
                if endpoints:
                    self._writer.upsert_api_endpoints(repo_id, endpoints)

                # §8 Concurrency model
                pools, asyncs, facts = self._concurrency_extractor.extract_file(java_file)
                if pools or asyncs or facts:
                    self._writer.upsert_concurrency_facts(repo_id, pools, asyncs, facts)

            except Exception as exc:
                log.warning("Failed to parse %s: %s", java_file, exc)

            if (i + 1) % 100 == 0:
                log.info("  ... processed %d / %d files", i + 1, len(java_files))

        if last_commit:
            self._writer.update_last_commit(repo_id, last_commit)

        log.info("Full scan complete: %s", repo_id)

    def incremental_update(self, repo_path: str, repo_id: str, from_commit: str, to_commit: str):
        """
        Process only files changed between two commits.
        Deletes removed files, upserts modified/added files.
        """
        repo = git.Repo(repo_path)
        self._writer.current_commit = to_commit
        diff = repo.commit(from_commit).diff(to_commit)
        log.info(
            "Incremental update %s: %s..%s (%d diffs)",
            repo_id, from_commit[:8], to_commit[:8], len(diff),
        )

        for d in diff:
            if d.deleted_file and d.a_path.endswith(".java"):
                full_path = str(Path(repo_path) / d.a_path)
                log.debug("  DELETE %s", d.a_path)
                self._writer.delete_file_nodes(full_path, repo_id)

            elif d.new_file and d.b_path.endswith(".java"):
                full_path = Path(repo_path) / d.b_path
                log.debug("  ADD %s", d.b_path)
                try:
                    parsed = self._parser.parse_file(full_path, repo_id)
                    self._writer.upsert_parsed_file(parsed)
                except Exception as exc:
                    log.warning("Failed to parse %s: %s", full_path, exc)

            elif d.b_path and d.b_path.endswith(".java"):
                # modified file — delete old nodes, re-parse
                full_path = Path(repo_path) / d.b_path
                log.debug("  MODIFY %s", d.b_path)
                self._writer.delete_file_nodes(str(full_path), repo_id)
                try:
                    parsed = self._parser.parse_file(full_path, repo_id)
                    self._writer.upsert_parsed_file(parsed)
                except Exception as exc:
                    log.warning("Failed to parse %s: %s", full_path, exc)

        self._writer.update_last_commit(repo_id, to_commit)
        log.info("Incremental update complete: %s → %s", from_commit[:8], to_commit[:8])
