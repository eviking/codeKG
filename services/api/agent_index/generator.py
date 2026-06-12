"""
Agent Index Generator
Generates .codekg/ index files from the knowledge graph.
Each file is kept small and focused so agents load only what they need.
"""
from __future__ import annotations

import textwrap
from datetime import datetime, timezone

from typing import Callable as _Callable

from shared.config import cfg

# Injected by the host application (api/main.py) after the Neo4j driver is ready.
# Falls back to a no-op so the module can be imported without a live driver.
def _noop_query(*a, **kw): return []
run_query: _Callable = _noop_query

# No caps — truncating index files silently breaks Claude Code's understanding.
# Files can be as large as needed; Claude Code handles them fine.
class _DefaultZero(dict):
    """Dictionary that falls back to zero for missing counters. Watch out for silent key creation here, because summary math relies on absent buckets behaving like empty counts."""

    def __missing__(self, key): return 0
_CAP = _DefaultZero()

# Repos whose total source LOC is below this threshold get a single combined index
# file instead of separate per-module files — eliminates the need for extra reads.
_COMBINED_LOC_THRESHOLD: int = cfg.agent_index.combined_loc_threshold

def _TS() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

# Injected at publish time so generators can embed the current commit SHA.
# Falls back to "unpublished" when called outside a publish context.
_current_publish_sha: str = "unpublished"


def _cap(text: str, limit: int) -> str:
    return text  # no truncation — partial files are worse than large files


# ── INDEX.md ─────────────────────────────────────────────────────────────────

