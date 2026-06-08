"""
Agent Index Generator
Generates .codekg/ index files from the knowledge graph.
Each file is kept small and focused so agents load only what they need.
"""
from __future__ import annotations

import textwrap
from datetime import datetime, timezone
from typing import Callable

from deps import run_query

# No caps — truncating index files silently breaks Claude Code's understanding.
class _DefaultZero(dict):
    """Dictionary that treats missing counters as zero during console summaries. Watch out for accidental writes here, because absent keys become real buckets once touched."""

    def __missing__(self, key): return 0
_CAP = _DefaultZero()

_TS = lambda: datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _cap(text: str, limit: int) -> str:
    return text  # no truncation — partial files are worse than large files


# ── INDEX.md ─────────────────────────────────────────────────────────────────

def generate_index(repo_id: str, available_files: list[dict]) -> str:
    """
    Master navigation file — agent reads this first to orient,
    then reads the specific files relevant to the task.
    Files are kept current by git-commit-triggered scans.
    """
    lines = [
        f"# CodeKG Agent Index — {repo_id}",
        f"_Generated {_TS()} · kept current by git commit triggers_",
        "",
        "## How to use this index",
        "These files are **always current** — regenerated automatically on every git commit.",
        "Treat them as the primary source of truth for this codebase.",
        "Read the files relevant to your task **before writing any code**.",
        "",
        "**Before starting any task, read:**",
        "1. `policies/active.md` — rules you must not violate",
        "2. The relevant `modules/<name>.md` — classes, structure, key entry points",
        "3. `architecture/hotspots.md` — if you plan to touch high-blast-radius classes",
        "4. `insights/<name>.md` — non-obvious facts from previous sessions in this area",
        "",
        "**Only call CodeKG MCP tools directly for:**",
        "- Live impact analysis on files you just changed (`get_change_impact`)",
        "- Full method-level class detail not in the module file (`get_class`)",
        "- Searching for a class when you don't know its module (`search_classes`)",
        "- Submitting session telemetry at the end of your task",
        "",
        "| When you need to... | Read |",
        "|---|---|",
        "| Understand the repo structure | `architecture/modules.md` |",
        "| Find key dependencies | `architecture/dependencies.md` |",
        "| Check design patterns | `architecture/patterns.md` |",
        "| Identify risky classes before changing | `architecture/hotspots.md` |",
        "| Know the rules before making changes | `policies/active.md` |",
        "| Check current violations | `policies/violations.md` |",
        "| Work on a specific module | `modules/<name>.md` |",
        "| Get non-obvious facts about a module | `insights/<name>.md` |",
        "",
        "## Available files",
    ]

    by_dir: dict[str, list[dict]] = {}
    for f in available_files:
        d = f.get("directory", "")
        by_dir.setdefault(d, []).append(f)

    for d, files in sorted(by_dir.items()):
        lines.append(f"\n### {d or 'root'}/")
        for f in sorted(files, key=lambda x: x["filename"]):
            status = f.get("status", "current")
            stale  = " ⚠ stale" if status == "stale" else ""
            lines.append(f"- `{f['filename']}`{stale} — {f.get('description', '')}")

    lines += [
        "",
        "## Modules in this repo",
    ]

    modules = run_query(
        "MATCH (m:Module {repo_id: $repo_id}) RETURN m.module_id AS id, m.name AS name "
        "ORDER BY m.module_id",
        repo_id=repo_id,
    )
    for m in modules:
        lines.append(f"- `{m['id']}` — {m['name'] or m['id']}")

    return _cap("\n".join(lines), _CAP["index"])


# ── architecture/modules.md ──────────────────────────────────────────────────

