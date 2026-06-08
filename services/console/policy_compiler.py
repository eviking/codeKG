"""
Policy compiler — translates natural language architectural constraints into
Cypher queries using Claude.

Falls back to a small regex library for the most common patterns so simple
rules compile instantly without an API call.
"""
from __future__ import annotations

import os
import re

from shared.config import cfg


# ── Fast-path regex patterns for common phrasings ────────────────────────────
# Only used when they match exactly — everything else goes to Claude.

_FAST_PATTERNS: list[tuple[re.Pattern, str]] = [

    (
        re.compile(
            r"(?:services?\s+in\s+|classes?\s+in\s+)?['\"]?(?P<src>\w+)['\"]?\s+module\s+"
            r"must\s+not\s+(?:directly\s+)?call\s+['\"]?(?P<tgt>\w+)['\"]?",
            re.IGNORECASE,
        ),
        "MATCH (src:Class)-[:IMPORTS|CALLS*1..3]->(tgt:Class)\n"
        "WHERE src.module = '{src}' AND tgt.module = '{tgt}'\n"
        "RETURN DISTINCT src.fqn AS fqn",
    ),

    (
        re.compile(
            r"['\"]?(?P<src>\w+)['\"]?\s+layer\s+must\s+not\s+depend\s+on\s+['\"]?(?P<tgt>\w+)['\"]?",
            re.IGNORECASE,
        ),
        "MATCH (src:Class)-[:IMPORTS]->(tgt:Class)\n"
        "WHERE src.module = '{src}' AND tgt.module = '{tgt}'\n"
        "RETURN DISTINCT src.fqn AS fqn",
    ),

    (
        re.compile(
            r"all\s+classes?\s+in\s+['\"]?(?P<module>\w+)['\"]?\s+module\s+must\s+have\s+annotation\s+@?(?P<annotation>\w+)",
            re.IGNORECASE,
        ),
        "MATCH (c:Class)\n"
        "WHERE c.module = '{module}' AND NOT ANY(a IN coalesce(c.annotations, []) WHERE a CONTAINS '{annotation}')\n"
        "RETURN DISTINCT c.fqn AS fqn",
    ),

    (
        re.compile(
            r"controllers?\s+must\s+not\s+(?:directly\s+)?call\s+repositories?",
            re.IGNORECASE,
        ),
        "MATCH (c:Class)-[:CALLS|IMPORTS*1..3]->(r:Class)\n"
        "WHERE toLower(c.name) CONTAINS 'controller' AND toLower(r.name) CONTAINS 'repository'\n"
        "RETURN DISTINCT c.fqn AS fqn",
    ),

    (
        re.compile(
            r"service\s+classes?\s+must\s+not\s+extend\s+(?P<base>\w+)",
            re.IGNORECASE,
        ),
        "MATCH (c:Class)-[:EXTENDS]->(base:Class)\n"
        "WHERE toLower(c.name) CONTAINS 'service' AND base.name = '{base}'\n"
        "RETURN DISTINCT c.fqn AS fqn",
    ),

    (
        re.compile(
            r"all\s+public\s+methods?\s+in\s+['\"]?(?P<module>\w+)['\"]?\s+must(?:\s+be)?\s+annotated\s+with\s+@?(?P<annotation>\w+)",
            re.IGNORECASE,
        ),
        "MATCH (c:Class)-[:HAS_METHOD]->(m:Method)\n"
        "WHERE c.module = '{module}'\n"
        "  AND ANY(mod IN coalesce(m.modifiers, []) WHERE toLower(mod) = 'public')\n"
        "  AND NOT ANY(a IN coalesce(m.annotations, []) WHERE a CONTAINS '{annotation}')\n"
        "RETURN DISTINCT m.fqn AS fqn // public methods",
    ),
]


_SCHEMA_CONTEXT = """
Knowledge graph schema (Neo4j):

Node labels and key properties:
- Class: fqn, name, file_path, module (module_id string), repo_id, role (CLASS/TEST/GENERATED),
         hygiene_grade (A-F), hygiene_score (0-100), hygiene_tier (god/large/medium/small/tiny),
         coupling (float), blast_size (int), annotations (list), kind (class/module/interface)
- Method: fqn, name, class_fqn, modifiers (list), annotations (list), repo_id
- Module: module_id, name, path, repo_id
- Repository: repo_id, language, hygiene_grade, hygiene_score

Relationships:
- (Class)-[:IMPORTS]->(Class)          — import/dependency edge
- (Class)-[:HAS_METHOD]->(Method)      — class owns method
- (Class)-[:EXTENDS]->(Class)          — inheritance
- (Class)-[:IMPLEMENTS]->(Class)       — interface implementation
- (Class)-[:BELONGS_TO]->(Module)      — class is in module
- (Class)-[:VIOLATES]->(ArchPolicy)    — existing violation

Important:
- Always filter by repo_id: WHERE c.repo_id = $repo_id (use parameter $repo_id)
- The query MUST return a column named `fqn` containing the FQN of the violating class/method
- Use DISTINCT to avoid duplicates
- module_id values look like "services/api", "services/console", "services/mcp" etc.
- Class.file_path is absolute — use CONTAINS or STARTS WITH for path matching
"""

_SYSTEM_PROMPT = """You are a Cypher query writer for a Neo4j knowledge graph that stores code structure.

Given a natural language architectural constraint, write a Cypher query that returns all VIOLATING nodes.

Rules:
1. The query must return a column named `fqn` for each violating node
2. Always include `WHERE c.repo_id = $repo_id` (parameterised — do not hardcode)
3. Return only the Cypher query — no explanation, no markdown fences, no comments
4. If the constraint cannot be expressed in Cypher against this schema, return exactly: UNCOMPILABLE
5. Use DISTINCT to avoid duplicate results
6. Keep it simple — prefer direct MATCH patterns over complex subqueries
"""


def compile_policy(natural_language: str) -> str:
    """
    Translate a natural language architectural constraint into a Cypher query.
    Returns valid Cypher on success, or a // comment string if compilation fails.
    """
    nl = natural_language.strip()
    if not nl:
        return _placeholder_comment("rule not expressible in this schema", nl)

    # Try fast-path patterns first
    for pattern, template in _FAST_PATTERNS:
        m = pattern.search(nl)
        if m:
            groups = m.groupdict()
            try:
                return template.format(**groups)
            except KeyError:
                continue

    # Fall back to Claude
    return _compile_with_claude(nl)


def _placeholder_comment(reason: str, nl: str) -> str:
    return (
        f"// Could not compile: {reason}\n"
        f'// Rule: "{nl}"\n'
        "// Expected output shape: RETURN DISTINCT <violator>.fqn AS fqn\n"
    )


def _compile_with_claude(nl: str) -> str:
    from shared.llm import llm as _llm
    try:
        message = _llm.chat(
            model=cfg.llm.policy_model,
            prompt=f"{_SCHEMA_CONTEXT}\n\nArchitectural constraint to compile:\n{nl}",
            system=_SYSTEM_PROMPT,
            max_tokens=cfg.llm.policy_max_tokens,
        )
        result = message.text.strip()

        # Strip any accidental markdown fences
        if result.startswith("```"):
            result = result.split("\n", 1)[1] if "\n" in result else result[3:]
            result = result.rsplit("```", 1)[0].strip()

        if result == "UNCOMPILABLE" or not result:
            return _placeholder_comment("rule not expressible in this schema", nl)

        return result

    except Exception as e:
        return _placeholder_comment(str(e), nl)
