#!/usr/bin/env python3
"""
summarise_classes.py — Generate natural-language summaries for every Java class
in a CodeKG repository using a local Ollama model (default: qwen2.5-coder:7b).

Self-bootstrapping: on first run this script creates a local .venv, installs
its two dependencies (neo4j, requests), then re-executes itself inside that
venv — so plain `python3 summarise_classes.py ...` always works.

Usage:
    python summarise_classes.py --repo ElasticSearch
    python summarise_classes.py --repo ElasticSearch --model qwen2.5-coder:7b
    python summarise_classes.py --repo ElasticSearch --workers 4 --debug
    python summarise_classes.py --repo ElasticSearch --role SERVICE --limit 100
    python summarise_classes.py --repo ElasticSearch --resume          # skip already-done
    python summarise_classes.py --repo ElasticSearch --stats           # show progress only

Requirements (all standard or already installed in CodeKG env):
    pip install neo4j requests

Environment variables (or pass as CLI args):
    NEO4J_URI       bolt://localhost:7687
    NEO4J_USER      neo4j
    NEO4J_PASSWORD  codekg_dev
    OLLAMA_URL      http://localhost:11434

The script writes the summary back to the Class node as:
    c.summary           — the natural-language text (string)
    c.summary_model     — which model produced it
    c.summary_ts        — ISO timestamp

It is safe to kill and restart at any time — classes with a summary already are
skipped unless --force is given.  Progress is logged every N classes and to a
local log file (summarise_<repo>.log).
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Self-bootstrap: ensure neo4j + requests are available without the user
# having to manually create a venv or run pip.  Runs only when the packages
# are absent, then re-execs this script inside the venv transparently.
# ---------------------------------------------------------------------------
import subprocess, sys, os
from pathlib import Path as _Path

_DEPS = ["neo4j", "requests"]
_VENV = _Path(__file__).parent / ".venv"

def _missing() -> list[str]:
    import importlib.util
    return [d for d in _DEPS if importlib.util.find_spec(d.replace("-", "_")) is None]

if _missing():
    _py = _VENV / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    if not _py.exists():
        print(f"[bootstrap] Creating venv at {_VENV} …", flush=True)
        subprocess.check_call([sys.executable, "-m", "venv", str(_VENV)])
    print(f"[bootstrap] Installing {_DEPS} …", flush=True)
    subprocess.check_call([str(_py), "-m", "pip", "install", "--quiet"] + _DEPS)
    # Re-exec this script with the venv python
    os.execv(str(_py), [str(_py)] + sys.argv)

# ---------------------------------------------------------------------------

import argparse
import json
import logging
import queue
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from neo4j import GraphDatabase

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

def _setup_logging(repo_id: str, debug: bool) -> logging.Logger:
    log_file = Path(f"summarise_{repo_id.replace('/', '_')}.log")
    level = logging.DEBUG if debug else logging.INFO

    fmt = "%(asctime)s  %(levelname)-7s  %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"

    handlers: list[logging.Handler] = [
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(log_file, encoding="utf-8"),
    ]
    for h in handlers:
        h.setFormatter(logging.Formatter(fmt, datefmt=datefmt))

    log = logging.getLogger("summarise")
    log.setLevel(level)
    for h in handlers:
        log.addHandler(h)

    log.info("Log file: %s", log_file.resolve())
    return log


# ---------------------------------------------------------------------------
# Neo4j helpers
# ---------------------------------------------------------------------------

def _get_driver(uri: str, user: str, password: str):
    return GraphDatabase.driver(uri, auth=(user, password))


def _fetch_classes(driver, repo_id: str, role: str | None,
                   resume: bool, limit: int | None, log: logging.Logger,
                   fqn: str | None = None, include_modules: bool = False) -> list[dict]:
    """
    Fetch classes from Neo4j.  If resume=True, skip those that already have a summary.
    Works for both Java (has object_model) and Python/C++ (builds object_model from KG).
    """
    filters = ["c.repo_id = $repo_id"] if include_modules else ["c.repo_id = $repo_id", "NOT c.kind IN ['module']"]
    if fqn:
        filters.append("c.fqn = $fqn")
    if role:
        filters.append("c.role = $role")
    if resume and not fqn:
        filters.append("c.summary IS NULL")

    where = " AND ".join(filters)
    cypher = f"""
        MATCH (c:Class)
        WHERE {where}
        OPTIONAL MATCH (c)-[:HAS_METHOD]->(m:Method)
        OPTIONAL MATCH (c)-[:HAS_FIELD]->(f:Field)
        RETURN c.fqn AS fqn, c.name AS name, c.role AS role, c.kind AS kind,
               c.object_model AS object_model, c.javadoc AS javadoc,
               c.package_fqn AS package_fqn,
               c.extends_unresolved AS extends_list,
               c.implements_unresolved AS implements_list,
               c.coupling AS coupling, c.blast_size AS blast_size,
               collect(DISTINCT {{
                   name: m.name, return_type: m.return_type,
                   parameters: m.parameters, modifiers: m.modifiers,
                   docstring: m.docstring
               }}) AS methods,
               collect(DISTINCT {{
                   name: f.name, type: f.type, modifiers: f.modifiers
               }}) AS fields
        ORDER BY c.coupling DESC
        {"LIMIT " + str(limit) if limit and not fqn else ""}
    """
    params = {"repo_id": repo_id}
    if fqn:
        params["fqn"] = fqn
    if role:
        params["role"] = role

    log.debug("Fetching classes — query:\n%s\nparams=%s", cypher.strip(), params)

    with driver.session() as s:
        rows = [dict(r) for r in s.run(cypher, **params)]

    # For classes without object_model (Python/C++), build a synthetic one from KG data
    for row in rows:
        if not row.get("object_model"):
            row["object_model"] = _build_object_model_from_kg(row)

    log.info("Fetched %d classes to process", len(rows))
    return rows


def _build_object_model_from_kg(row: dict) -> str:
    """Build a Java-style object_model JSON string from KG node properties."""
    import json as _json
    methods = [m for m in (row.get("methods") or []) if m.get("name")]
    fields  = [f for f in (row.get("fields") or [])  if f.get("name")]
    extends = row.get("extends_list") or []
    ifaces  = row.get("implements_list") or []
    if isinstance(extends, str):
        extends = [extends]
    if isinstance(ifaces, str):
        ifaces = [ifaces]
    om = {
        "name":        row.get("name", ""),
        "kind":        row.get("kind", "class"),
        "role":        row.get("role") or "CLASS",
        "package":     row.get("package_fqn", ""),
        "superclass":  {"name": extends[0]} if extends else {},
        "interfaces":  [{"name": i} for i in ifaces],
        "annotations": [],
        "methods":     methods,
        "fields":      fields,
        "coupling":    row.get("coupling") or 0,
        "blast_size":  row.get("blast_size") or 0,
        "dependencies":   [],
        "dependents":     [],
        "patterns":       [],
        "warnings":       [],
        "call_chains":    [],
    }
    return _json.dumps(om)


def _write_summary(driver, fqn: str, summary: str, model: str, log: logging.Logger) -> None:
    ts = datetime.now(timezone.utc).isoformat()
    with driver.session() as s:
        s.run(
            """
            MATCH (c:Class {fqn: $fqn})
            SET c.summary       = $summary,
                c.summary_model = $model,
                c.summary_ts    = $ts
            """,
            fqn=fqn, summary=summary, model=model, ts=ts,
        )
    log.debug("Wrote summary for %s (%d chars)", fqn, len(summary))


def _fetch_stats(driver, repo_id: str) -> dict:
    with driver.session() as s:
        row = s.run("""
            MATCH (c:Class {repo_id: $repo_id})
            WHERE NOT c.kind IN ['module']
            WITH count(c) AS total,
                 sum(CASE WHEN c.summary IS NOT NULL THEN 1 ELSE 0 END) AS done,
                 sum(CASE WHEN c.object_model IS NOT NULL THEN 1 ELSE 0 END) AS with_om
            RETURN total, done, with_om
        """, repo_id=repo_id).single()
        return dict(row) if row else {}


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

_SKIP_ROLES = {"TEST", "GENERATED"}

def _build_prompt(om: dict, javadoc: str | None = None) -> str:
    """
    Construct the prompt from the class object model.
    javadoc: optional Javadoc extracted from the source file (authoritative).
    """
    name       = om.get("name", "Unknown")
    role       = om.get("role", "CLASS")
    kind       = om.get("kind", "class")
    pkg        = om.get("package", "")
    module     = om.get("module_id", "")
    anns       = [a for a in (om.get("annotations") or [])
                  if not a.startswith("@Override")]
    def _name(x) -> str:
        """Accept either a dict with a 'name' key or a plain string."""
        if isinstance(x, dict):
            return x.get("name", "")
        return str(x) if x else ""

    super_obj  = om.get("superclass") or {}
    super_     = super_obj.get("name") if isinstance(super_obj, dict) else str(super_obj)
    ifaces     = [_name(i) for i in (om.get("interfaces") or [])]
    methods    = om.get("methods") or []
    fields     = om.get("fields") or []
    deps       = [_name(d) for d in (om.get("dependencies") or [])]
    dependents = [_name(d) for d in (om.get("dependents") or [])]
    coupling   = om.get("coupling", 0)
    blast      = om.get("blast_size", 0)
    patterns   = [_name(p) for p in (om.get("patterns") or [])]
    warnings   = om.get("warnings") or []
    call_chains = om.get("call_chains") or []

    # ── Role explanation (so model doesn't confuse with @annotation) ──
    role_desc = {
        "TRANSPORT":    "entry-point request handler (outermost layer, receives external requests)",
        "COMMAND":      "command/action handler (orchestrates a single operation)",
        "SERVICE":      "domain service (core business logic)",
        "REPOSITORY":   "data-access layer (reads/writes persistent storage)",
        "FACTORY":      "object factory/builder",
        "CONFIGURATION":"configuration/settings holder",
        "ABSTRACT_BASE":"abstract base class (extended by concrete implementations)",
        "UTILITY":      "stateless utility class",
        "VALUE_OBJECT": "value object, DTO, or data container",
        "CLASS":        "general-purpose class",
    }.get(role, role)

    # ── Public API: show full signatures so the model can read concrete behaviour ──
    pub  = [m for m in methods if "public" in (m.get("modifiers") or [])]
    priv = [m for m in methods if "public" not in (m.get("modifiers") or [])]

    # Separate constructor from real methods; keep trivial getters/setters but de-prioritise
    def _is_trivial(m):
        n = m.get("name", "")
        return n in ("toString", "hashCode", "equals", "clone") or n == name  # constructor
    def _is_accessor(m):
        n = m.get("name", "")
        return n.startswith(("get", "set", "is", "has")) and not m.get("parameters")

    substantive = [m for m in pub if not _is_trivial(m) and not _is_accessor(m)]
    accessors   = [m for m in pub if _is_accessor(m) and not _is_trivial(m)]
    # Show substantive methods first, then accessors if space allows, skip trivial
    shown = (substantive + accessors)[:18]

    method_lines = []
    for m in shown:
        ret    = m.get("return_type") or "void"
        params = ", ".join(m.get("parameters") or [])
        anns_m = [a for a in (m.get("annotations") or []) if a != "@Override"]
        ann_str = f"  [{', '.join(anns_m)}]" if anns_m else ""
        method_lines.append(f"  {ret} {m['name']}({params}){ann_str}")
    if len(pub) > len(shown):
        method_lines.append(f"  … {len(pub) - len(shown)} more public methods")
    if priv:
        method_lines.append(f"  ({len(priv)} package/private methods)")

    # ── Fields: full type reveals injected dependencies and data structures ──
    sig_fields = [
        f for f in fields
        if f.get("name", "").upper() != f.get("name", "")   # skip ALL_CAPS constants
        and f.get("type", "") not in ("Logger", "Log", "long", "int", "boolean", "String", "AtomicLong")
    ][:10]
    field_lines = [
        f"  {f.get('type','?')} {f.get('name','?')}"
        + (" [final]" if "final" in (f.get("modifiers") or []) else "")
        for f in sig_fields
    ]

    # ── Call chains: show as prose not code ──
    chain_lines = []
    for chain in call_chains[:2]:
        steps = " → ".join(
            f"{s['name']} ({s['role']})" for s in chain.get("chain", [])
        )
        chain_lines.append(f"  {steps}")

    # ── Risk signals ──
    risk_parts = []
    if blast > 50:
        risk_parts.append(f"HIGH blast radius: {blast} classes transitively depend on this — signature changes are very risky")
    elif blast > 10:
        risk_parts.append(f"blast radius {blast} classes")
    if coupling > 0.7:
        risk_parts.append(f"high coupling score {coupling:.2f} (many callers + dependencies)")
    elif coupling > 0.4:
        risk_parts.append(f"moderate coupling {coupling:.2f}")
    if patterns:
        risk_parts.append(f"patterns: {', '.join(patterns)}")
    # strip coupling noise from warnings, keep structural ones
    structural_warnings = [w for w in warnings if "coupling" not in w.lower()]
    if structural_warnings:
        risk_parts.append("; ".join(structural_warnings))

    # ── Assemble context block ──
    lines = [
        f"Class name:  {name}",
        f"Kind:        {kind}",
        f"Package:     {pkg}",
    ]
    if module:
        lines.append(f"Module:      {module}")
    if anns:
        lines.append(f"Java annotations: {', '.join(anns)}")
    if super_:
        lines.append(f"Extends:     {super_}")
    if ifaces:
        lines.append(f"Implements:  {', '.join(ifaces)}")
    lines.append(f"\nArchitectural role: {role} — {role_desc}")

    lines.append(f"\nPublic API ({len(pub)} public methods of {len(methods)} total):")
    lines.extend(method_lines)

    if field_lines:
        lines.append("\nInjected / significant fields:")
        lines.extend(field_lines)

    if deps:
        shown_deps = deps[:12]
        lines.append(f"\nDirect dependencies (same repo): {', '.join(shown_deps)}"
                     + (f" (+{len(deps)-12} more)" if len(deps) > 12 else ""))
    if dependents:
        lines.append(f"Classes that depend on this: {', '.join(dependents[:10])}"
                     + (f" (+{len(dependents)-10} more)" if len(dependents) > 10 else ""))

    if chain_lines:
        lines.append("\nRequest/execution flow (field-injection derived):")
        lines.extend(chain_lines)

    if risk_parts:
        lines.append(f"\nRisk signals: {'; '.join(risk_parts)}")

    context = "\n".join(lines)

    # Docstring/Javadoc appended at end of context where model reads it last (better recall)
    if javadoc and javadoc.strip():
        doc_label = "Source docstring" if kind in ("class", "module") and not any(
            a.startswith("@") for a in (anns or [])
        ) else "Source Javadoc"
        context += f"\n\n{doc_label}: {javadoc.strip()}"

    # ── Pre-extract concrete evidence from the metadata to prime the model ──
    evidence = _extract_evidence(methods, sig_fields, name, ifaces)

    javadoc_line = f"\nSource docstring: {javadoc.strip()}" if javadoc and javadoc.strip() else ""
    implements_line = f"\nImplements: {', '.join(ifaces)}" if ifaces else ""

    prompt = f"""Here is the API of a class. Write 3-4 sentences explaining what it does — derive every sentence from a specific method signature or field type shown below. Name the actual types and method names. Do not use: manages, coordinates, responsible, functionality, plays, lifecycle, provides, keeps track.