def generate_modules(repo_id: str) -> str:
    modules = run_query("""
        MATCH (m:Module {repo_id: $repo_id})
        OPTIONAL MATCH (c:Class {repo_id: $repo_id})
            WHERE c.file_path STARTS WITH m.path AND NOT c.kind IN ['module']
        WITH m, count(c) AS class_count,
             avg(CASE WHEN c.blast_size IS NOT NULL THEN c.blast_size ELSE 0 END) AS avg_blast,
             max(c.blast_size) AS max_blast,
             sum(CASE WHEN c.hygiene_grade IN ['C','D','F'] THEN 1 ELSE 0 END) AS hotspot_count
        RETURN m.module_id AS id, m.name AS name, m.path AS path,
               m.summary AS summary, class_count,
               round(avg_blast) AS avg_blast, max_blast, hotspot_count
        ORDER BY class_count DESC
    """, repo_id=repo_id)

    # Top classes across all modules for quick orientation
    top_classes = run_query("""
        MATCH (c:Class {repo_id: $repo_id})
        WHERE c.blast_size > 5 AND NOT c.kind IN ['module']
        RETURN c.name AS name, c.fqn AS fqn, c.blast_size AS blast,
               c.hygiene_grade AS grade, c.file_path AS file_path,
               c.summary AS summary, c.javadoc AS javadoc
        ORDER BY c.blast_size DESC LIMIT 10
    """, repo_id=repo_id)

    lines = [
        f"# Module Map — {repo_id}",
        f"_Generated {_TS()}_",
        "",
        f"This repository contains **{len(modules)} logical modules**.",
        "Read individual `modules/<name>.md` files for full class detail.",
        "",
    ]

    if top_classes:
        lines += ["## Top 10 classes by blast radius (repo-wide)", ""]
        lines.append("_Before touching any of these, read their module file first._")
        lines.append("")
        lines += ["| Class | Blast | Grade | Location |", "|---|---|---|---|"]
        for c in top_classes:
            parts = (c.get("file_path") or "").split("/")
            short = "/".join(parts[-2:]) if len(parts) >= 2 else c.get("file_path") or ""
            lines.append(f"| `{c['name']}` | {c['blast']} | {c.get('grade') or '?'} | `{short}` |")
        lines.append("")

    lines += ["## Modules", ""]
    for m in modules:
        hotspot_warn = f" ⚠ {m['hotspot_count']} hotspot(s)" if (m.get("hotspot_count") or 0) > 0 else ""
        lines.append(f"### `{m['id']}` — {m['name'] or m['id']}{hotspot_warn}")
        lines.append(f"**Path:** `{m['path'] or '(root)'}` | **Classes:** {m['class_count']} | "
                     f"**Max blast:** {m.get('max_blast') or 0} | **Avg blast:** {m.get('avg_blast') or 0}")
        if m.get("summary"):
            lines.append("")
            lines.append(m["summary"][:300])
        lines.append("")
        lines.append(f"→ Full detail: `.codekg/modules/{m['id']}.md`")
        lines.append("")

    return _cap("\n".join(lines), _CAP["modules"])


# ── architecture/dependencies.md ─────────────────────────────────────────────

def generate_dependencies(repo_id: str) -> str:
    # Cross-module dependencies
    deps = run_query("""
        MATCH (c:Class {repo_id: $repo_id})-[:IMPORTS]->(d:Class {repo_id: $repo_id})
        MATCH (mc:Module {repo_id: $repo_id}) WHERE c.file_path STARTS WITH mc.path
        MATCH (md:Module {repo_id: $repo_id}) WHERE d.file_path STARTS WITH md.path AND mc.module_id <> md.module_id
        RETURN mc.module_id AS from_module, md.module_id AS to_module,
               count(*) AS edge_count
        ORDER BY edge_count DESC
        LIMIT 40
    """, repo_id=repo_id)

    # High blast radius classes
    blast = run_query("""
        MATCH (c:Class {repo_id: $repo_id})
        WHERE c.blast_size > 10
        RETURN c.name AS name, c.fqn AS fqn, c.blast_size AS blast,
               c.package_fqn AS pkg,
               c.javadoc AS javadoc, c.summary AS summary
        ORDER BY c.blast_size DESC LIMIT 15
    """, repo_id=repo_id)

    lines = [
        f"# Key Dependencies — {repo_id}",
        f"_Generated {_TS()}_",
        "",
        "## Cross-module dependencies",
        "Sorted by number of import edges. High counts = tight coupling.",
        "",
        "| From | To | Import edges |",
        "|---|---|---|",
    ]
    for d in deps:
        lines.append(f"| `{d['from_module']}` | `{d['to_module']}` | {d['edge_count']} |")

    lines += [
        "",
        "## Highest blast radius classes",
        "Changing these classes affects the most dependents.",
        "",
    ]
    for b in blast:
        doc = (b.get("javadoc") or b.get("summary") or "").strip()
        lines.append(f"### `{b['name']}` — blast {b['blast']} classes")
        lines.append(f"**FQN:** `{b['fqn']}`  **Package:** `{b['pkg'] or ''}`")
        if doc:
            lines.append(f"> {doc[:200]}")
        lines.append("")

    return _cap("\n".join(lines), _CAP["dependencies"])