def generate_index(repo_id: str, available_files: list[dict], recent_commits: list[dict] | None = None) -> str:
    """
    Master navigation file — agent reads this first to orient,
    then reads the specific files relevant to the task.
    Files are kept current by git-commit-triggered scans.
    """
    lines = [
        f"# CodeKG Agent Index — {repo_id}",
        f"_Generated {_TS()} · commit `{_current_publish_sha}` · kept current by git commit triggers_",
        "",
        "## ⚠ STOP — read this before doing anything",
        "",
        "Do **NOT** use `find`, `ls`, `grep`, or open source files to understand this codebase.",
        "The files in `.codekg/` contain complete, pre-computed intelligence — use them instead.",
        "They include every class, every method with full parameter and return type signatures,",
        "blast radius, hygiene grades, architectural rules, and session insights.",
        "",
    ]

    # Build set of visible file keys so we only reference files that will exist on disk
    visible_keys = {f["file_key"] for f in available_files}

    required_reading = ["**Required reading before writing any code:**"]
    step = 1
    if "policies/active" in visible_keys:
        required_reading.append(f"{step}. `.codekg/policies/active.md` — rules you must not violate")
        step += 1
    required_reading.append(f"{step}. `.codekg/modules/<name>.md` — every class and method for the module you're working in")
    step += 1
    if "architecture/hotspots" in visible_keys:
        required_reading.append(f"{step}. `.codekg/architecture/hotspots.md` — before touching any high-blast-radius class")
        step += 1
    if "insights/index" in visible_keys:
        required_reading.append(f"{step}. `.codekg/insights/index.md` — non-obvious facts from previous sessions")
    lines += required_reading
    lines += [
        "",
        "**Only call CodeKG MCP tools directly for:**",
        "- Live impact analysis on files you just changed (`get_change_impact`)",
        "- Searching for a class when you don't know its module (`search_classes`)",
        "- Submitting session telemetry (`capture_insight`) — always do this at the end",
        "",
    ]

    # Quick-reference table — only include rows for files in the visible bundle
    _QUICK_REF_ROWS = [
        ("Understand repo structure",          "architecture/modules",      ".codekg/architecture/modules.md"),
        ("Cross-module dependencies",          "architecture/dependencies",  ".codekg/architecture/dependencies.md"),
        ("Data stores & schemas",              "architecture/datastores",    ".codekg/architecture/datastores.md"),
        ("Pages/screens, routes, nav links",   "architecture/screens",       ".codekg/architecture/screens.md"),
        ("Design patterns in use",             "architecture/patterns",      ".codekg/architecture/patterns.md"),
        ("Identify risky classes",             "architecture/hotspots",      ".codekg/architecture/hotspots.md"),
        ("Architectural rules",                "policies/active",            ".codekg/policies/active.md"),
        ("Current violations",                 "policies/violations",        ".codekg/policies/violations.md"),
        ("Session insights",                   "insights/index",             ".codekg/insights/index.md"),
        ("Recent commits & index changes",     "architecture/recent_changes", ".codekg/architecture/recent_changes.md"),
    ]
    lines += ["| When you need to... | Read this file |", "|---|---|"]
    for label, key, path in _QUICK_REF_ROWS:
        if key in visible_keys:
            lines.append(f"| {label} | `{path}` |")
    lines.append("| Classes & methods in a module | `.codekg/modules/<name>.md` |")
    lines += [
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
            status   = f.get("status", "current")
            stale    = " ⚠ stale" if status == "stale" else ""
            gen_at   = (f.get("generated_at") or "")[:16].replace("T", " ")
            gen_note = f" · updated {gen_at} UTC" if gen_at else ""
            lines.append(f"- `{f['filename']}`{stale} — {f.get('description', '')}{gen_note}")

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

    # ── Recent changes ────────────────────────────────────────────────────────
    # Shows which index files were updated this publish cycle and recent repo commits.
    stale_files = [f for f in available_files if f.get("status") == "stale"]
    updated_files = [
        f for f in available_files
        if f.get("generated_at") and f.get("published_at")
        and f["generated_at"] > f["published_at"]
    ]
    all_changed = {f["file_key"] for f in stale_files + updated_files}

    if all_changed or recent_commits:
        lines += ["", "## Recent changes", ""]

    if all_changed:
        lines.append("**Index files updated this cycle:**")
        for fk in sorted(all_changed):
            f = next((x for x in available_files if x["file_key"] == fk), None)
            ts = (f.get("generated_at") or "")[:16].replace("T", " ") if f else ""
            lines.append(f"- `{fk}` — regenerated {ts} UTC")
        lines.append("")

    if recent_commits:
        lines.append("**Recent repo commits:**")
        for c in recent_commits[:15]:
            sha   = c.get("sha", "")[:8]
            msg   = c.get("message", "").split("\n")[0][:80]
            date  = c.get("date", "")[:10]
            author = c.get("author", "")
            lines.append(f"- `{sha}` {date} {author} — {msg}")
        lines.append("")

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

    _LARGE_REPO_THRESHOLD = cfg.agent_index.large_repo_threshold

    # Drop 0-class modules — they're empty directories with no useful content
    non_empty = [m for m in modules if (m.get("class_count") or 0) > 0]

    if len(modules) > _LARGE_REPO_THRESHOLD:
        # Index mode — NL description + link per module, grouped by top-level path.
        # Claude Code opens the per-module detail file for full class/method signatures.
        lines[3] = (
            f"This repository contains **{len(modules)} logical modules** "
            f"({len(non_empty)} with classes). "
            f"This file is a navigation index — scan it to find the right area, "
            f"then open the linked `.codekg/modules/<name>.md` for full class and method detail."
        )
        lines += [
            "## How to navigate",
            "",
            "1. Find the area you're working in from the list below.",
            "2. Open the linked `.codekg/modules/<name>.md` for full class and method signatures.",
            "3. Can't find it? Use `search_classes` to locate a class, then trace back to its module.",
            "",
        ]

        # Group by first path segment (top-level directory) for scannability
        groups: dict[str, list] = {}
        for m in non_empty:
            top = m['id'].split('/')[0]
            groups.setdefault(top, []).append(m)

        lines.append("## Modules by area")
        lines.append("")
        for group_name, group_modules in sorted(groups.items()):
            lines.append(f"### `{group_name}/`")
            lines.append("")
            for m in group_modules:
                safe_id = m['id'].replace('/', '--')
                hotspot_flag = f" ⚠ {m.get('hotspot_count')} hotspots" if (m.get('hotspot_count') or 0) > 0 else ""
                desc = (m.get("summary") or "").strip()
                if desc and '.' in desc:
                    desc = desc[:desc.index('.')+1]
                desc_part = f" — {desc}" if desc else ""
                lines.append(
                    f"- **[`{m['id']}`](`.codekg/modules/{safe_id}.md`)**"
                    f"{hotspot_flag} ({m['class_count']} classes){desc_part}"
                )
            lines.append("")
    else:
        # Standard mode — compact table for smaller repos
        lines += [
            "## Modules",
            "",
            "| Module | Classes | Max blast | Hotspots | Index file |",
            "|--------|---------|-----------|----------|------------|",
        ]
        for m in non_empty:
            safe_id = m['id'].replace('/', '--')
            hotspots = m.get("hotspot_count") or 0
            hotspot_cell = f"⚠ {hotspots}" if hotspots > 0 else "—"
            lines.append(
                f"| `{m['id']}` | {m['class_count']} "
                f"| {m.get('max_blast') or 0} "
                f"| {hotspot_cell} "
                f"| `.codekg/modules/{safe_id}.md` |"
            )

    return _cap("\n".join(lines), _CAP["modules"])


# ── architecture/dependencies.md ─────────────────────────────────────────────

def generate_dependencies(repo_id: str) -> str:
    # All import edges — source module → target file (target may be outside any module)
    deps = run_query("""
        MATCH (c:Class {repo_id: $repo_id})-[:IMPORTS]->(d:Class)
        OPTIONAL MATCH (mc:Module {repo_id: $repo_id}) WHERE c.file_path STARTS WITH mc.path
        OPTIONAL MATCH (md:Module {repo_id: $repo_id}) WHERE d.file_path STARTS WITH md.path
        WITH coalesce(mc.module_id, 'external') AS from_module,
             coalesce(md.module_id, split(d.file_path, '/')[-2] + '/' + split(d.file_path, '/')[-1]) AS to_target,
             count(*) AS edge_count
        WHERE from_module <> to_target
        RETURN from_module, to_target, edge_count
        ORDER BY edge_count DESC
        LIMIT 40
    """, repo_id=repo_id)

    # High blast radius classes (lower threshold to show something)
    blast = run_query("""
        MATCH (c:Class {repo_id: $repo_id})
        WHERE c.blast_size > 0
        RETURN c.name AS name, c.fqn AS fqn, c.blast_size AS blast,
               c.file_path AS file_path,
               c.javadoc AS javadoc, c.summary AS summary
        ORDER BY c.blast_size DESC LIMIT 15
    """, repo_id=repo_id)

    lines = [
        f"# Key Dependencies — {repo_id}",
        f"_Generated {_TS()}_",
        "",
        "## Import edges by module",
        "All outgoing imports from each module, including to shared/external code.",
        "",
        "| From module | To | Import edges |",
        "|---|---|---|",
    ]
    for d in deps:
        lines.append(f"| `{d['from_module']}` | `{d['to_target']}` | {d['edge_count']} |")

    if not deps:
        lines.append("_No import edges detected between classes._")

    lines += [
        "",
        "## Highest blast radius classes",
        "Changing these classes affects the most dependents — approach with care.",
        "",
    ]
    if blast:
        for b in blast:
            doc = (b.get("javadoc") or b.get("summary") or "").strip()
            fp = (b.get("file_path") or "")
            fp = _shorten_fp(fp, "")
            lines.append(f"### `{b['name']}` — blast {b['blast']} classes")
            lines.append(f"**FQN:** `{b['fqn']}`  **File:** `{fp}`")
            if doc:
                lines.append(f"> {doc[:200]}")
            lines.append("")
    else:
        lines.append("_No classes with blast radius > 0 detected._")
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
            lines += ["| Class | Policy | Blast | File |", "|---|---|---|---|"]
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


# ── Path helpers ─────────────────────────────────────────────────────────────

def _get_repo_path(repo_id: str) -> str:
    """Return the on-disk repo root path from the KG, or empty string."""
    rows = run_query(
        "MATCH (r:Repository {repo_id: $repo_id}) RETURN r.path AS path LIMIT 1",
        repo_id=repo_id,
    )
    return (rows[0].get("path") or "") if rows else ""


def _shorten_fp(fp: str, repo_path: str) -> str:
    """
    Shorten an absolute file path to a repo-relative path.
    Uses the known repo_path prefix first, then falls back to stripping
    the /host-home mount prefix so the result is portable across machines.
    """
    if not fp:
        return fp
    # Try repo_path prefix (most precise)
    if repo_path:
        # Normalise for case-insensitive file systems (macOS host paths)
        for candidate in (repo_path, repo_path.lower()):
            if fp.startswith(candidate + "/"):
                return fp[len(candidate) + 1:]
            if fp.lower().startswith(candidate.lower() + "/"):
                return fp[len(candidate) + 1:]
    # Fallback: strip /host-home/<anything>/ up to the first path component
    # that looks like a project root (heuristic: 4+ path components after /host-home)
    if "/host-home/" in fp:
        after = fp.split("/host-home/", 1)[1]   # e.g. Documents/projects/myrepo/src/Foo.java
        parts = after.split("/")
        # Drop components until we hit what looks like the repo — best effort
        # is to return the last 4 segments which avoids exposing home dirs
        return "/".join(parts[-4:]) if len(parts) >= 4 else after
    # Last resort: last 4 path segments
    parts = fp.replace("\\", "/").split("/")
    return "/".join(parts[-4:]) if len(parts) >= 4 else fp


# ── Shared class renderer ────────────────────────────────────────────────────


def _render_class(c: dict, heading_level: int = 3, repo_path: str = "") -> list[str]:
    """
    Render a single class with full method signatures from object_model.
    Used by both generate_module_file and generate_combined_index.
    """
    import json as _j
    hdr = "#" * heading_level
    lines = []

    grade  = c.get("grade") or "?"
    blast  = c.get("blast") or 0
    loc    = c.get("loc") or 0
    fqn    = c.get("fqn") or ""
    fp     = c.get("file_path") or ""
    # shorten file path to repo-relative
    fp = _shorten_fp(fp, repo_path)

    lines.append(f"{hdr} `{c['name']}` — {c.get('kind') or 'class'}")
    meta = f"**File:** `{fp}`"
    if loc:
        meta += f"  **LOC:** {loc}"
    meta += f"  **Grade:** {grade}  **Blast:** {blast}"
    lines.append(meta)
    if fqn:
        lines.append(f"**FQN:** `{fqn}`")

    doc = (c.get("summary") or c.get("javadoc") or "").strip()
    if doc:
        lines.append("")
        lines.append(doc[:400])

    # Methods from object_model — rendered as a table for clarity
    om_raw = c.get("object_model")
    if om_raw:
        try:
            om = _j.loads(om_raw) if isinstance(om_raw, str) else om_raw
            methods = om.get("methods") or []
            if methods:
                lines.append("")
                lines.append("| Method | Parameters | Returns | Notes |")
                lines.append("|--------|-----------|---------|-------|")
                for m in methods:
                    name   = m.get("name", "")
                    ret    = m.get("return_type") or "—"
                    params = m.get("parameters") or []
                    mods   = m.get("modifiers") or []
                    m_sum  = (m.get("summary") or m.get("javadoc") or "").strip()
                    mod_str = " ".join(mods) + " " if mods else ""
                    param_str = "<br>".join(f"`{p}`" for p in params) if params else "—"
                    ret_str = f"`{ret}`" if ret != "—" else "—"
                    note = m_sum[:120] if m_sum else ""
                    lines.append(f"| `{mod_str}{name}` | {param_str} | {ret_str} | {note} |")
        except (ValueError, KeyError):
            pass

    # Used by — classes that depend on this one (blast_radius FQNs)
    dependents = c.get("blast_radius") or []
    if isinstance(dependents, str):
        try:
            dependents = _j.loads(dependents)
        except ValueError:
            dependents = []
    if dependents:
        lines.append("")
        lines.append("**Used by:**")
        for dep_fqn in sorted(set(dependents))[:10]:
            lines.append(f"- `{dep_fqn}`")
        if len(dependents) > 10:
            lines.append(f"- _…and {len(dependents) - 10} more_")

    lines.append("")
    return lines


# ── Shared module data fetcher ────────────────────────────────────────────────

def _datastores_for_module(module_path: str) -> list[dict]:
    """
    Scan source files under module_path and return list of
    {id, label, type, files} for each detected data store.
    The module_path is the absolute path on the container filesystem.
    """
    import os as _os_m
    if not module_path or not _os_m.path.isdir(module_path):
        return []
    store_files: dict[str, list[str]] = {}
    _SKIP_M = {"__pycache__", ".venv", "venv", "site-packages"}
    for root, dirs, files in _os_m.walk(module_path):
        dirs[:] = [d for d in dirs if d not in _SKIP_M]
        for fname in files:
            if not fname.endswith(".py"):
                continue
            full = _os_m.path.join(root, fname)
            rel  = _os_m.path.relpath(full, module_path)
            for store_id in _scan_file_for_stores(full):
                store_files.setdefault(store_id, []).append(rel)
    result = []
    sig_map = {s[0]: (s[1], s[2]) for s in _DS_SIGNATURES}
    for store_id, files in sorted(store_files.items()):
        label, ds_type = sig_map.get(store_id, (store_id, "unknown"))
        result.append({"id": store_id, "label": label, "type": ds_type,
                        "files": sorted(set(files))})
    return result


def _fetch_module_data(repo_id: str, module_path: str, module_id: str) -> dict:
    """Fetch all data needed to render a module. Returns a dict of lists."""
    classes = run_query("""
        MATCH (c:Class {repo_id: $repo_id})
        WHERE c.file_path STARTS WITH $path AND NOT c.kind IN ['module']
        RETURN c.name AS name, c.fqn AS fqn, c.kind AS kind,
               c.hygiene_grade AS grade, c.blast_size AS blast,
               c.start_line AS start_line, c.end_line AS end_line,
               c.javadoc AS javadoc, c.summary AS summary,
               c.file_path AS file_path, c.object_model AS object_model,
               c.blast_radius AS blast_radius
        ORDER BY c.blast_size DESC, c.name
        LIMIT 80
    """, repo_id=repo_id, path=module_path)

    # Add LOC per class from end_line
    for c in classes:
        sl = c.get("start_line") or 0
        el = c.get("end_line") or 0
        c["loc"] = (el - sl) if el > sl else 0

    incoming_deps = run_query("""
        MATCH (caller:Class {repo_id: $repo_id})-[:IMPORTS]->(c:Class {repo_id: $repo_id})
        WHERE c.file_path STARTS WITH $path
          AND NOT caller.file_path STARTS WITH $path
        WITH caller.file_path AS fp, count(*) AS edge_count
        RETURN fp, edge_count ORDER BY edge_count DESC LIMIT 10
    """, repo_id=repo_id, path=module_path)

    outgoing_deps = run_query("""
        MATCH (c:Class {repo_id: $repo_id})-[:IMPORTS]->(dep:Class {repo_id: $repo_id})
        WHERE c.file_path STARTS WITH $path
          AND NOT dep.file_path STARTS WITH $path
        WITH dep.file_path AS fp, count(*) AS edge_count
        RETURN fp, edge_count ORDER BY edge_count DESC LIMIT 10
    """, repo_id=repo_id, path=module_path)

    module_dot = module_id.replace("/", ".")
    insights = run_query("""
        MATCH (tk:TribalKnowledge {repo_id: $repo_id})
        WHERE tk.applies_to CONTAINS $module_dot
           OR tk.applies_to CONTAINS $module_id
           OR tk.module_id = $module_id
        RETURN tk.insight AS insight, tk.scope AS scope,
               tk.applies_to AS applies_to, tk.confidence AS confidence
        ORDER BY tk.confidence DESC LIMIT 10
    """, repo_id=repo_id, module_id=module_id, module_dot=module_dot)

    datastores = _datastores_for_module(module_path)

    return {"classes": classes, "incoming_deps": incoming_deps,
            "outgoing_deps": outgoing_deps, "insights": insights,
            "datastores": datastores}


def _render_module_body(module_id: str, m: dict, data: dict,
                        heading_offset: int = 0, repo_path: str = "") -> list[str]:
    """
    Render one module's full content as a list of lines.
    heading_offset=0 → top-level headings (##); 1 → one level deeper (###) etc.
    """
    h1 = "#" * (1 + heading_offset)
    h2 = "#" * (2 + heading_offset)

    classes      = data["classes"]
    incoming     = data["incoming_deps"]
    outgoing     = data["outgoing_deps"]
    insights     = data["insights"]
    datastores   = data.get("datastores") or []
    module_path  = m.get("path") or ""

    lines = [
        f"{h1} Module: {m.get('name') or module_id}",
        f"_Generated {_TS()} · commit `{_current_publish_sha}`_",
        "",
        f"**Path:** `{module_path or '(root)'}`  **Classes:** {len(classes)}",
        "",
    ]

    if m.get("summary"):
        lines += [m["summary"][:400], ""]

    # Used by — which other modules import from this one
    if incoming:
        lines += [f"{h2} Used by", ""]
        lines.append("_Other modules that import from this one:_")
        lines.append("")
        for d in incoming:
            short = _shorten_fp(d.get("fp") or "", "")
            short = "/".join(short.replace("\\", "/").split("/")[-3:]) if short else d.get("fp", "")
            lines.append(f"- `{short}` — {d['edge_count']} import(s)")
        lines.append("")

    # Depends on — what this module imports from others
    if outgoing:
        lines += [f"{h2} Depends on", ""]
        lines.append("_External files/modules this module imports from:_")
        lines.append("")
        for d in outgoing:
            short = _shorten_fp(d.get("fp") or "", "")
            short = "/".join(short.replace("\\", "/").split("/")[-3:]) if short else d.get("fp", "")
            lines.append(f"- `{short}` — {d['edge_count']} import(s)")
        lines.append("")

    # Data stores used by this module
    if datastores:
        lines += [f"{h2} Data stores", ""]
        lines.append("_Detected from source file imports and connection patterns:_")
        lines.append("")
        for ds in datastores:
            lines.append(f"- **{ds['label']}** ({ds['type']}) — see `.codekg/architecture/datastores.md` for schema")
            for f in ds["files"]:
                lines.append(f"  - `{f}`")
        lines.append("")

    # Routes defined in this module (FastAPI route handlers → template → context)
    import os as _os_routes
    route_screens: list[dict] = []
    if module_path and _os_routes.path.isdir(module_path):
        _SKIP = {"__pycache__", ".venv", "venv", "site-packages", ".git"}
        for root, dirs, files in _os_routes.walk(module_path):
            dirs[:] = [d for d in dirs if d not in _SKIP]
            if _os_routes.path.basename(root) == "routes" or root == module_path:
                for fname in sorted(files):
                    if not fname.endswith(".py"):
                        continue
                    fpath = _os_routes.path.join(root, fname)
                    try:
                        screens = _parse_route_file(fpath)
                    except (OSError, SyntaxError, ValueError):
                        screens = []
                    for s in screens:
                        if s.get("template") or s.get("is_page"):
                            rel = _os_routes.path.relpath(fpath, module_path)
                            s["_rel_file"] = rel
                            route_screens.append(s)

    if route_screens:
        lines += [f"{h2} Routes", ""]
        lines.append("_FastAPI route handlers in this module — what each renders, its template, and template context._")
        lines.append("")
        lines += [
            "| Method | URL | Template | Parameters | Template context |",
            "|--------|-----|----------|------------|-----------------|",
        ]
        for s in sorted(route_screens, key=lambda x: (x["url"], x["method"])):
            tpl    = s.get("template") or "—"
            params = ", ".join(s.get("query_params") or []) or "—"
            ctx    = ", ".join(f"`{v}`" for v in (s.get("ctx_vars") or [])) or "—"
            lines.append(
                f"| `{s['method']}` | `{s['url']}` | `{tpl}` | {params} | {ctx} |"
            )
        lines.append("")

    # Insights pinned at top
    if insights:
        lines += [f"{h2} ⚡ Insights from previous sessions", ""]
        lines.append("_Non-obvious facts from engineering sessions — treat as expert hints._")
        lines.append("")
        for i in insights:
            conf = int((i.get("confidence") or 0.7) * 100)
            lines.append(f"- **{i.get('applies_to', '')}** ({conf}%): {i['insight']}")
        lines.append("")

    # All classes with full method detail
    lines += [f"{h2} Classes", ""]
    for c in classes:
        lines.extend(_render_class(c, heading_level=2 + heading_offset + 1, repo_path=repo_path))

    return lines


# ── modules/<name>.md ────────────────────────────────────────────────────────

def generate_module_file(repo_id: str, module_id: str) -> str:
    module = run_query("""
        MATCH (m:Module {repo_id: $repo_id, module_id: $module_id})
        RETURN m.name AS name, m.path AS path, m.summary AS summary
    """, repo_id=repo_id, module_id=module_id)

    if not module:
        return f"# Module `{module_id}` not found\n"
    m = module[0]
    repo_path = _get_repo_path(repo_id)
    data = _fetch_module_data(repo_id, m.get("path") or "", module_id)
    lines = _render_module_body(module_id, m, data, heading_offset=0, repo_path=repo_path)
    return _cap("\n".join(lines), _CAP["module_file"])


# ── combined all-modules index (used when total repo LOC < threshold) ─────────

def get_repo_total_loc(repo_id: str) -> int:
    """Sum of max(end_line) per file across the whole repo."""
    rows = run_query("""
        MATCH (c:Class {repo_id: $repo_id})
        WHERE c.end_line IS NOT NULL AND c.end_line > 0
        WITH c.file_path AS fp, max(c.end_line) AS loc
        RETURN sum(loc) AS total_loc
    """, repo_id=repo_id)
    return int((rows[0].get("total_loc") or 0) if rows else 0)


def generate_combined_index(repo_id: str) -> str:
    """
    Single file containing ALL modules with full class+method detail.
    Used when total repo LOC < _COMBINED_LOC_THRESHOLD so agents never
    need to open a separate module file.
    """
    modules = run_query(
        "MATCH (m:Module {repo_id: $repo_id}) RETURN m.module_id AS id, "
        "m.name AS name, m.path AS path, m.summary AS summary ORDER BY m.module_id",
        repo_id=repo_id,
    )

    lines = [
        f"# Full Codebase Index — {repo_id}",
        f"_Generated {_TS()} · all modules inlined (repo LOC below {_COMBINED_LOC_THRESHOLD} threshold)_",
        "",
        "This file contains complete class and method detail for every module.",
        "No additional file reads needed — everything is here.",
        "",
    ]

    repo_path = _get_repo_path(repo_id)
    for mod in modules:
        data = _fetch_module_data(repo_id, mod.get("path") or "", mod["id"])
        lines.extend(_render_module_body(mod["id"], mod, data, heading_offset=0, repo_path=repo_path))
        lines.append("---")
        lines.append("")

    return _cap("\n".join(lines), _CAP["combined"])


# ── insights/<name>.md ───────────────────────────────────────────────────────

def generate_insights_module(repo_id: str, module_id: str) -> str:
    module_dot = module_id.replace("/", ".")
    insights = run_query("""
        MATCH (tk:TribalKnowledge {repo_id: $repo_id})
        WHERE (tk.applies_to CONTAINS $module_dot
           OR tk.applies_to CONTAINS $module_id
           OR tk.module_id = $module_id)
          AND coalesce(tk.approved, false) = true
          AND coalesce(tk.hidden, false) = false
          AND coalesce(tk.importance, 50) > 75
        RETURN tk.insight AS insight, tk.scope AS scope,
               tk.applies_to AS applies_to, tk.confidence AS confidence,
               tk.importance AS importance, tk.created_at AS created_at,
               tk.technical_debt AS technical_debt
        ORDER BY tk.importance DESC, tk.confidence DESC, tk.created_at DESC
        LIMIT 30
    """, repo_id=repo_id, module_id=module_id, module_dot=module_dot)

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
                if i.get("technical_debt"):
                    lines.append("")
                    lines.append("**Technical debt observed:**")
                    lines.append(i["technical_debt"])
                lines.append("")
    else:
        lines.append("_No insights recorded for this module yet._")
        lines.append("Insights are captured automatically when agents submit session telemetry.")

    return _cap("\n".join(lines), _CAP["insights"])


# ── datastores/ ──────────────────────────────────────────────────────────────

import sqlite3 as _sqlite3

# Known data store signatures: (store_id, label, type, detector_patterns)
# detector_patterns: list of strings that appear in source files using this store
_DS_SIGNATURES = [
    ("neo4j",       "Neo4j",            "graph",   ["from neo4j import", "GraphDatabase.driver", "neo4j import Driver"]),
    ("telemetry",   "telemetry.db",     "sqlite",  ["TELEMETRY_DB", "telemetry.db"]),
    ("llm_audit",   "llm_audit.db",     "sqlite",  ["AUDIT_DB_PATH", "llm_audit.db", "llm_audit"]),
    ("mcp_audit",   "mcp_audit.db",     "sqlite",  ["MCP_AUDIT_DB", "mcp_audit.db"]),
    ("agent_index", "agent_index.db",   "sqlite",  ["AGENT_INDEX_DB", "agent_index.db", "agent_index/store"]),
    ("scan_log",    "scan_log.db",      "sqlite",  ["scan_log.db", "SCAN_LOG_DB", "scan_log"]),
]

def _ds_env_to_path() -> dict:
    """Env-var → live runtime path (from cfg so paths reflect actual installation)."""
    from shared.config import cfg as _c
    return {
        "TELEMETRY_DB":   _c.paths.telemetry_db,
        "AUDIT_DB_PATH":  _c.paths.llm_audit_db,
        "MCP_AUDIT_DB":   _c.paths.mcp_audit_db,
        "AGENT_INDEX_DB": _c.agent_index.db_path,
    }


def _scan_file_for_stores(path: str) -> list[str]:
    """Return list of store_ids used in a source file."""
    try:
        text = open(path, encoding="utf-8", errors="replace").read()
    except OSError:
        return []
    found = []
    for store_id, _, _, patterns in _DS_SIGNATURES:
        if any(p in text for p in patterns):
            found.append(store_id)
    return found


def _sqlite_schema(db_path: str) -> list[dict]:
    """Return list of {table, columns} from a live SQLite DB."""
    try:
        con = _sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=3)
        tables = con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
        result = []
        for (tname,) in tables:
            cols = con.execute(f"PRAGMA table_info({tname})").fetchall()
            result.append({
                "table": tname,
                "columns": [
                    {
                        "name": c[1], "type": c[2],
                        "not_null": bool(c[3]), "pk": bool(c[5]),
                    }
                    for c in cols
                ],
            })
        con.close()
        return result
    except Exception:  # DB may not exist yet or have wrong schema — return empty
        return []