{evidence}{implements_line}{javadoc_line}

Begin your answer with "{name}" and write only the paragraph:"""

    return prompt


# ---------------------------------------------------------------------------
# Evidence extractor — Python-side, deterministic, feeds the prompt
# ---------------------------------------------------------------------------

def _extract_evidence(methods: list, fields: list, class_name: str, ifaces: list) -> str:
    """
    Build a short evidence block from the actual method signatures and field types.
    This is done in Python so the LLM only has to synthesise, not extract.
    """
    lines = []

    # Pick the most revealing methods: non-trivial names, rich params/returns
    def _sig(m):
        ret    = m.get("return_type") or "void"
        params = ", ".join(m.get("parameters") or [])
        return f"{ret} {m['name']}({params})"

    skip_names = {class_name, "toString", "hashCode", "equals", "clone"}
    skip_prefixes = ("get", "set", "is", "has")

    substantive = [
        m for m in methods
        if m.get("name") not in skip_names
        and not m.get("name", "").startswith(skip_prefixes)
        and "public" in (m.get("modifiers") or [])
    ]
    # sort by signature richness: longer param list + non-void return = more informative
    substantive.sort(key=lambda m: (
        len(m.get("parameters") or []) +
        (2 if (m.get("return_type") or "void") not in ("void", "boolean", "int", "long", "String") else 0)
    ), reverse=True)

    if substantive:
        lines.append("Key method signatures:")
        for m in substantive[:6]:
            lines.append(f"  {_sig(m)}")

    # Fields: skip logger/primitives, show generic type parameters (they're informative)
    skip_types = {"Logger", "Log", "boolean", "int", "long", "String", "AtomicLong", "AtomicInteger"}
    rich_fields = [
        f for f in fields
        if f.get("name", "").upper() != f.get("name", "")
        and f.get("type", "") not in skip_types
    ]
    if rich_fields:
        lines.append("Internal data structures:")
        for f in rich_fields[:6]:
            mod = "final " if "final" in (f.get("modifiers") or []) else ""
            lines.append(f"  {mod}{f.get('type','?')} {f.get('name','?')}")

    if ifaces:
        lines.append(f"Implements: {', '.join(ifaces)}")

    return "\n".join(lines) if lines else "(no evidence extracted)"


# ---------------------------------------------------------------------------
# Response post-processor
# ---------------------------------------------------------------------------

def _extract_paragraph(text: str) -> str:
    """
    Extract the final documentation paragraph from a chain-of-thought response.
    Looks for text after 'Step 2' or a paragraph that doesn't start with 'Fact'.
    Falls back to the full text if no structure is found.
    """
    import re
    # Try to find Step 2 section
    for marker in ("Step 2", "step 2", "STEP 2", "Paragraph:", "Documentation:"):
        idx = text.find(marker)
        if idx != -1:
            after = text[idx + len(marker):].lstrip(" —:\n")
            # Take until a double newline or end
            para = after.split("\n\n")[0].strip()
            if len(para) > 40:
                return para
    # Fallback: find the first paragraph that doesn't look like a "Fact N:" line
    for para in re.split(r"\n{2,}", text):
        para = para.strip()
        if para and not re.match(r"^(Fact\s*\d|Step\s*\d|F\d:)", para, re.I):
            if len(para) > 40:
                return para
    return text.strip()


# ---------------------------------------------------------------------------
# Ollama client
# ---------------------------------------------------------------------------

def _call_ollama(prompt: str, model: str, ollama_url: str,
                 timeout: int, log: logging.Logger) -> str | None:
    url = f"{ollama_url.rstrip('/')}/api/generate"
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.1,
            "num_predict": 280,
        },
    }
    log.debug("POST %s  model=%s  prompt_len=%d", url, model, len(prompt))
    try:
        resp = requests.post(url, json=payload, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        text = data.get("response", "").strip()
        log.debug("Ollama response: %d chars, done_reason=%s",
                  len(text), data.get("done_reason"))
        log.debug("Ollama raw output:\n%s", text)
        text = _extract_paragraph(text)
        log.debug("Extracted paragraph:\n%s", text)
        return text if text else None
    except requests.exceptions.Timeout:
        log.warning("Ollama request timed out after %ds", timeout)
        return None
    except requests.exceptions.ConnectionError as e:
        log.error("Cannot reach Ollama at %s: %s", ollama_url, e)
        return None
    except Exception as e:
        log.error("Ollama error: %s", e)
        return None


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def _run(args: argparse.Namespace, log: logging.Logger) -> None:
    # ── Connect ──
    neo4j_uri  = args.neo4j_uri  or os.environ.get("NEO4J_URI",      "bolt://localhost:7687")
    neo4j_user = args.neo4j_user or os.environ.get("NEO4J_USER",     "neo4j")
    neo4j_pass = args.neo4j_pass or os.environ.get("NEO4J_PASSWORD",  "codekg_dev")
    ollama_url = args.ollama_url  or os.environ.get("OLLAMA_URL",     "http://localhost:11434")

    log.info("Neo4j:  %s  (user=%s)", neo4j_uri, neo4j_user)
    log.info("Ollama: %s  model=%s", ollama_url, args.model)
    log.info("Repo:   %s", args.repo)

    driver = _get_driver(neo4j_uri, neo4j_user, neo4j_pass)
    try:
        driver.verify_connectivity()
        log.info("Neo4j connection OK")
    except Exception as e:
        log.error("Cannot connect to Neo4j: %s", e)
        sys.exit(1)

    # ── Stats-only mode ──
    if args.stats:
        stats = _fetch_stats(driver, args.repo)
        total    = stats.get("total", 0)
        done     = stats.get("done", 0)
        with_om  = stats.get("with_om", 0)
        pct      = round(done / with_om * 100, 1) if with_om else 0
        remaining = with_om - done
        log.info("=== Progress for repo '%s' ===", args.repo)
        log.info("  Total classes:        %d", total)
        log.info("  With object model:    %d", with_om)
        log.info("  Summaries written:    %d  (%.1f%%)", done, pct)
        log.info("  Remaining:            %d", remaining)
        if remaining > 0 and done > 0:
            # Estimate time based on args.rate_estimate if provided
            est_secs = remaining * args.rate_estimate
            log.info("  Est. time remaining:  ~%s (at %.1fs/class)",
                     _fmt_duration(est_secs), args.rate_estimate)
        driver.close()
        return

    # ── Fetch work queue ──
    classes = _fetch_classes(
        driver, args.repo, args.role,
        resume=not args.force,
        limit=args.limit,
        log=log,
        fqn=args.fqn,
        include_modules=args.include_modules,
    )

    if not classes:
        log.info("Nothing to do — all classes already have summaries. Use --force to regenerate.")
        driver.close()
        return

    # Skip roles that produce useless summaries
    if not args.include_skip_roles:
        before = len(classes)
        classes = [c for c in classes if c.get("role") not in _SKIP_ROLES]
        skipped = before - len(classes)
        if skipped:
            log.info("Skipped %d TEST/GENERATED classes (use --include-skip-roles to include)", skipped)

    total = len(classes)
    log.info("Starting summarisation: %d classes to process", total)
    if args.dry_run:
        log.info("DRY RUN — prompts will be logged but nothing written to Neo4j")

    # ── Three-stage pipeline ──
    # Stage 1 (prep thread):   parse JSON + build prompt  → prompt_q
    # Stage 2 (main thread):   call Ollama (GPU bottleneck)
    # Stage 3 (writer thread): batch-write summaries to Neo4j  ← write_q
    #
    # This keeps the GPU busy while Neo4j I/O happens concurrently.

    _SENTINEL = object()  # signals end-of-stream to downstream stages

    prompt_q: queue.Queue = queue.Queue(maxsize=8)   # pre-built prompts
    write_q:  queue.Queue = queue.Queue(maxsize=32)  # (fqn, summary) pairs to persist

    counts = {"done": 0, "error": 0, "skip": 0}
    start_time  = time.perf_counter()
    last_report = start_time
    counters_lock = threading.Lock()

    # ── Stage 1: prep thread — parse object_model + build prompt ──
    def _prep_worker():
        for cls in classes:
            fqn  = cls["fqn"]
            name = cls["name"]
            role = cls.get("role", "CLASS")
            om_str = cls.get("object_model") or "{}"
            try:
                om = json.loads(om_str)
            except json.JSONDecodeError as e:
                log.warning("Bad object_model JSON for %s: %s — skipping", fqn, e)
                with counters_lock:
                    counts["skip"] += 1
                continue
            javadoc = cls.get("javadoc") or om.get("javadoc")
            prompt = _build_prompt(om, javadoc=javadoc)
            prompt_q.put((fqn, name, role, prompt))
        prompt_q.put(_SENTINEL)

    # ── Stage 3: writer thread — batch Neo4j writes ──
    _WRITE_BATCH = 10

    def _writer_worker():
        batch: list[tuple[str, str]] = []
        while True:
            item = write_q.get()
            if item is _SENTINEL:
                # flush remaining
                if batch and not args.dry_run:
                    _flush_batch(batch)
                break
            fqn, summary, model_name = item
            if args.dry_run:
                write_q.task_done()
                continue
            batch.append((fqn, summary, model_name))
            if len(batch) >= _WRITE_BATCH:
                _flush_batch(batch)
                batch.clear()
            write_q.task_done()

    def _flush_batch(batch):
        for fqn, summary, model_name in batch:
            try:
                _write_summary(driver, fqn, summary, model_name, log)
            except Exception as e:
                log.error("Failed to write summary for %s: %s", fqn, e)

    # Start background threads
    prep_thread   = threading.Thread(target=_prep_worker,   daemon=True, name="prep")
    writer_thread = threading.Thread(target=_writer_worker, daemon=True, name="writer")
    prep_thread.start()
    writer_thread.start()

    # ── Stage 2: main thread — Ollama inference ──
    idx = 0
    while True:
        item = prompt_q.get()
        if item is _SENTINEL:
            break
        fqn, name, role, prompt = item
        idx += 1

        log.debug("[%d/%d] Processing %s (%s)", idx, total, fqn, role)
        log.debug("Prompt for %s:\n%s", name, prompt if args.debug else prompt[:200] + "…")

        if args.dry_run:
            log.info("[DRY RUN] Would summarise %s (%s)", name, role)
            with counters_lock:
                counts["done"] += 1
            prompt_q.task_done()
            continue

        # Call Ollama with retry
        summary = None
        for attempt in range(1, args.retries + 1):
            summary = _call_ollama(prompt, args.model, ollama_url, args.timeout, log)
            if summary:
                break
            if attempt < args.retries:
                wait = attempt * 5
                log.warning("Retry %d/%d for %s in %ds…", attempt, args.retries, name, wait)
                time.sleep(wait)

        if not summary:
            log.error("Failed to get summary for %s after %d attempts", fqn, args.retries)
            with counters_lock:
                counts["error"] += 1
            time.sleep(args.error_backoff)
            prompt_q.task_done()
            continue

        write_q.put((fqn, summary, args.model))
        with counters_lock:
            counts["done"] += 1
        prompt_q.task_done()

        # Progress report
        now = time.perf_counter()
        if idx % args.report_every == 0 or (now - last_report) > 300:
            elapsed   = now - start_time
            rate      = counts["done"] / elapsed if elapsed > 0 else 0
            remaining = total - idx
            eta_secs  = remaining / rate if rate > 0 else 0
            pct       = idx / total * 100
            log.info(
                "Progress: %d/%d (%.1f%%) | done=%d errors=%d skipped=%d "
                "| rate=%.2f cls/s | ETA %s",
                idx, total, pct, counts["done"], counts["error"], counts["skip"],
                rate, _fmt_duration(eta_secs),
            )
            last_report = now

        if args.delay > 0:
            time.sleep(args.delay)

    # Signal writer to flush and wait for it
    write_q.put(_SENTINEL)
    writer_thread.join()
    prep_thread.join(timeout=5)

    # ── Final report ──
    elapsed = time.perf_counter() - start_time
    rate    = counts["done"] / elapsed if elapsed > 0 else 0
    log.info("=== Complete ===")
    log.info("  Processed:  %d / %d", counts["done"] + counts["error"] + counts["skip"], total)
    log.info("  Written:    %d summaries", counts["done"])
    log.info("  Errors:     %d", counts["error"])
    log.info("  Skipped:    %d", counts["skip"])
    log.info("  Elapsed:    %s", _fmt_duration(elapsed))
    log.info("  Avg rate:   %.2f classes/s  (%.1fs/class)",
             rate, 1/rate if rate > 0 else 0)

    driver.close()


def _fmt_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{int(seconds)}s"
    if seconds < 3600:
        m, s = divmod(int(seconds), 60)
        return f"{m}m {s}s"
    h, rem = divmod(int(seconds), 3600)
    m = rem // 60
    return f"{h}h {m}m"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Generate natural-language class summaries using a local Ollama model.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Start from the top (highest-coupling classes first), skip already done:
  python summarise_classes.py --repo ElasticSearch

  # Only SERVICE and REPOSITORY classes:
  python summarise_classes.py --repo ElasticSearch --role SERVICE
  python summarise_classes.py --repo ElasticSearch --role REPOSITORY

  # Test with 10 classes, see the full prompts:
  python summarise_classes.py --repo ElasticSearch --limit 10 --debug

  # Dry run — see what would happen without writing anything:
  python summarise_classes.py --repo ElasticSearch --dry-run --limit 5

  # Check progress:
  python summarise_classes.py --repo ElasticSearch --stats

  # Force regenerate everything:
  python summarise_classes.py --repo ElasticSearch --force

  # Use a different model:
  python summarise_classes.py --repo ElasticSearch --model qwen2.5-coder-64k:latest
        """,
    )

    p.add_argument("--repo",      required=True,  help="CodeKG repo_id, e.g. 'ElasticSearch'")
    p.add_argument("--model",     default="qwen2.5-coder:7b", help="Ollama model name")
    p.add_argument("--role",      default=None,   help="Filter to a specific role, e.g. SERVICE")
    p.add_argument("--fqn",       default=None,   help="Target a single class by FQN (for testing/regeneration)")
    p.add_argument("--limit",     type=int, default=None, help="Max classes to process (for testing)")
    p.add_argument("--force",     action="store_true", help="Regenerate even if summary exists")
    p.add_argument("--resume",    action="store_true", help="(Default) Skip already summarised classes")
    p.add_argument("--stats",     action="store_true", help="Show progress stats and exit")
    p.add_argument("--dry-run",   dest="dry_run", action="store_true",
                   help="Build prompts and log them but don't call Ollama or write to Neo4j")
    p.add_argument("--debug",     action="store_true", help="Verbose logging including full prompts")
    p.add_argument("--include-skip-roles", dest="include_skip_roles", action="store_true",
                   help="Include TEST and GENERATED classes (skipped by default)")
    p.add_argument("--include-modules", dest="include_modules", action="store_true",
                   help="Also summarise module-level nodes (kind=module, e.g. Python file nodes)")

    # Tuning
    p.add_argument("--workers",      type=int,   default=1,
                   help="Parallel workers (default 1 — Qwen7b saturates one GPU thread)")
    p.add_argument("--timeout",      type=int,   default=120,
                   help="Ollama request timeout in seconds (default 120)")
    p.add_argument("--retries",      type=int,   default=3,
                   help="Retry attempts per class on Ollama failure (default 3)")
    p.add_argument("--delay",        type=float, default=0.0,
                   help="Optional sleep between requests in seconds (default 0)")
    p.add_argument("--error-backoff",dest="error_backoff", type=float, default=10.0,
                   help="Sleep after a failed class before moving on (default 10s)")
    p.add_argument("--report-every", dest="report_every", type=int, default=50,
                   help="Log progress every N classes (default 50)")
    p.add_argument("--rate-estimate",dest="rate_estimate", type=float, default=8.0,
                   help="Seconds per class for ETA in --stats mode (default 8)")

    # Connection
    p.add_argument("--neo4j-uri",  dest="neo4j_uri",  default=None)
    p.add_argument("--neo4j-user", dest="neo4j_user", default=None)
    p.add_argument("--neo4j-pass", dest="neo4j_pass", default=None)
    p.add_argument("--ollama-url", dest="ollama_url", default=None)

    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    log  = _setup_logging(args.repo, args.debug)
    log.info("summarise_classes.py  repo=%s  model=%s  resume=%s  force=%s",
             args.repo, args.model, not args.force, args.force)

    if args.workers > 1:
        log.warning(
            "--workers > 1 is not yet implemented in sequential mode. "
            "Running with 1 worker. (Qwen2.5-7b typically saturates the GPU anyway.)"
        )

    try:
        _run(args, log)
    except KeyboardInterrupt:
        log.info("Interrupted by user — progress is saved, safe to resume with --resume")
        sys.exit(0)
    except Exception as e:
        log.exception("Unexpected error: %s", e)
        sys.exit(1)
