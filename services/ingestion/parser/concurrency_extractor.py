"""
§8 Concurrency Model extractor.

Detects:
- Thread pool declarations (ExecutorService, ThreadPoolExecutor, @Async, ScheduledExecutorService)
- Synchronization patterns (@Synchronized, synchronized blocks, ReentrantLock, volatile fields)
- Thread-safety annotations (@ThreadSafe, @NotThreadSafe, @GuardedBy)
- Async method markers (@Async, CompletableFuture return types, Mono/Flux for reactive)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import tree_sitter_java as tsjava
from tree_sitter import Language, Parser, Node

JAVA_LANGUAGE = Language(tsjava.language())

EXECUTOR_TYPES = {
    "ExecutorService", "ThreadPoolExecutor", "ScheduledExecutorService",
    "ScheduledThreadPoolExecutor", "ForkJoinPool", "Executor",
    "ExecutorCompletionService", "ThreadFactory",
}

ASYNC_RETURN_TYPES = {
    "CompletableFuture", "Future", "ListenableFuture",
    "Mono", "Flux",                             # Project Reactor
    "Observable", "Single", "Maybe", "Flowable", # RxJava
    "Promise",
}

LOCK_TYPES = {
    "ReentrantLock", "ReadWriteLock", "ReentrantReadWriteLock",
    "StampedLock", "Lock", "Semaphore", "CountDownLatch", "CyclicBarrier",
}

THREAD_SAFETY_ANNOTATIONS = {
    "@ThreadSafe", "@NotThreadSafe", "@GuardedBy", "@Immutable",
}


@dataclass
class ThreadPoolDeclaration:
    class_fqn: str
    field_name: str
    pool_type: str
    configuration: Optional[str] = None    # e.g. "newFixedThreadPool(10)"
    file_path: Optional[str] = None
    line: Optional[int] = None


@dataclass
class AsyncMethod:
    class_fqn: str
    method_name: str
    mechanism: str                  # @Async | CompletableFuture | Mono | Flux | synchronized
    return_type: Optional[str] = None
    file_path: Optional[str] = None
    line: Optional[int] = None


@dataclass
class ConcurrencyFact:
    class_fqn: str
    fact_type: str                  # thread_safe | not_thread_safe | guarded_by | synchronized_method | volatile_field
    detail: Optional[str] = None
    file_path: Optional[str] = None
    line: Optional[int] = None


def _text(node: Node, src: bytes) -> str:
    return src[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


class ConcurrencyExtractor:

    def __init__(self):
        self._parser = Parser(JAVA_LANGUAGE)

    def extract_file(self, path: Path) -> tuple[list[ThreadPoolDeclaration], list[AsyncMethod], list[ConcurrencyFact]]:
        try:
            src = path.read_bytes()
        except Exception:
            return [], [], []
        tree = self._parser.parse(src)
        pools: list[ThreadPoolDeclaration] = []
        asyncs: list[AsyncMethod] = []
        facts: list[ConcurrencyFact] = []
        self._visit_root(tree.root_node, src, str(path), pools, asyncs, facts)
        return pools, asyncs, facts

    def _visit_root(self, root: Node, src: bytes, file_path: str,
                    pools, asyncs, facts):
        pkg = ""
        for node in root.children:
            if node.type == "package_declaration":
                for child in node.children:
                    if child.type in ("scoped_identifier", "identifier"):
                        pkg = _text(child, src)
            elif node.type == "class_declaration":
                self._visit_class(node, src, pkg, file_path, pools, asyncs, facts)

    def _visit_class(self, class_node: Node, src: bytes, pkg: str, file_path: str,
                     pools, asyncs, facts):
        name_node = class_node.child_by_field_name("name")
        if not name_node:
            return
        class_fqn = f"{pkg}.{_text(name_node, src)}" if pkg else _text(name_node, src)

        # Class-level thread-safety annotations
        for child in class_node.children:
            if child.type == "modifiers":
                ann_text = _text(child, src)
                for ann in THREAD_SAFETY_ANNOTATIONS:
                    if ann in ann_text:
                        facts.append(ConcurrencyFact(
                            class_fqn=class_fqn,
                            fact_type=ann.lstrip("@").lower().replace(" ", "_"),
                            file_path=file_path,
                            line=class_node.start_point[0] + 1,
                        ))

        body = class_node.child_by_field_name("body")
        if not body:
            return

        for member in body.children:
            if member.type == "field_declaration":
                self._visit_field(member, src, class_fqn, file_path, pools, facts)
            elif member.type == "method_declaration":
                self._visit_method(member, src, class_fqn, file_path, asyncs, facts)

    def _visit_field(self, field_node: Node, src: bytes, class_fqn: str, file_path: str,
                     pools, facts):
        type_node = field_node.child_by_field_name("type")
        if not type_node:
            return
        type_text = _text(type_node, src)
        mods_text = ""
        for child in field_node.children:
            if child.type == "modifiers":
                mods_text = _text(child, src)

        # Thread pool fields
        base_type = type_text.split("<")[0].strip()
        if base_type in EXECUTOR_TYPES:
            name_node = None
            for child in field_node.children:
                if child.type == "variable_declarator":
                    name_node = child.child_by_field_name("name")
            field_name = _text(name_node, src) if name_node else "?"

            # Try to capture initializer e.g. Executors.newFixedThreadPool(10)
            config = None
            field_text = _text(field_node, src)
            m = re.search(r"Executors\.\w+\([^)]*\)", field_text)
            if m:
                config = m.group(0)
            else:
                m = re.search(r"new\s+\w+\([^)]*\)", field_text)
                if m:
                    config = m.group(0)

            pools.append(ThreadPoolDeclaration(
                class_fqn=class_fqn,
                field_name=field_name,
                pool_type=base_type,
                configuration=config,
                file_path=file_path,
                line=field_node.start_point[0] + 1,
            ))

        # Lock fields
        if base_type in LOCK_TYPES:
            for child in field_node.children:
                if child.type == "variable_declarator":
                    name_node = child.child_by_field_name("name")
                    if name_node:
                        facts.append(ConcurrencyFact(
                            class_fqn=class_fqn,
                            fact_type="lock_field",
                            detail=f"{base_type} {_text(name_node, src)}",
                            file_path=file_path,
                            line=field_node.start_point[0] + 1,
                        ))

        # volatile fields
        if "volatile" in mods_text:
            for child in field_node.children:
                if child.type == "variable_declarator":
                    name_node = child.child_by_field_name("name")
                    if name_node:
                        facts.append(ConcurrencyFact(
                            class_fqn=class_fqn,
                            fact_type="volatile_field",
                            detail=f"volatile {type_text} {_text(name_node, src)}",
                            file_path=file_path,
                            line=field_node.start_point[0] + 1,
                        ))

    def _visit_method(self, method_node: Node, src: bytes, class_fqn: str, file_path: str,
                      asyncs, facts):
        name_node = method_node.child_by_field_name("name")
        if not name_node:
            return
        method_name = _text(name_node, src)

        return_type_node = method_node.child_by_field_name("type")
        return_type = _text(return_type_node, src) if return_type_node else None

        mods_text = ""
        for child in method_node.children:
            if child.type == "modifiers":
                mods_text = _text(child, src)

        # @Async annotation
        if "@Async" in mods_text:
            asyncs.append(AsyncMethod(
                class_fqn=class_fqn,
                method_name=method_name,
                mechanism="@Async",
                return_type=return_type,
                file_path=file_path,
                line=method_node.start_point[0] + 1,
            ))

        # synchronized method
        if "synchronized" in mods_text:
            facts.append(ConcurrencyFact(
                class_fqn=class_fqn,
                fact_type="synchronized_method",
                detail=method_name,
                file_path=file_path,
                line=method_node.start_point[0] + 1,
            ))

        # Async return types (CompletableFuture, Mono, Flux, etc.)
        if return_type:
            base_rt = return_type.split("<")[0].strip()
            if base_rt in ASYNC_RETURN_TYPES:
                asyncs.append(AsyncMethod(
                    class_fqn=class_fqn,
                    method_name=method_name,
                    mechanism=base_rt,
                    return_type=return_type,
                    file_path=file_path,
                    line=method_node.start_point[0] + 1,
                ))