def _detect_datastores(repo_path: str) -> dict[str, dict]:
    """
    Scan repo source files and return a dict of:
      store_id → {label, type, schema, modules_using}
    """
    import os as _os_ds
    stores: dict[str, dict] = {}

    # Normalise path: try lowercase variant if the exact path doesn't exist
    if repo_path and not _os_ds.path.isdir(repo_path):
        alt = repo_path[:-len(repo_path.lstrip("/"))] + repo_path.lstrip("/").lower()
        if _os_ds.path.isdir(alt):
            repo_path = alt
        # Also try replacing last component case
        parent, last = _os_ds.path.split(repo_path)
        lower_last = _os_ds.path.join(parent, last.lower())
        if _os_ds.path.isdir(lower_last):
            repo_path = lower_last

    if not repo_path or not _os_ds.path.isdir(repo_path):
        return {}

    # Initialise all known stores
    for store_id, label, ds_type, _ in _DS_SIGNATURES:
        stores[store_id] = {
            "id": store_id, "label": label, "type": ds_type,
            "schema": [], "files_using": [], "modules_using": set(),
        }

    _SKIP_DIRS = {"__pycache__", ".git", "node_modules", ".codekg",
                  ".venv", "venv", ".venv-test", "site-packages"}

    # Walk source files
    for root, dirs, files in _os_ds.walk(repo_path):
        dirs[:] = [d for d in dirs
                   if d not in _SKIP_DIRS and not d.startswith(".venv")]
        for fname in files:
            if not fname.endswith(".py"):
                continue
            full = _os_ds.path.join(root, fname)
            rel  = _os_ds.path.relpath(full, repo_path)
            for store_id in _scan_file_for_stores(full):
                stores[store_id]["files_using"].append(rel)
                # derive module from path (services/xxx/...)
                parts = rel.split(_os_ds.sep)
                if len(parts) >= 2 and parts[0] == "services":
                    stores[store_id]["modules_using"].add(f"{parts[0]}/{parts[1]}")

    # Introspect live SQLite DBs — paths from config so they survive installation changes
    from shared.config import cfg as _cfg_ds
    sqlite_paths = {
        "telemetry":   _cfg_ds.paths.telemetry_db,
        "llm_audit":   _cfg_ds.paths.llm_audit_db,
        "mcp_audit":   _cfg_ds.paths.mcp_audit_db,
        "agent_index": _cfg_ds.agent_index.db_path,
        "scan_log":    _cfg_ds.paths.scan_log_db,
    }
    for store_id, db_path in sqlite_paths.items():
        if store_id in stores:
            stores[store_id]["schema"] = _sqlite_schema(db_path)
            stores[store_id]["path"] = db_path

    # Convert modules_using sets to sorted lists
    for s in stores.values():
        s["modules_using"] = sorted(s["modules_using"])

    return {k: v for k, v in stores.items() if v["files_using"]}