# ── architecture/patterns.md ─────────────────────────────────────────────────

def generate_patterns(repo_id: str) -> str:
    patterns = run_query("""
        MATCH (ap:ArchPattern {repo_id: $repo_id})
        RETURN ap.name AS name, ap.anti_pattern AS anti,
               ap.description AS description, ap.match_count AS count,
               ap.top_packages AS packages
        ORDER BY ap.anti_pattern DESC, ap.match_count DESC
    """, repo_id=repo_id)

    anti     = [p for p in patterns if p.get("anti")]
    positive = [p for p in patterns if not p.get("anti")]

    lines = [
        f"# Architectural Patterns — {repo_id}",
        f"_Generated {_TS()}_",
        "",
    ]

    if anti:
        lines += ["## ⚠ Anti-patterns detected", ""]
        for p in anti:
            lines.append(f"### {p['name']} ({p.get('count', 0)} occurrences)")
            if p.get("description"):
                lines.append(p["description"][:200])
            if p.get("packages"):
                lines.append(f"**Top packages:** {p['packages']}")
            lines.append("")

    if positive:
        lines += ["## Design patterns in use", ""]
        for p in positive:
            lines.append(f"- **{p['name']}** — {p.get('count', 0)} occurrences"
                         + (f" ({p['packages']})" if p.get("packages") else ""))

    return _cap("\n".join(lines), _CAP["patterns"])


# ── architecture/hotspots.md ─────────────────────────────────────────────────

def generate_hotspots(repo_id: str) -> str:
    hotspots = run_query("""
        MATCH (c:Class {repo_id: $repo_id})
        WHERE c.hygiene_grade IN ['C','D','F']
          AND c.blast_size > 5
          AND NOT c.kind IN ['module']
        RETURN c.name AS name, c.fqn AS fqn,
               c.hygiene_grade AS grade, c.hygiene_score AS score,
               c.blast_size AS blast, c.package_fqn AS pkg,
               c.method_count AS methods,
               c.javadoc AS javadoc, c.summary AS summary
        ORDER BY c.blast_size DESC, c.hygiene_score ASC
        LIMIT 30
    """, repo_id=repo_id)

    lines = [
        f"# Hotspots — {repo_id}",
        f"_Generated {_TS()}_",
        "",
        "Classes with both high blast radius and low hygiene score.",
        "**Approach these carefully** — changes here affect many downstream classes",
        "and the code quality makes reasoning harder for both humans and agents.",
        "",
    ]

    for h in hotspots:
        doc = (h.get("javadoc") or h.get("summary") or "").strip()
        lines.append(f"### `{h['name']}` — Grade **{h['grade']}**")
        lines.append(f"**FQN:** `{h['fqn']}`  **Blast:** {h['blast']} classes  **Methods:** {h.get('methods','?')}  **Package:** `{h['pkg'] or ''}`")
        if doc:
            lines.append(f"> {doc[:200]}")
        lines.append("")

    if not hotspots:
        lines.append("_No significant hotspots detected — good hygiene across the board._")

    return _cap("\n".join(lines), _CAP["hotspots"])


# ── policies/active.md ───────────────────────────────────────────────────────