def _render_sqlite_schema(store: dict) -> list[str]:
    lines = []
    for tbl in store.get("schema") or []:
        lines.append(f"#### `{tbl['table']}`")
        lines.append("")
        lines.append("| Column | Type | Constraints |")
        lines.append("|--------|------|-------------|")
        for col in tbl["columns"]:
            constraints = []
            if col["pk"]:       constraints.append("PK")
            if col["not_null"]: constraints.append("NOT NULL")
            lines.append(f"| `{col['name']}` | {col['type']} | {', '.join(constraints) or '—'} |")
        lines.append("")
    return lines


def generate_datastores_index(repo_id: str, repo_path: str) -> str:
    stores = _detect_datastores(repo_path)

    lines = [
        f"# Data Stores — {repo_id}",
        f"_Generated {_TS()}_",
        "",
        f"**{len(stores)} data stores detected** by scanning source files.",
        "",
        "| Store | Type | Runtime path | Modules |",
        "|-------|------|--------------|---------|",
    ]
    for s in sorted(stores.values(), key=lambda x: x["label"]):
        path = s.get("path", "—")
        mods = ", ".join(f"`{m}`" for m in s["modules_using"]) or "—"
        lines.append(f"| **{s['label']}** | {s['type']} | `{path}` | {mods} |")

    lines += ["", "---", ""]
    for s in sorted(stores.values(), key=lambda x: x["label"]):
        lines.append(f"## {s['label']} ({s['type']})")
        lines.append("")
        if s.get("path"):
            lines.append(f"**Runtime path:** `{s['path']}`")
        if s["modules_using"]:
            lines.append(f"**Used by:** {', '.join(f'`{m}`' for m in s['modules_using'])}")
        lines.append("")
        if s["files_using"]:
            lines.append("**Source files:**")
            for f in sorted(set(s["files_using"])):
                lines.append(f"- `{f}`")
            lines.append("")
        if s["type"] == "sqlite" and s.get("schema"):
            lines.append("**Schema:**")
            lines.append("")
            lines.extend(_render_sqlite_schema(s))
        elif s["type"] == "graph":
            lines.append("**Schema:** see Neo4j section below for node labels, properties, and relationships.")
            lines.append("")

    # Append full Neo4j schema at the end
    lines += ["---", "", "## Neo4j graph schema", ""]
    neo4j_content = generate_schema(repo_id)
    # Strip the title/header — we're embedding it
    neo4j_body = "\n".join(
        line for line in neo4j_content.splitlines()
        if not line.startswith("# ") and not line.startswith("_Generated")
    ).strip()
    lines.append(neo4j_body)
    lines.append("")

    return _cap("\n".join(lines), _CAP.get("datastores", 40_000))


# ── architecture/schema.md ───────────────────────────────────────────────────

def generate_schema(repo_id: str) -> str:
    """
    Neo4j graph schema for this repo — node labels, their properties with
    example values, and relationship types. Lets agents write correct Cypher
    without needing to probe the KG first.
    """
    # Node labels + property keys (sampled from real nodes)

    lines = [
        f"# Knowledge Graph Schema — {repo_id}",
        f"_Generated {_TS()}_",
        "",
        "Use this file to write correct Cypher queries without probing the KG.",
        "All nodes are scoped to a repo via `repo_id` — always include it in MATCH clauses.",
        "",
    ]

    # ── Node labels with real properties from the KG ─────────────────────────
    lines += ["## Node labels", ""]

    # Key nodes we know about — get real property samples
    key_nodes = [
        ("Class", """
            MATCH (c:Class {repo_id: $repo_id})
            RETURN c LIMIT 1
        """),
        ("Method", """
            MATCH (c:Class {repo_id: $repo_id})-[:HAS_METHOD]->(m:Method)
            RETURN m LIMIT 1
        """),
        ("Module", """
            MATCH (m:Module {repo_id: $repo_id})
            RETURN m LIMIT 1
        """),
        ("Repository", """
            MATCH (r:Repository {repo_id: $repo_id})
            RETURN r LIMIT 1
        """),
        ("ArchPolicy", """
            MATCH (ap:ArchPolicy)
            WHERE ap.repo_id = $repo_id OR ap.repo_id IS NULL
            RETURN ap LIMIT 1
        """),
        ("ArchPattern", """
            MATCH (ap:ArchPattern {repo_id: $repo_id})
            RETURN ap LIMIT 1
        """),
        ("TribalKnowledge", """
            MATCH (tk:TribalKnowledge {repo_id: $repo_id})
            RETURN tk LIMIT 1
        """),
    ]

    node_var_map = {
        "Class": "c", "Method": "m", "Module": "m",
        "Repository": "r", "ArchPolicy": "ap", "ArchPattern": "ap",
        "TribalKnowledge": "tk",
    }

    for label, cypher in key_nodes:
        rows = run_query(cypher.strip(), repo_id=repo_id)
        var = node_var_map[label]
        lines.append(f"### `{label}`")
        if rows and rows[0].get(var):
            node = dict(rows[0][var])
            # Show all property keys with truncated example values
            lines.append("| Property | Example value |")
            lines.append("|---|---|")
            for k, v in sorted(node.items()):
                if v is None:
                    continue
                ex = str(v)[:80].replace("\n", " ").replace("|", "\\|")
                lines.append(f"| `{k}` | `{ex}` |")
        else:
            lines.append("_No nodes of this type found for this repo._")
        lines.append("")

    # ── Relationship types ────────────────────────────────────────────────────
    rel_rows = run_query("""
        MATCH (a {repo_id: $repo_id})-[r]->(b)
        RETURN DISTINCT labels(a)[0] AS from_label, type(r) AS rel_type, labels(b)[0] AS to_label
        ORDER BY from_label, rel_type
        LIMIT 60
    """, repo_id=repo_id)

    if rel_rows:
        lines += ["## Relationships", ""]
        lines += ["| From | Relationship | To |", "|---|---|---|"]
        for r in rel_rows:
            lines.append(f"| `{r['from_label']}` | `:{r['rel_type']}` | `{r['to_label']}` |")
        lines.append("")

    # ── Common query patterns ─────────────────────────────────────────────────
    lines += [
        "## Common query patterns",
        "",
        "```cypher",
        "// All classes in a module",
        "MATCH (c:Class {repo_id: $repo_id}) WHERE c.file_path STARTS WITH $module_path RETURN c",
        "",
        "// Methods of a class",
        "MATCH (c:Class {repo_id: $repo_id, fqn: $fqn})-[:HAS_METHOD]->(m:Method) RETURN m",
        "",
        "// Classes that depend on a given class (blast radius)",
        "MATCH (caller:Class {repo_id: $repo_id})-[:IMPORTS]->(c:Class {repo_id: $repo_id, fqn: $fqn}) RETURN caller",
        "",
        "// Active policy violations",
        "MATCH (c:Class {repo_id: $repo_id})-[:VIOLATES]->(ap:ArchPolicy) RETURN c.fqn, ap.name, ap.severity",
        "",
        "// Insights for a class or module",
        "MATCH (tk:TribalKnowledge {repo_id: $repo_id}) WHERE tk.applies_to CONTAINS $name RETURN tk ORDER BY tk.confidence DESC",
        "```",
        "",
        "**Always filter by `repo_id`** — the KG stores multiple repos in the same database.",
    ]

    return _cap("\n".join(lines), _CAP["patterns"])  # reuse patterns cap (10K)


def generate_insights_index(repo_id: str) -> str:
    """
    Single file with ALL insights grouped by module — replaces per-module insight files.
    Module files already inline insights at the top; this file is the complete reference.
    """
    insights = run_query("""
        MATCH (tk:TribalKnowledge {repo_id: $repo_id})
        WHERE coalesce(tk.approved, false) = true
          AND coalesce(tk.hidden, false) = false
          AND coalesce(tk.importance, 50) > 75
        RETURN tk.applies_to AS applies_to, tk.scope AS scope,
               tk.insight AS insight, tk.confidence AS confidence,
               tk.importance AS importance, tk.technical_debt AS technical_debt
        ORDER BY tk.importance DESC, tk.applies_to, tk.confidence DESC
    """, repo_id=repo_id)

    lines = [
        f"# All Insights — {repo_id}",
        f"_Generated {_TS()}_",
        "",
        "Non-obvious facts captured from previous coding sessions.",
        "These are also inlined at the top of each module file.",
        f"**Total:** {len(insights)} insights",
        "",
    ]

    if not insights:
        lines.append("_No insights recorded yet. Call `capture_insight` at the end of each session._")
        return _cap("\n".join(lines), _CAP["insights"])

    # Group by a simplified module bucket (first two segments of applies_to)
    by_area: dict[str, list] = {}
    for i in insights:
        area = i["applies_to"]
        by_area.setdefault(area, []).append(i)

    for area, area_insights in sorted(by_area.items()):
        lines.append(f"## `{area}`")
        lines.append("")
        for i in area_insights:
            conf = int((i.get("confidence") or 0.7) * 100)
            scope = i.get("scope") or "class"
            lines.append(f"**[{scope}]** _{conf}% confidence_")
            lines.append(i["insight"])
            if i.get("technical_debt"):
                lines.append("")
                lines.append("**Technical debt observed:**")
                lines.append(i["technical_debt"])
            lines.append("")

    return _cap("\n".join(lines), _CAP["insights"])


# ── architecture/recent_changes.md ───────────────────────────────────────────

def generate_recent_changes(repo_id: str, repo_path: str) -> str:
    """
    Recent git commits for the repo plus a per-index-file change log.
    Helps agents understand what has changed recently without reading all files.
    """
    import subprocess as _sp
    import os as _os

    lines = [
        f"# Recent Changes — {repo_id}",
        f"_Generated {_TS()} · commit `{_current_publish_sha}`_",
        "",
        "Use this file to understand what has changed recently in both the codebase "
        "and the agent index itself, so you can focus on areas that matter.",
        "",
    ]

    # ── Git log ───────────────────────────────────────────────────────────────
    commits: list[dict] = []
    if repo_path and _os.path.isdir(repo_path):
        try:
            result = _sp.run(
                ["git", "-C", repo_path, "log", "--pretty=format:%H|%ad|%an|%s",
                 "--date=short", "-30"],
                capture_output=True, text=True, timeout=10,
            )
            for line in result.stdout.strip().splitlines():
                parts = line.split("|", 3)
                if len(parts) == 4:
                    commits.append({
                        "sha": parts[0][:8], "date": parts[1],
                        "author": parts[2], "message": parts[3],
                    })
        except (OSError, _sp.SubprocessError):
            pass

    if commits:
        lines += ["## Recent commits", ""]
        lines += ["| Commit | Date | Author | Message |", "|--------|------|--------|---------|"]
        for c in commits:
            msg = c["message"][:72].replace("|", "\\|")
            lines.append(f"| `{c['sha']}` | {c['date']} | {c['author']} | {msg} |")
        lines.append("")
    else:
        lines += ["## Recent commits", "", "_No git history available._", ""]

    # ── Changed files in last 5 commits ───────────────────────────────────────
    if commits and repo_path and _os.path.isdir(repo_path):
        try:
            result = _sp.run(
                ["git", "-C", repo_path, "diff", "--name-only",
                 "HEAD~5", "HEAD"],
                capture_output=True, text=True, timeout=10,
            )
            changed = [ln.strip() for ln in result.stdout.strip().splitlines() if ln.strip()]
            if changed:
                lines += ["## Files changed in last 5 commits", ""]
                for f in changed[:40]:
                    lines.append(f"- `{f}`")
                if len(changed) > 40:
                    lines.append(f"- _…and {len(changed) - 40} more_")
                lines.append("")
        except (OSError, _sp.SubprocessError):
            pass

    return _cap("\n".join(lines), _CAP["insights"])


# ── CLAUDE.md snippet ────────────────────────────────────────────────────────

_CODEKG_SECTION_START = "<!-- codekg:start -->"
_CODEKG_SECTION_END   = "<!-- codekg:end -->"


def generate_claude_md_snippet(repo_id: str, visible_keys: set | None = None) -> str:
    modules = run_query(
        "MATCH (m:Module {repo_id: $repo_id}) RETURN m.module_id AS id, m.name AS name "
        "ORDER BY m.module_id LIMIT 12",
        repo_id=repo_id,
    )
    total_loc = get_repo_total_loc(repo_id)
    is_combined = total_loc < _COMBINED_LOC_THRESHOLD and total_loc > 0

    def _has(key: str) -> bool:
        return visible_keys is None or key in visible_keys

    if is_combined:
        index_mode_note = textwrap.dedent(f"""
        ### Index mode: **combined** (repo LOC {total_loc} < {_COMBINED_LOC_THRESHOLD} threshold)
        This repo is small enough that ALL class and method detail is inlined into a
        single file. **Read `.codekg/modules/combined.md` first** — it contains everything
        and eliminates the need for any additional module file reads.
        """).strip()

        qr_rows = ["| Need | File |", "|---|---|",
                   "| **Everything** (classes, methods, structure) | `.codekg/modules/combined.md` |"]
        if _has("policies/active"):              qr_rows.append("| Architectural rules | `.codekg/policies/active.md` |")
        if _has("policies/violations"):          qr_rows.append("| Current violations | `.codekg/policies/violations.md` |")
        if _has("insights/index"):               qr_rows.append("| Session insights | `.codekg/insights/index.md` |")
        if _has("architecture/recent_changes"):  qr_rows.append("| Recent commits & index changes | `.codekg/architecture/recent_changes.md` |")
        quick_ref = "### Quick reference\n" + "\n".join(qr_rows)

        br_steps = ["### Required reading — do this before writing a single line of code",
                    "1. **Read `.codekg/modules/combined.md`** — every class, every method, full signatures"]
        step = 2
        if _has("policies/active"):
            br_steps.append(f"{step}. **Read `.codekg/policies/active.md`** — architectural rules you must not violate")
            step += 1
        if _has("insights/index"):
            br_steps.append(f"{step}. **Read `.codekg/insights/index.md`** — non-obvious facts from previous sessions")
        br_steps.append("If you skip these, you will write code that conflicts with existing patterns.")
        before_task = "\n".join(br_steps)

        mcp_note = textwrap.dedent("""
        ### When to call CodeKG MCP tools directly
        The combined index covers everything. Only go direct for:
        - **`get_change_impact`** — live blast radius on files you just modified
        - **`search_classes`** — finding a class across all repos
        - **`capture_insight`** — always call this when you discover something non-obvious
        """).strip()
    else:
        index_mode_note = textwrap.dedent(f"""
        ### Index mode: **per-module** (repo LOC {total_loc} — separate files per module)
        Each module has its own index file with full class and method detail.
        Read the relevant module file before writing any code in that area.
        """).strip()

        qr_rows = ["| Need | File |", "|---|---|"]
        if _has("architecture/modules"):      qr_rows.append("| Repo structure & module list | `.codekg/architecture/modules.md` |")
        if _has("architecture/dependencies"): qr_rows.append("| Cross-module dependencies | `.codekg/architecture/dependencies.md` |")
        if _has("architecture/datastores"):   qr_rows.append("| All data stores + schemas | `.codekg/architecture/datastores.md` |")
        if _has("architecture/screens"):      qr_rows.append("| Pages/screens, routes, nav links | `.codekg/architecture/screens.md` |")
        if _has("architecture/patterns"):     qr_rows.append("| Design patterns | `.codekg/architecture/patterns.md` |")
        if _has("architecture/hotspots"):     qr_rows.append("| Risky classes | `.codekg/architecture/hotspots.md` |")
        if _has("policies/active"):           qr_rows.append("| Architectural rules | `.codekg/policies/active.md` |")
        if _has("policies/violations"):       qr_rows.append("| Current violations | `.codekg/policies/violations.md` |")
        qr_rows.append("| Full module detail (classes + methods) | `.codekg/modules/<name>.md` |")
        if _has("insights/index"):                 qr_rows.append("| Session insights | `.codekg/insights/index.md` |")
        if _has("architecture/recent_changes"):    qr_rows.append("| Recent commits & index changes | `.codekg/architecture/recent_changes.md` |")
        quick_ref = "### Quick reference\n" + "\n".join(qr_rows)

        br_steps = ["### Required reading — do this before writing a single line of code"]
        step = 1
        if _has("policies/active"):
            br_steps.append(f"{step}. **Read `.codekg/policies/active.md`** — architectural rules you must not violate")
            step += 1
        br_steps.append(f"{step}. **Read `.codekg/modules/<name>.md`** for the module you're working in")
        br_steps.append("   — every class, every method with full parameter and return type signatures")
        step += 1
        if _has("architecture/hotspots"):
            br_steps.append(f"{step}. **Read `.codekg/architecture/hotspots.md`** if you plan to touch any high-blast-radius class")
            step += 1
        if _has("insights/index"):
            br_steps.append(f"{step}. **Read `.codekg/insights/index.md`** — non-obvious facts from previous sessions")
        br_steps.append("If you skip these, you will write code that conflicts with existing patterns.")
        before_task = "\n".join(br_steps)

        mcp_note = textwrap.dedent("""
        ### When to call CodeKG MCP tools directly
        The module index files cover most tasks. Only go direct for:
        - **`get_change_impact`** — live blast radius on files you just modified
        - **`search_classes`** — finding a class when you don't know its module
        - **`capture_insight`** — always call this when you discover something non-obvious
        """).strip()

    module_list = "\n".join(
        f"- `{m['id']}`" + (f" — {m['name']}" if m.get("name") else "")
        for m in modules
    )

    parts = [
        "## CodeKG Agent Index",
        "_Auto-maintained — regenerated on every git commit. Do not edit this section manually._",
        "",
        "## ⚠ MANDATORY: Read before doing anything else",
        "",
        "**DO NOT** use `find`, `ls`, `grep`, or `Read` to explore this codebase.",
        "**DO NOT** open source files to understand structure, find classes, or read method signatures.",
        "**DO NOT** start writing code without first reading the index files below.",
        "",
        "Pre-computed index files in `.codekg/` contain **complete, always-current** class and method",
        "detail for every module. They were built from the full AST and knowledge graph — they are more",
        "complete and accurate than anything you would find by exploring source files manually.",
        "Raw file exploration wastes your context window and produces incomplete understanding.",
        "",
        "**Your first action on every task MUST be:**",
        "```",
        "Read .codekg/INDEX.md",
        "```",
        "This takes 2 seconds and tells you exactly which files to read next.",
        "",
        index_mode_note,
        "",
        before_task,
        "",
        quick_ref,
        "",
        "### Modules in this repo",
        module_list,
        "",
        mcp_note,
    ]
    body = "\n".join(parts)
    return f"{_CODEKG_SECTION_START}\n{body}\n{_CODEKG_SECTION_END}"