def generate_policies_active(repo_id: str) -> str:
    policies = run_query("""
        MATCH (ap:ArchPolicy)
        WHERE ap.repo_id = $repo_id OR ap.repo_id IS NULL OR ap.repo_id = ''
        RETURN ap.policy_id AS id, ap.name AS name, ap.description AS description,
               ap.severity AS severity, ap.status AS status
        ORDER BY ap.severity DESC, ap.name
    """, repo_id=repo_id)

    active = [p for p in policies if p.get("status") in (None, "", "active")]

    lines = [
        f"# Active Architectural Policies — {repo_id}",
        f"_Generated {_TS()}_",
        "",
        "**Read this before making any structural changes.**",
        "These rules are enforced — violations will be flagged in CI.",
        "",
    ]

    by_severity: dict[str, list] = {}
    for p in active:
        sev = (p.get("severity") or "medium").lower()
        by_severity.setdefault(sev, []).append(p)

    for sev in ("critical", "high", "medium", "low"):
        if sev not in by_severity:
            continue
        lines.append(f"## {sev.capitalize()} severity")
        lines.append("")
        for p in by_severity[sev]:
            lines.append(f"### {p['name']}")
            if p.get("description"):
                lines.append(p["description"][:300])
            lines.append("")

    if not active:
        lines.append("_No active policies defined for this repository._")

    return _cap("\n".join(lines), _CAP["policies"])


# ── policies/violations.md ───────────────────────────────────────────────────

def generate_violations(repo_id: str) -> str:
    violations = run_query("""
        MATCH (c:Class {repo_id: $repo_id})-[:VIOLATES]->(ap:ArchPolicy)
        RETURN c.name AS class_name, c.fqn AS fqn, c.file_path AS file_path,
               c.blast_size AS blast,
               ap.name AS policy, ap.severity AS severity, ap.description AS policy_desc
        ORDER BY ap.severity DESC, c.blast_size DESC, ap.name, c.name
        LIMIT 60
    """, repo_id=repo_id)

    lines = [
        f"# Current Policy Violations — {repo_id}",
        f"_Generated {_TS()}_",
        "",
        f"**{len(violations)} violation(s)** detected in last scan.",
        "Fix these before they compound — especially critical/high severity ones.",
        "",
    ]

    if violations:
        # Group by severity
        by_sev: dict[str, list] = {}
        for v in violations:
            sev = (v.get("severity") or "medium").lower()
            by_sev.setdefault(sev, []).append(v)

        for sev in ("critical", "high", "medium", "low"):
            if sev not in by_sev:
                continue
            lines.append(f"## {sev.capitalize()} severity ({len(by_sev[sev])} violations)")
            lines.append("")
            lines += [f"| Class | Policy | Blast | File |", "|---|---|---|---|"]
            for v in by_sev[sev]:
                parts = (v.get("file_path") or "").split("/")
                short_fp = "/".join(parts[-2:]) if len(parts) >= 2 else parts[-1] if parts else ""
                blast = v.get("blast") or 0
                lines.append(
                    f"| `{v['class_name']}` | {v['policy']} | {blast} | `{short_fp}` |"
                )
            # Show first unique policy descriptions
            seen_policies: set[str] = set()
            for v in by_sev[sev]:
                pol = v.get("policy") or ""
                desc = v.get("policy_desc") or ""
                if pol not in seen_policies and desc:
                    lines.append(f"\n**{pol}:** {desc[:200]}")
                    seen_policies.add(pol)
            lines.append("")
    else:
        lines.append("_No violations detected — all policies passing._")

    return _cap("\n".join(lines), _CAP["violations"])


# ── modules/<name>.md ────────────────────────────────────────────────────────