def generate_agents_md_snippet(repo_id: str, visible_keys: set | None = None) -> str:
    """Same as generate_claude_md_snippet but omits MCP tool references (Codex has no MCP)."""
    # Reuse the claude_md body — it contains no MCP calls in the static text.
    # We only swap the final 'When to call CodeKG MCP tools' section for a
    # shell-command equivalent that Codex can actually execute.
    modules = run_query(
        "MATCH (m:Module {repo_id: $repo_id}) RETURN m.module_id AS id, m.name AS name "
        "ORDER BY m.module_id LIMIT 12",
        repo_id=repo_id,
    )
    total_loc = get_repo_total_loc(repo_id)
    is_combined = total_loc < _COMBINED_LOC_THRESHOLD and total_loc > 0

    def _has(key: str) -> bool:
        return visible_keys is None or key in visible_keys

    if is_combined:
        index_mode_note = textwrap.dedent(f"""
        ### Index mode: **combined** (repo LOC {total_loc} < {_COMBINED_LOC_THRESHOLD} threshold)
        This repo is small enough that ALL class and method detail is inlined into a
        single file. **Read `.codekg/modules/combined.md` first** — it contains everything
        and eliminates the need for any additional module file reads.
        """).strip()

        qr_rows = ["| Need | File |", "|---|---|",
                   "| **Everything** (classes, methods, structure) | `.codekg/modules/combined.md` |"]
        if _has("policies/active"):             qr_rows.append("| Architectural rules | `.codekg/policies/active.md` |")
        if _has("policies/violations"):         qr_rows.append("| Current violations | `.codekg/policies/violations.md` |")
        if _has("insights/index"):              qr_rows.append("| Session insights | `.codekg/insights/index.md` |")
        if _has("architecture/recent_changes"): qr_rows.append("| Recent commits & index changes | `.codekg/architecture/recent_changes.md` |")
        quick_ref = "### Quick reference\n" + "\n".join(qr_rows)

        br_steps = ["### Required reading — do this before writing a single line of code",
                    "1. **Read `.codekg/modules/combined.md`** — every class, every method, full signatures"]
        step = 2
        if _has("policies/active"):
            br_steps.append(f"{step}. **Read `.codekg/policies/active.md`** — architectural rules you must not violate")
            step += 1
        if _has("insights/index"):
            br_steps.append(f"{step}. **Read `.codekg/insights/index.md`** — non-obvious facts from previous sessions")
        br_steps.append("If you skip these, you will write code that conflicts with existing patterns.")
        before_task = "\n".join(br_steps)

        shell_note = textwrap.dedent("""
        ### CodeKG index files (no MCP required)
        All intelligence is pre-computed into `.codekg/` — just read the files directly.
        No tool calls needed to navigate the codebase:
        - **Read `.codekg/INDEX.md`** first — it lists every available file
        - **Read `.codekg/modules/combined.md`** — complete class and method detail
        - **Read `.codekg/policies/active.md`** — architectural rules
        """).strip()
    else:
        index_mode_note = textwrap.dedent(f"""
        ### Index mode: **per-module** (repo LOC {total_loc} — separate files per module)
        Each module has its own index file with full class and method detail.
        Read the relevant module file before writing any code in that area.
        """).strip()

        qr_rows = ["| Need | File |", "|---|---|"]
        if _has("architecture/modules"):      qr_rows.append("| Repo structure & module list | `.codekg/architecture/modules.md` |")
        if _has("architecture/dependencies"): qr_rows.append("| Cross-module dependencies | `.codekg/architecture/dependencies.md` |")
        if _has("architecture/datastores"):   qr_rows.append("| All data stores + schemas | `.codekg/architecture/datastores.md` |")
        if _has("architecture/screens"):      qr_rows.append("| Pages/screens, routes, nav links | `.codekg/architecture/screens.md` |")
        if _has("architecture/patterns"):     qr_rows.append("| Design patterns | `.codekg/architecture/patterns.md` |")
        if _has("architecture/hotspots"):     qr_rows.append("| Risky classes | `.codekg/architecture/hotspots.md` |")
        if _has("policies/active"):           qr_rows.append("| Architectural rules | `.codekg/policies/active.md` |")
        if _has("policies/violations"):       qr_rows.append("| Current violations | `.codekg/policies/violations.md` |")
        qr_rows.append("| Full module detail (classes + methods) | `.codekg/modules/<name>.md` |")
        if _has("insights/index"):                qr_rows.append("| Session insights | `.codekg/insights/index.md` |")
        if _has("architecture/recent_changes"):   qr_rows.append("| Recent commits & index changes | `.codekg/architecture/recent_changes.md` |")
        quick_ref = "### Quick reference\n" + "\n".join(qr_rows)

        br_steps = ["### Required reading — do this before writing a single line of code"]
        step = 1
        if _has("policies/active"):
            br_steps.append(f"{step}. **Read `.codekg/policies/active.md`** — architectural rules you must not violate")
            step += 1
        br_steps.append(f"{step}. **Read `.codekg/modules/<name>.md`** for the module you're working in")
        br_steps.append("   — every class, every method with full parameter and return type signatures")
        step += 1
        if _has("architecture/hotspots"):
            br_steps.append(f"{step}. **Read `.codekg/architecture/hotspots.md`** if you plan to touch any high-blast-radius class")
            step += 1
        if _has("insights/index"):
            br_steps.append(f"{step}. **Read `.codekg/insights/index.md`** — non-obvious facts from previous sessions")
        br_steps.append("If you skip these, you will write code that conflicts with existing patterns.")
        before_task = "\n".join(br_steps)

        shell_note = textwrap.dedent("""
        ### CodeKG index files (no MCP required)
        All intelligence is pre-computed into `.codekg/` — just read the files directly.
        No tool calls needed to navigate the codebase:
        - **Read `.codekg/INDEX.md`** first — it lists every available file
        - **Read `.codekg/modules/<name>.md`** — class and method detail per module
        - **Read `.codekg/policies/active.md`** — architectural rules
        - **Read `.codekg/architecture/hotspots.md`** — before touching high-blast-radius files
        """).strip()

    module_list = "\n".join(
        f"- `{m['id']}`" + (f" — {m['name']}" if m.get("name") else "")
        for m in modules
    )

    parts = [
        "## CodeKG Agent Index",
        "_Auto-maintained — regenerated on every git commit. Do not edit this section manually._",
        "",
        "## ⚠ MANDATORY: Read before doing anything else",
        "",
        "**DO NOT** use `find`, `ls`, `grep`, or read source files to explore this codebase.",
        "**DO NOT** open source files to understand structure, find classes, or read method signatures.",
        "**DO NOT** start writing code without first reading the index files below.",
        "",
        "Pre-computed index files in `.codekg/` contain **complete, always-current** class and method",
        "detail for every module. They were built from the full AST and knowledge graph — they are more",
        "complete and accurate than anything you would find by exploring source files manually.",
        "Raw file exploration wastes your context window and produces incomplete understanding.",
        "",
        "**Your first action on every task MUST be:**",
        "```",
        "cat .codekg/INDEX.md",
        "```",
        "This takes 2 seconds and tells you exactly which files to read next.",
        "",
        index_mode_note,
        "",
        before_task,
        "",
        quick_ref,
        "",
        "### Modules in this repo",
        module_list,
        "",
        shell_note,
    ]
    body = "\n".join(parts)
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


# ── architecture/screens.md ──────────────────────────────────────────────────

import re as _re_screens

def _detect_tech_stack(repo_path: str) -> dict[str, str]:
    """Infer technology stack from the repo's actual source files."""
    import os as _os_ts
    tech: dict[str, str] = {}

    if not repo_path or not _os_ts.path.isdir(repo_path):
        return tech

    # Collect requirements files and package manifests
    req_text = ""
    for root, dirs, files in _os_ts.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in {"__pycache__", ".venv", "venv", "node_modules", ".git"}]
        for fname in files:
            if fname in ("requirements.txt", "requirements-dev.txt", "pyproject.toml", "setup.py",
                         "package.json", "build.gradle", "pom.xml", "Gemfile", "go.mod"):
                try:
                    req_text += open(_os_ts.path.join(root, fname), encoding="utf-8", errors="replace").read()
                except OSError:
                    pass
        if len(req_text) > 50_000:
            break

    req_lower = req_text.lower()

    # Detect web framework
    if "fastapi" in req_lower:
        tech["framework"] = "FastAPI (Python)"
    elif "django" in req_lower:
        tech["framework"] = "Django (Python)"
    elif "flask" in req_lower:
        tech["framework"] = "Flask (Python)"
    elif "rails" in req_lower or "actionpack" in req_lower:
        tech["framework"] = "Ruby on Rails"
    elif "spring-boot" in req_lower or "spring-web" in req_lower:
        tech["framework"] = "Spring Boot (Java)"
    elif "express" in req_lower:
        tech["framework"] = "Express.js (Node)"
    elif "next" in req_lower and "react" in req_lower:
        tech["framework"] = "Next.js / React"
    elif "react" in req_lower:
        tech["framework"] = "React"
    elif "vue" in req_lower:
        tech["framework"] = "Vue.js"
    elif "angular" in req_lower:
        tech["framework"] = "Angular"

    # Detect templating
    if "jinja2" in req_lower:
        tech["templating"] = "Jinja2 (server-side HTML)"
    elif "mako" in req_lower:
        tech["templating"] = "Mako"
    elif "handlebars" in req_lower:
        tech["templating"] = "Handlebars"

    # Detect HTTP client
    if "httpx" in req_lower:
        tech["http_client"] = "httpx"
    elif "requests" in req_lower:
        tech["http_client"] = "requests"
    elif "axios" in req_lower:
        tech["http_client"] = "axios"

    return tech

# Patterns to detect what a route handler does
_HTTPX_CALL_RE    = _re_screens.compile(r'_http\.\w+\(\s*[f"]([^"\']+)["\']')
_RUN_QUERY_RE     = _re_screens.compile(r'run_query\(')
_DIRECT_DB_RE     = _re_screens.compile(r'sqlite3\.connect|_telemetry_con|_sq\.connect|con\.execute')
_TEMPLATE_RE      = _re_screens.compile(r'TemplateResponse\(\s*["\']([^"\']+)["\']')
_ROUTE_RE         = _re_screens.compile(
    r'@router\.(get|post|put|delete|patch)\(\s*["\']([^"\']+)["\']'
    r'(?:[^)]*response_class\s*=\s*HTMLResponse)?'
)
_HTML_HREF_RE     = _re_screens.compile(r"""href=['"](/[^'"?#]*)""")
_HTML_ACTION_RE   = _re_screens.compile(r"""action=['"]([^'"?#]*)['"]""")
_REDIRECT_RE      = _re_screens.compile(r'RedirectResponse\(\s*[f"\']([^"\']+)["\']')

# Extract query/path params from handler function signature
# Matches: param_name: type = default   or   param_name: type
_HANDLER_SIG_RE   = _re_screens.compile(
    r'async def \w+\([^)]*\):|def \w+\([^)]*\):'
)
_QUERY_PARAM_RE   = _re_screens.compile(
    r'(\w+)\s*:\s*([\w\[\], ]+?)'           # name: type
    r'(?:\s*=\s*(?:Query\([^)]*\)|([^,\n)]+)))?'  # optional default
)

# Extract keys from the TemplateResponse context dict:
# matches "key": value  or  "key": expr  inside the dict
_CTX_KEY_RE = _re_screens.compile(r'"(\w+)"\s*:')


def _parse_route_file(path: str) -> list[dict]:
    """
    Parse one routes/*.py file into a list of screen dicts.
    Each dict represents one URL endpoint with the following keys:
      method, url, is_page, template, api_calls, db_access, redirects, handler_src
    """
    try:
        src = open(path, encoding="utf-8", errors="replace").read()
    except OSError:
        return []

    screens = []
    # Split on @router. decorators to get per-handler blocks
    parts = _re_screens.split(r'(?=@router\.)', src)
    for part in parts:
        m = _ROUTE_RE.match(part)
        if not m:
            continue
        method = m.group(1).upper()
        url    = m.group(2)
        is_page = "response_class=HTMLResponse" in part or "HTMLResponse" in part

        tpl_m = _TEMPLATE_RE.search(part)
        template = tpl_m.group(1) if tpl_m else None

        api_calls = [c.strip() for c in _HTTPX_CALL_RE.findall(part)]
        has_neo4j = bool(_RUN_QUERY_RE.search(part))
        has_db    = bool(_DIRECT_DB_RE.search(part))
        redirects = [r.strip() for r in _REDIRECT_RE.findall(part)]

        # Query/path params: parse function signature line
        # Skip: request, self, body params, and FastAPI internals
        _SKIP_PARAMS = {"request", "self", "body", "response", "background_tasks"}
        query_params = []
        sig_m = _re_screens.search(r'(?:async def|def) \w+\(([^)]*)\)', part)
        if sig_m:
            sig_body = sig_m.group(1)
            for pm in _re_screens.finditer(
                r'(\w+)\s*:\s*([\w\[\]| ,]+?)(?:\s*=\s*([^,\n)]+))?(?=[,\n)]|$)',
                sig_body
            ):
                pname, ptype, pdefault = pm.group(1), pm.group(2).strip(), (pm.group(3) or "").strip()
                if pname in _SKIP_PARAMS:
                    continue
                if ptype in ("Request", "Response", "BackgroundTasks"):
                    continue
                entry = f"`{pname}: {ptype}`"
                if pdefault:
                    entry += f" = `{pdefault}`"
                query_params.append(entry)

        # Template context variables: keys from the TemplateResponse dict
        # Find the TemplateResponse call and extract keys from its dict argument
        ctx_vars = []
        tpl_call_m = _re_screens.search(
            r'TemplateResponse\(\s*["\'][^"\']+["\'],\s*\{([^}]*(?:\{[^}]*\}[^}]*)*)\}',
            part, _re_screens.DOTALL
        )
        if tpl_call_m:
            dict_body = tpl_call_m.group(1)
            seen_keys: set[str] = set()
            for km in _CTX_KEY_RE.finditer(dict_body):
                k = km.group(1)
                # skip spread keys like **ctx — those come from _template_ctx
                if k not in seen_keys:
                    seen_keys.add(k)
                    ctx_vars.append(k)
            # Also catch **_template_ctx / **ctx spreads — always adds standard keys
            if "_template_ctx" in dict_body or "**ctx" in dict_body:
                for std in ("current_path", "repos", "effective_repo"):
                    if std not in seen_keys:
                        ctx_vars.insert(0, f"{std} (via _template_ctx)")

        screens.append({
            "method":       method,
            "url":          url,
            "is_page":      is_page,
            "template":     template,
            "api_calls":    api_calls,
            "query_params": query_params,
            "ctx_vars":     ctx_vars,
            "neo4j":     has_neo4j,
            "direct_db": has_db,
            "redirects": redirects,
        })

    return screens


def _parse_template(path: str) -> dict:
    """
    Extract inbound links (href) and form actions from a Jinja2 template.
    Returns {links_to: [...], form_actions: [...]}
    """
    try:
        src = open(path, encoding="utf-8", errors="replace").read()
    except OSError:
        return {"links_to": [], "form_actions": []}

    hrefs   = list(dict.fromkeys(_HTML_HREF_RE.findall(src)))
    actions = list(dict.fromkeys(_HTML_ACTION_RE.findall(src)))
    # Filter out anchors that are just "#" or empty
    hrefs   = [h for h in hrefs   if h and h != "#"]
    actions = [a for a in actions if a and not a.startswith("#")]
    return {"links_to": hrefs, "form_actions": actions}


def _collect_screens(repo_path: str) -> list[dict]:
    """
    Walk all service directories under repo_path looking for route files
    and templates. Returns merged screen records.
    """
    import os as _os_sc

    # Normalise path (macOS case-insensitive / container case-sensitive)
    if repo_path and not _os_sc.path.isdir(repo_path):
        parent, last = _os_sc.path.split(repo_path)
        lower = _os_sc.path.join(parent, last.lower())
        if _os_sc.path.isdir(lower):
            repo_path = lower

    if not repo_path or not _os_sc.path.isdir(repo_path):
        return []

    all_screens: list[dict] = []

    # Pattern 1 — FastAPI routes/  subdirectory
    for root, dirs, files in _os_sc.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in {"__pycache__", ".venv", "venv",
                                                   "site-packages", ".git", ".codekg",
                                                   "node_modules"}]
        # Route files: anything under a routes/ directory
        in_routes = _os_sc.path.basename(root) == "routes"

        for fname in files:
            if not fname.endswith(".py"):
                continue
            fpath = _os_sc.path.join(root, fname)
            rel   = _os_sc.path.relpath(fpath, repo_path)
            if not in_routes:
                continue

            screens = _parse_route_file(fpath)
            for s in screens:
                s["route_file"] = rel
                s["service"] = rel.split(_os_sc.sep)[1] if len(rel.split(_os_sc.sep)) > 1 else "?"
            all_screens.extend(screens)

    # Pattern 2 — resolve template info for HTML page screens
    template_dirs: list[str] = []
    for root, dirs, files in _os_sc.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in {"__pycache__", ".venv", "venv",
                                                   "site-packages", ".git", ".codekg"}]
        if _os_sc.path.basename(root) == "templates":
            template_dirs.append(root)

    template_index: dict[str, str] = {}  # template name → full path
    for td in template_dirs:
        for fname in _os_sc.listdir(td):
            if fname.endswith(".html"):
                template_index[fname] = _os_sc.path.join(td, fname)

    for s in all_screens:
        tpl = s.get("template")
        if tpl and tpl in template_index:
            tpl_data = _parse_template(template_index[tpl])
            s["links_to"]     = tpl_data["links_to"]
            s["form_actions"] = tpl_data["form_actions"]
        else:
            s["links_to"]     = []
            s["form_actions"] = []

    return all_screens