def generate_module_file(repo_id: str, module_id: str) -> str:
    module = run_query("""
        MATCH (m:Module {repo_id: $repo_id, module_id: $module_id})
        RETURN m.name AS name, m.path AS path, m.summary AS summary
    """, repo_id=repo_id, module_id=module_id)

    if not module:
        return f"# Module `{module_id}` not found\n"
    m = module[0]
    module_path = m.get("path") or ""

    classes = run_query("""
        MATCH (c:Class {repo_id: $repo_id})
        WHERE c.file_path STARTS WITH $path AND NOT c.kind IN ['module']
        OPTIONAL MATCH (c)-[:HAS_METHOD]->(mt:Method)
        WITH c, count(mt) AS method_count
        RETURN c.name AS name, c.fqn AS fqn, c.kind AS kind,
               c.hygiene_grade AS grade, c.blast_size AS blast,
               method_count, c.javadoc AS javadoc, c.summary AS summary,
               c.file_path AS file_path
        ORDER BY c.blast_size DESC, c.name
        LIMIT 60
    """, repo_id=repo_id, path=module_path)

    # Key public methods for each key class
    key_class_fqns = [c["fqn"] for c in classes if (c.get("blast") or 0) > 3][:12]
    methods_by_class: dict[str, list] = {}
    if key_class_fqns:
        method_rows = run_query("""
            MATCH (c:Class {repo_id: $repo_id})-[:HAS_METHOD]->(mt:Method)
            WHERE c.fqn IN $fqns
              AND NOT mt.name STARTS WITH 'get'
              AND NOT mt.name STARTS WITH 'set'
              AND mt.visibility IN ['public', null]
            RETURN c.fqn AS class_fqn, mt.name AS name,
                   mt.signature AS signature, mt.javadoc AS javadoc,
                   mt.summary AS summary, mt.return_type AS return_type
            ORDER BY c.fqn, mt.name
            LIMIT 120
        """, repo_id=repo_id, fqns=key_class_fqns)
        for row in method_rows:
            methods_by_class.setdefault(row["class_fqn"], []).append(row)

    # Incoming dependencies to this module (who depends on us)
    incoming_deps = run_query("""
        MATCH (caller:Class {repo_id: $repo_id})-[:IMPORTS]->(c:Class {repo_id: $repo_id})
        WHERE c.file_path STARTS WITH $path
          AND NOT caller.file_path STARTS WITH $path
        WITH caller.file_path AS fp, count(*) AS edge_count
        RETURN fp, edge_count
        ORDER BY edge_count DESC LIMIT 10
    """, repo_id=repo_id, path=module_path)

    # Outgoing dependencies from this module (who we depend on)
    outgoing_deps = run_query("""
        MATCH (c:Class {repo_id: $repo_id})-[:IMPORTS]->(dep:Class {repo_id: $repo_id})
        WHERE c.file_path STARTS WITH $path
          AND NOT dep.file_path STARTS WITH $path
        WITH dep.file_path AS fp, count(*) AS edge_count
        RETURN fp, edge_count
        ORDER BY edge_count DESC LIMIT 10
    """, repo_id=repo_id, path=module_path)

    # Insights for this module
    insights = run_query("""
        MATCH (tk:TribalKnowledge {repo_id: $repo_id})
        WHERE tk.applies_to CONTAINS $module_id OR tk.module_id = $module_id
        RETURN tk.insight AS insight, tk.scope AS scope,
               tk.applies_to AS applies_to, tk.confidence AS confidence
        ORDER BY tk.confidence DESC LIMIT 8
    """, repo_id=repo_id, module_id=module_id)

    lines = [
        f"# Module: {m['name'] or module_id}",
        f"_Generated {_TS()}_",
        "",
        f"**Path:** `{module_path or '(root)'}`  ",
        f"**Classes:** {len(classes)}",
        "",
    ]

    if m.get("summary"):
        lines += [m["summary"][:600], ""]

    # ── Insights pinned at top if present ──────────────────────────────────
    if insights:
        lines += ["## ⚡ Insights from previous sessions", ""]
        lines.append("_Non-obvious facts captured from engineering sessions — treat as expert hints._")
        lines.append("")
        for i in insights:
            conf = int((i.get("confidence") or 0.7) * 100)
            lines.append(f"- **{i.get('applies_to', '')}** ({conf}%): {i['insight']}")
        lines.append("")

    # ── Key classes (high blast first) with methods ─────────────────────────
    key = [c for c in classes if (c.get("blast") or 0) > 3][:12]
    if key:
        lines += ["## Key classes", ""]
        lines.append("_These classes have high blast radius — changes here affect many other classes._")
        lines.append("")
        for c in key:
            grade = c.get("grade") or "?"
            blast = c.get("blast") or 0
            lines.append(f"### `{c['name']}` ({c['kind'] or 'class'}) — Grade {grade}, Blast {blast}")
            lines.append(f"**FQN:** `{c['fqn']}`")
            lines.append(f"**File:** `{c.get('file_path') or ''}` | **Methods:** {c.get('method_count', 0)}")
            doc = c.get("javadoc") or c.get("summary") or ""
            if doc:
                lines.append("")
                lines.append(doc[:300])
            # Key methods
            meths = methods_by_class.get(c["fqn"], [])
            if meths:
                lines.append("")
                lines.append("**Public methods:**")
                for mt in meths[:10]:
                    sig = mt.get("signature") or mt.get("name") or ""
                    mt_doc = mt.get("javadoc") or mt.get("summary") or ""
                    ret = mt.get("return_type") or ""
                    sig_line = f"- `{sig}`" + (f" → `{ret}`" if ret else "")
                    if mt_doc:
                        sig_line += f" — {mt_doc[:120]}"
                    lines.append(sig_line)
            lines.append("")

    # ── All classes reference table ─────────────────────────────────────────
    lines += ["## All classes", ""]
    lines.append("_Full list sorted by blast radius (impact if changed). Grade A=clean, F=needs attention._")
    lines.append("")
    lines += ["| Class | Kind | Grade | Blast | Methods | Description |", "|---|---|---|---|---|---|"]
    for c in classes:
        doc = c.get("summary") or c.get("javadoc") or ""
        doc_cell = doc[:120].replace("|", "\\|").replace("\n", " ") if doc else "—"
        lines.append(
            f"| `{c['name']}` | {c['kind'] or 'class'} "
            f"| {c.get('grade') or '?'} | {c.get('blast') or 0} "
            f"| {c.get('method_count') or 0} | {doc_cell} |"
        )

    # ── Dependency map ──────────────────────────────────────────────────────
    if incoming_deps or outgoing_deps:
        lines += ["", "## Dependency map", ""]
        if outgoing_deps:
            lines.append("**This module imports from:**")
            for d in outgoing_deps:
                # shorten file path to last 3 segments
                parts = (d.get("fp") or "").split("/")
                short = "/".join(parts[-3:]) if len(parts) >= 3 else d.get("fp") or ""
                lines.append(f"- `{short}` ({d['edge_count']} imports)")
            lines.append("")
        if incoming_deps:
            lines.append("**Other modules that import from here:**")
            for d in incoming_deps:
                parts = (d.get("fp") or "").split("/")
                short = "/".join(parts[-3:]) if len(parts) >= 3 else d.get("fp") or ""
                lines.append(f"- `{short}` ({d['edge_count']} imports)")
            lines.append("")

    return _cap("\n".join(lines), _CAP["module_file"])