def _screen_description(url: str, template: str | None) -> str:
    """Best-effort human description from URL + template name."""
    # Derive from template name when available
    if template:
        name = template.replace(".html", "").replace("_", " ").title()
        return f"{name} page"
    # Derive from URL path segments
    parts = [p for p in url.strip("/").split("/") if p and not p.startswith("{")]
    if parts:
        return " / ".join(p.replace("-", " ").replace("_", " ").title() for p in parts) + " page"
    if url == "/":
        return "Home / Dashboard"
    return url


def _collect_nav_links(repo_path: str) -> list[str]:
    """Extract href links from a base template (base.html or layout equivalent)."""
    import os as _os_nav
    if not repo_path or not _os_nav.path.isdir(repo_path):
        return []
    # Walk looking for a base template
    for root, dirs, files in _os_nav.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in {"__pycache__", ".venv", "venv", "node_modules", ".git"}]
        for fname in files:
            if fname in ("base.html", "layout.html", "_layout.html", "base.jinja2",
                         "application.html.erb", "base.njk"):
                try:
                    src = open(_os_nav.path.join(root, fname), encoding="utf-8", errors="replace").read()
                    links = _re_screens.findall(r"""href=['"](/[^'"?#]{1,60})""", src)
                    # Deduplicate preserving order, skip static/asset paths
                    seen: set[str] = set()
                    result = []
                    for lnk in links:
                        if lnk not in seen and not lnk.startswith("/static"):
                            seen.add(lnk)
                            result.append(lnk)
                    return result[:30]
                except OSError:
                    pass
    return []


def _detect_conventions(screens: list[dict]) -> list[str]:
    """Derive observable coding conventions from the parsed screen list."""
    conventions = []
    if not screens:
        return conventions

    methods = {s["method"] for s in screens}
    has_get_post = "GET" in methods and "POST" in methods
    has_template = any(s.get("template") for s in screens)
    has_api_calls = any(s.get("api_calls") for s in screens)
    has_neo4j = any(s.get("neo4j") for s in screens)
    has_sqlite = any(s.get("direct_db") for s in screens)
    has_redirects = any(s.get("redirects") for s in screens)
    path_params = [s for s in screens if "{" in s.get("url", "")]

    if has_template:
        conventions.append("**Server-side rendering**: routes return `TemplateResponse` with Jinja2 templates")
    if has_get_post:
        conventions.append("**Form pattern**: HTML `<form method=POST>` — POST handlers redirect or re-render")
    if has_api_calls:
        conventions.append("**Service calls**: some routes proxy to a downstream API via HTTP client")
    if has_neo4j:
        conventions.append("**Graph DB**: pages query Neo4j directly via `run_query()`")
    if has_sqlite:
        conventions.append("**SQLite**: some routes use direct SQLite connections for local data")
    if has_redirects:
        conventions.append("**Post-redirect-get**: mutating POST handlers redirect on success")
    if path_params:
        conventions.append(f"**Path parameters**: {len(path_params)} routes use path params (e.g. `{{id}}`, `{{id:path}}`)")

    return conventions


def generate_screens_index(repo_id: str, repo_path: str) -> str:
    """
    Generate a complete page/screen catalog for the repo.
    Covers: URL, HTTP method, template, description, navigation links,
    API calls downstream, DB access, and technology metadata.
    Useful for any developer (or agent) who thinks in terms of pages/screens
    rather than files and classes.
    """
    screens = _collect_screens(repo_path)

    # Separate HTML pages from pure API endpoints
    pages   = [s for s in screens if s.get("is_page") or s.get("template")]
    apis    = [s for s in screens if not (s.get("is_page") or s.get("template"))]

    tech = _detect_tech_stack(repo_path)

    lines = [
        f"# Screen & Page Catalog — {repo_id}",
        f"_Generated {_TS()}_",
        "",
        "Complete map of every user-facing page and API endpoint.",
        "Covers URL patterns, templates, navigation links, downstream calls, and data access.",
        "Read this before adding, renaming, or linking pages.",
        "",
    ]

    if tech:
        lines += [
            "## Technology stack",
            "",
            "| Concern | Detail |",
            "|---------|--------|",
        ]
        for k, v in tech.items():
            lines.append(f"| **{k.replace('_', ' ').title()}** | {v} |")
        lines.append("")

    # Derive nav links from base.html or equivalent — do not hardcode
    nav_links = _collect_nav_links(repo_path)
    if nav_links:
        lines += [
            "## Navigation graph",
            "",
            f"_Top-level nav links extracted from base template ({len(nav_links)} links)._",
            "",
            "| URL |",
            "|-----|",
        ]
        for link in nav_links:
            lines.append(f"| `{link}` |")
        lines.append("")

    lines += [
        "## Pages (HTML responses)",
        "",
        f"_{len(pages)} page endpoint(s) detected._",
        "",
    ]

    # Group by service
    by_service: dict[str, list[dict]] = {}
    for s in pages:
        svc = s.get("service", "unknown")
        by_service.setdefault(svc, []).append(s)

    for svc, svc_screens in sorted(by_service.items()):
        lines.append(f"### Service: `{svc}`")
        lines.append("")

        for s in sorted(svc_screens, key=lambda x: x["url"]):
            url      = s["url"]
            method   = s["method"]
            template = s.get("template") or "—"
            desc     = _screen_description(url, s.get("template"))
            rf       = s.get("route_file", "?")

            lines.append(f"#### `{method} {url}`")
            lines.append(f"**Template:** `{template}`  **Route file:** `{rf}`")
            lines.append(f"**Description:** {desc}")
            lines.append("")

            # Query / path parameters
            qp = s.get("query_params", [])
            if qp:
                lines.append("**Parameters:** " + ", ".join(qp))
                lines.append("")

            # Template context variables passed to this page
            ctx = s.get("ctx_vars", [])
            if ctx:
                lines.append("**Template context:** " + ", ".join(f"`{v}`" for v in ctx))
                lines.append("")

            # Inbound — which nav / pages link here
            linked_from = []
            for other in pages:
                if other is s:
                    continue
                other_links = other.get("links_to", []) + other.get("form_actions", [])
                for lnk in other_links:
                    # Normalise — strip path params from the stored URL for matching
                    base_url = url.split("{")[0].rstrip("/") or "/"
                    if lnk == base_url or lnk.startswith(base_url + "/") or lnk == url:
                        linked_from.append(other["url"])
                        break
            if linked_from:
                lines.append("**Linked from:** " + ", ".join(f"`{u}`" for u in sorted(set(linked_from))))
                lines.append("")

            # Outbound links in the template
            links_to = s.get("links_to", [])
            if links_to:
                lines.append("**Links to:** " + ", ".join(f"`{lk}`" for lk in sorted(set(links_to))[:15]))
                lines.append("")

            # Form actions (POST targets)
            form_actions = [a for a in s.get("form_actions", []) if a not in links_to]
            if form_actions:
                lines.append("**Form actions (POST):** " + ", ".join(f"`{a}`" for a in sorted(set(form_actions))[:10]))
                lines.append("")

            # Downstream API calls detected in handler source
            api_calls = s.get("api_calls", [])
            if api_calls:
                lines.append("**Calls downstream API:**")
                for c in sorted(set(api_calls)):
                    lines.append(f"  - `{c}`")
                lines.append("")

            # Data access
            data_parts = []
            if s.get("neo4j"):
                data_parts.append("Neo4j (via `run_query`)")
            if s.get("direct_db"):
                data_parts.append("SQLite (direct connection)")
            if data_parts:
                lines.append("**Data access:** " + ", ".join(data_parts))
                lines.append("")

            # Redirects to
            if s.get("redirects"):
                lines.append("**Redirects to:** " + ", ".join(f"`{r}`" for r in s["redirects"]))
                lines.append("")

    # API-only endpoints summary
    if apis:
        lines += [
            "## API endpoints (non-HTML)",
            "",
            f"_{len(apis)} JSON/plain-text endpoint(s)_",
            "",
            "| Method | URL | Route file | Notes |",
            "|--------|-----|------------|-------|",
        ]
        for s in sorted(apis, key=lambda x: x["url"]):
            rf    = s.get("route_file", "?")
            notes = []
            if s.get("neo4j"):     notes.append("Neo4j")
            if s.get("direct_db"): notes.append("SQLite")
            if s.get("api_calls"): notes.append(f"→ api: {', '.join(s['api_calls'][:2])}")
            lines.append(f"| `{s['method']}` | `{s['url']}` | `{rf}` | {'; '.join(notes) or '—'} |")
        lines.append("")

    conventions = _detect_conventions(screens)
    if conventions:
        lines += ["## Key patterns & conventions", ""]
        for c in conventions:
            lines.append(f"- {c}")
        lines.append("")

    return _cap("\n".join(lines), _CAP["screens"])


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
        "key":         "architecture/datastores",
        "directory":   "architecture",
        "filename":    "datastores.md",
        "description": "All data stores (Neo4j, SQLite DBs) — schemas and which modules use them",
        "trigger":     "scan_complete",
        "generator":   None,  # handled specially — needs repo_path
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
        "key":         "modules/combined",
        "directory":   "modules",
        "filename":    "combined.md",
        "description": "All modules inlined — used when total repo LOC < 2,500",
        "trigger":     "scan_complete",
        "generator":   generate_combined_index,
    },
    {
        "key":         "architecture/screens",
        "directory":   "architecture",
        "filename":    "screens.md",
        "description": "All pages/screens — URL, template, nav links, API calls, data access",
        "trigger":     "scan_complete",
        "generator":   None,  # handled specially — needs repo_path
    },
    {
        "key":         "architecture/recent_changes",
        "directory":   "architecture",
        "filename":    "recent_changes.md",
        "description": "Recent git commits and index file changes — read to understand what changed",
        "trigger":     "any_change",
        "generator":   None,  # handled specially — needs repo_path for git log
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