# ── insights/<name>.md ───────────────────────────────────────────────────────

def generate_insights_module(repo_id: str, module_id: str) -> str:
    insights = run_query("""
        MATCH (tk:TribalKnowledge {repo_id: $repo_id})
        WHERE tk.applies_to CONTAINS $module_id
           OR tk.module_id = $module_id
        RETURN tk.insight AS insight, tk.scope AS scope,
               tk.applies_to AS applies_to, tk.confidence AS confidence,
               tk.created_at AS created_at
        ORDER BY tk.confidence DESC, tk.created_at DESC
        LIMIT 30
    """, repo_id=repo_id, module_id=module_id)

    lines = [
        f"# Insights — {module_id}",
        f"_Generated {_TS()}_",
        "",
        "Non-obvious facts discovered from previous coding sessions.",
        "Treat as strong hints from engineers who have worked in this code.",
        "",
    ]

    if insights:
        by_scope: dict[str, list] = {}
        for i in insights:
            s = i.get("scope") or "class"
            by_scope.setdefault(s, []).append(i)

        for scope in ("system", "module", "class", "method"):
            if scope not in by_scope:
                continue
            lines.append(f"## {scope.capitalize()}-level insights")
            lines.append("")
            for i in by_scope[scope]:
                conf = int((i.get("confidence") or 0.7) * 100)
                lines.append(f"**`{i['applies_to']}`** (confidence {conf}%)")
                lines.append(f"{i['insight']}")
                lines.append("")
    else:
        lines.append("_No insights recorded for this module yet._")
        lines.append("Insights are captured automatically when agents submit session telemetry.")

    return _cap("\n".join(lines), _CAP["insights"])


def generate_insights_index(repo_id: str) -> str:
    insights = run_query("""
        MATCH (tk:TribalKnowledge {repo_id: $repo_id})
        RETURN tk.applies_to AS applies_to, tk.scope AS scope,
               count(*) AS count
        ORDER BY count DESC
        LIMIT 50
    """, repo_id=repo_id)

    lines = [
        f"# Insights Index — {repo_id}",
        f"_Generated {_TS()}_",
        "",
        "Non-obvious facts captured from previous coding sessions.",
        "Read the module-specific file for details.",
        "",
        "| Area | Scope | Insights |",
        "|---|---|---|",
    ]
    for i in insights:
        lines.append(f"| `{i['applies_to']}` | {i['scope']} | {i['count']} |")

    if not insights:
        lines.append("_No insights recorded yet. Insights are captured automatically when agents submit session telemetry._")

    return _cap("\n".join(lines), _CAP["insights"])


# ── CLAUDE.md snippet ────────────────────────────────────────────────────────

_CODEKG_SECTION_START = "<!-- codekg:start -->"
_CODEKG_SECTION_END   = "<!-- codekg:end -->"


def generate_claude_md_snippet(repo_id: str) -> str:
    modules = run_query(
        "MATCH (m:Module {repo_id: $repo_id}) RETURN m.module_id AS id, m.name AS name "
        "ORDER BY m.module_id LIMIT 12",
        repo_id=repo_id,
    )
    module_lines = "\n".join(f"  - `{m['id']}`" + (f" — {m['name']}" if m.get("name") else "") for m in modules)

    body = textwrap.dedent(f"""
        ## CodeKG Agent Index
        _Auto-maintained — regenerated on every git commit. Do not edit this section manually._

        Pre-computed intelligence files live in `.codekg/` and are always current.
        **Read them before writing any code** — they replace the need to explore the source tree.

        ### Before starting any task
        1. Read `.codekg/policies/active.md` — rules you must not violate
        2. Read `.codekg/modules/<name>.md` for the module you're working in
        3. Check `.codekg/architecture/hotspots.md` before touching high-blast-radius classes
        4. Read `.codekg/insights/<name>.md` for non-obvious facts from previous sessions

        ### Quick reference
        | Need | File |
        |---|---|
        | Repo structure | `.codekg/architecture/modules.md` |
        | Dependencies & blast radius | `.codekg/architecture/dependencies.md` |
        | Design patterns | `.codekg/architecture/patterns.md` |
        | Risky classes | `.codekg/architecture/hotspots.md` |
        | Architectural rules | `.codekg/policies/active.md` |
        | Current violations | `.codekg/policies/violations.md` |
        | Module detail | `.codekg/modules/<name>.md` |
        | Session insights | `.codekg/insights/<name>.md` |

        ### Modules in this repo
        {module_lines}

        ### When to call CodeKG MCP tools directly
        The index files cover most tasks. Only go direct for:
        - **`get_change_impact`** — live blast radius on files you just modified
        - **`get_class`** — full method signatures when a module file isn't enough
        - **`search_classes`** — finding a class when you don't know its module
        - **`submit_session_telemetry`** — always call this at the end of your session
    """).strip()

    return f"{_CODEKG_SECTION_START}\n{body}\n{_CODEKG_SECTION_END}"


def generate_agents_md_snippet(repo_id: str) -> str:
    """Same as generate_claude_md_snippet but for Codex/OpenAI agents (no MCP tool references)."""
    modules = run_query(
        "MATCH (m:Module {repo_id: $repo_id}) RETURN m.module_id AS id, m.name AS name "
        "ORDER BY m.module_id LIMIT 12",
        repo_id=repo_id,
    )
    module_lines = "\n".join(f"  - `{m['id']}`" + (f" — {m['name']}" if m.get("name") else "") for m in modules)

    body = textwrap.dedent(f"""
        ## CodeKG Agent Index
        _Auto-maintained — regenerated on every git commit. Do not edit this section manually._

        Pre-computed intelligence files live in `.codekg/` and are always current.
        **Read them before writing any code** — they replace the need to explore the source tree.

        ### Before starting any task
        1. Read `.codekg/policies/active.md` — rules you must not violate
        2. Read `.codekg/modules/<name>.md` for the module you're working in
        3. Check `.codekg/architecture/hotspots.md` before touching high-blast-radius classes
        4. Read `.codekg/insights/<name>.md` for non-obvious facts from previous sessions

        ### Quick reference
        | Need | File |
        |---|---|
        | Repo structure | `.codekg/architecture/modules.md` |
        | Dependencies & blast radius | `.codekg/architecture/dependencies.md` |
        | Design patterns | `.codekg/architecture/patterns.md` |
        | Risky classes | `.codekg/architecture/hotspots.md` |
        | Architectural rules | `.codekg/policies/active.md` |
        | Current violations | `.codekg/policies/violations.md` |
        | Module detail | `.codekg/modules/<name>.md` |
        | Session insights | `.codekg/insights/<name>.md` |

        ### Modules in this repo
        {module_lines}

        ### CodeKG index files (no MCP required)
        All intelligence is pre-computed into `.codekg/` — read the files directly.
        No tool calls are needed to navigate the codebase:
        - **Start with `cat .codekg/INDEX.md`** — lists every available file
        - **Read `.codekg/modules/<name>.md`** — class and method detail per module
        - **Read `.codekg/policies/active.md`** — architectural rules before any change
    """).strip()

    return f"{_CODEKG_SECTION_START}\n{body}\n{_CODEKG_SECTION_END}"


def apply_claude_md_section(existing_content: str, snippet: str) -> str:
    """
    Insert or replace the CodeKG section in an existing CLAUDE.md.
    If markers are present, replaces between them.
    If not, appends to the end with a divider.
    """
    if _CODEKG_SECTION_START in existing_content:
        # Replace existing section
        start = existing_content.index(_CODEKG_SECTION_START)
        end   = existing_content.index(_CODEKG_SECTION_END) + len(_CODEKG_SECTION_END)
        return existing_content[:start] + snippet + existing_content[end:]
    else:
        # Append as new section
        return existing_content.rstrip() + "\n\n---\n\n" + snippet + "\n"


# ── Registry of all file types ────────────────────────────────────────────────

FILE_REGISTRY: list[dict] = [
    {
        "key":         "index",
        "directory":   "",
        "filename":    "INDEX.md",
        "description": "Master navigation file — read first",
        "trigger":     "any_change",
        "generator":   None,  # handled specially (needs available_files)
    },
    {
        "key":         "architecture/modules",
        "directory":   "architecture",
        "filename":    "modules.md",
        "description": "Module map with class counts and summaries",
        "trigger":     "scan_complete",
        "generator":   generate_modules,
    },
    {
        "key":         "architecture/dependencies",
        "directory":   "architecture",
        "filename":    "dependencies.md",
        "description": "Cross-module dependencies and high blast-radius classes",
        "trigger":     "scan_complete",
        "generator":   generate_dependencies,
    },
    {
        "key":         "architecture/patterns",
        "directory":   "architecture",
        "filename":    "patterns.md",
        "description": "Detected design patterns and anti-patterns",
        "trigger":     "scan_complete",
        "generator":   generate_patterns,
    },
    {
        "key":         "architecture/hotspots",
        "directory":   "architecture",
        "filename":    "hotspots.md",
        "description": "High blast-radius, low hygiene classes to approach carefully",
        "trigger":     "hygiene_change",
        "generator":   generate_hotspots,
    },
    {
        "key":         "policies/active",
        "directory":   "policies",
        "filename":    "active.md",
        "description": "Active architectural policies — read before making changes",
        "trigger":     "policy_change",
        "generator":   generate_policies_active,
    },
    {
        "key":         "policies/violations",
        "directory":   "policies",
        "filename":    "violations.md",
        "description": "Current policy violations by class",
        "trigger":     "scan_complete",
        "generator":   generate_violations,
    },
    {
        "key":         "insights/index",
        "directory":   "insights",
        "filename":    "index.md",
        "description": "Index of all captured insights by area",
        "trigger":     "insight_added",
        "generator":   generate_insights_index,
    },
    {
        "key":         "claude_md",
        "directory":   "",
        "filename":    "CLAUDE.md",
        "description": "Snippet to paste into repo root CLAUDE.md",
        "trigger":     "any_change",
        "generator":   generate_claude_md_snippet,
    },
    {
        "key":         "agents_md",
        "directory":   "",
        "filename":    "AGENTS.md",
        "description": "Snippet to paste into repo root AGENTS.md (Codex / OpenAI Codex agents)",
        "trigger":     "any_change",
        "generator":   generate_agents_md_snippet,
    },
]
