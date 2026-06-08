"""
Call chain computation for CodeKG.

Derives the request/execution flow through a codebase without needing CALLS edges,
by tracing constructor-injected field types through class role layers.

The intuition: in layered architectures, a TRANSPORT class holds SERVICE fields,
a SERVICE holds REPOSITORY fields, etc. By following field-type references through
role layers we reconstruct the "how does a request flow?" answer that LLMs need.

Algorithm per entry-point class:
  1. Start from TRANSPORT or COMMAND classes (the outermost layer)
  2. For each class, look at its fields whose type resolves to a known class in the repo
  3. Filter those field-classes by role (skip UTILITY, TEST, GENERATED, VALUE_OBJECT)
  4. Order hops by role priority: TRANSPORT → COMMAND → SERVICE → REPOSITORY
  5. BFS outward, max 6 hops, stop when we reach leaves (REPOSITORY / no further hops)
  6. Store the chain on the entry-point class AND on every class that appears in it

Output stored on Class nodes:
  c.call_chains  — JSON list of chains starting from this class (as entry point)
  c.appears_in_chains — JSON list of entry-point FQNs whose chain this class appears in

Merged into object_model JSON as:
  "call_chain": [
    {
      "entry": "TransportPutJobAction",
      "chain": [
        {"name": "TransportPutJobAction", "role": "TRANSPORT", "fqn": "..."},
        {"name": "JobManager",            "role": "SERVICE",   "fqn": "..."},
        {"name": "JobConfigProvider",     "role": "REPOSITORY","fqn": "..."}
      ],
      "depth": 3,
      "via_field": ["jobManager", "jobConfigProvider"]
    }
  ]
"""
from __future__ import annotations

import json
import logging
from collections import defaultdict

from neo4j import Driver

try:
    from shared.codekg_logging.codekg_logger import get_logger
except ImportError:
    class _FB:
        """Fallback logger for call-chain extraction helpers. Watch out for its limited interface here, because it exists only to keep offline utilities from crashing on import."""

        def __init__(self, n): self._l = logging.getLogger(n)
        def info(self, m, **k): self._l.info(m)
        def warning(self, m, **k): self._l.warning(m)
        def error(self, m, **k): self._l.error(m)
    def get_logger(n, **k): return _FB(n)

log = get_logger(__name__, service="ingestion")

_BATCH = 200

# Roles that can appear in a chain (ordered by layer)
_CHAIN_ROLES = ("TRANSPORT", "COMMAND", "SERVICE", "REPOSITORY", "ABSTRACT_BASE", "CLASS")
_ENTRY_ROLES  = {"TRANSPORT", "COMMAND"}
_SKIP_ROLES   = {"TEST", "GENERATED", "UTILITY", "VALUE_OBJECT", "CONFIGURATION"}

# Role → numeric depth priority (lower = closer to edge)
_ROLE_DEPTH = {
    "TRANSPORT":   0,
    "COMMAND":     1,
    "SERVICE":     2,
    "ABSTRACT_BASE": 3,
    "CLASS":       3,
    "REPOSITORY":  4,
    "FACTORY":     4,
}

_MAX_CHAIN_DEPTH  = 6
_MAX_CHAINS_STORED = 3   # per class: top-N chains by depth
_MAX_CHAIN_WIDTH  = 5   # max siblings at each hop


# ---------------------------------------------------------------------------
# Data fetchers
# ---------------------------------------------------------------------------

def _run(driver: Driver, cypher: str, **params) -> list[dict]:
    with driver.session() as s:
        return [dict(r) for r in s.run(cypher, **params)]


def _fetch_class_index(driver: Driver, repo_id: str) -> dict[str, dict]:
    """
    Returns {fqn -> {name, role, module_id, fqn}} for all non-skip-role classes.
    Also builds a name → [fqn] index for field-type resolution.
    """
    rows = _run(driver, """
        MATCH (c:Class {repo_id: $repo_id})
        WHERE c.role IS NOT NULL
        RETURN c.fqn AS fqn, c.name AS name, c.role AS role,
               c.object_model AS om
    """, repo_id=repo_id)

    by_fqn:  dict[str, dict] = {}
    by_name: dict[str, list[str]] = defaultdict(list)  # name -> [fqn, ...]

    for r in rows:
        if r["role"] in _SKIP_ROLES:
            continue
        # Extract module_id from object_model
        module_id = None
        if r.get("om"):
            try:
                module_id = json.loads(r["om"]).get("module_id")
            except ValueError:
                pass
        entry = {
            "fqn":       r["fqn"],
            "name":      r["name"],
            "role":      r["role"],
            "module_id": module_id,
        }
        by_fqn[r["fqn"]] = entry
        by_name[r["name"]].append(r["fqn"])

    return by_fqn, dict(by_name)


def _fetch_field_map(driver: Driver, repo_id: str) -> dict[str, list[dict]]:
    """
    Returns {class_fqn -> [{field_name, type_name}, ...]} for all classes.
    """
    rows = _run(driver, """
        MATCH (c:Class {repo_id: $repo_id})-[:HAS_FIELD]->(f:Field)
        RETURN c.fqn AS fqn, f.name AS field_name, f.type_name AS type_name
    """, repo_id=repo_id)

    result: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        if r["type_name"]:
            result[r["fqn"]].append({
                "field_name": r["field_name"],
                "type_name":  _strip_generics(r["type_name"]),
            })
    return dict(result)


def _strip_generics(type_name: str) -> str:
    """'Supplier<ByteSizeValue>' → 'Supplier'"""
    return type_name.split("<")[0].strip()


# ---------------------------------------------------------------------------
# Chain BFS
# ---------------------------------------------------------------------------

def _resolve_field_types(
    class_fqn: str,
    field_map: dict[str, list[dict]],
    by_fqn: dict[str, dict],
    by_name: dict[str, list[str]],
    own_module: str | None,
) -> list[tuple[str, str, str]]:
    """
    For a given class, return the list of (field_name, type_class_fqn, type_class_role)
    for fields whose type resolves to a known non-skip-role class.
    Prefer same-module matches when a name is ambiguous.
    """
    results = []
    for field in field_map.get(class_fqn, []):
        type_name = field["type_name"]
        candidates = by_name.get(type_name, [])
        if not candidates:
            continue
        # Prefer same module
        if own_module and len(candidates) > 1:
            same_mod = [f for f in candidates
                        if by_fqn.get(f, {}).get("module_id") == own_module]
            chosen = same_mod[0] if same_mod else candidates[0]
        else:
            chosen = candidates[0]
        role = by_fqn.get(chosen, {}).get("role", "CLASS")
        if role not in _SKIP_ROLES:
            results.append((field["field_name"], chosen, role))
    return results


def _build_chain(
    entry_fqn: str,
    by_fqn: dict[str, dict],
    by_name: dict[str, list[str]],
    field_map: dict[str, list[dict]],
) -> list[dict] | None:
    """
    Walk from entry_fqn following the primary dependency spine:
    at each hop, pick the field whose type has the deepest role (SERVICE > CLASS > REPOSITORY).
    Siblings (other fields at the same depth) are listed as context on the step.

    Returns a list of step dicts forming the primary chain, or None if < 2 hops.
    """
    entry = by_fqn.get(entry_fqn)
    if not entry:
        return None

    own_module = entry.get("module_id")
    visited: set[str] = {entry_fqn}

    chain_nodes: list[dict] = [{
        "fqn":       entry_fqn,
        "name":      entry["name"],
        "role":      entry["role"],
        "via_field": None,
        "siblings":  [],
        "depth":     0,
    }]

    curr_fqn  = entry_fqn
    curr_depth_val = _ROLE_DEPTH.get(entry["role"], 0)

    for depth in range(1, _MAX_CHAIN_DEPTH + 1):
        hops = _resolve_field_types(curr_fqn, field_map, by_fqn, by_name, own_module)

        # Only follow fields to classes deeper in the role stack
        deeper = [
            (fn, fqn, role) for fn, fqn, role in hops
            if _ROLE_DEPTH.get(role, 3) >= curr_depth_val
            and fqn not in visited
        ]
        if not deeper:
            break

        # Sort: named roles first (SERVICE/REPOSITORY before CLASS/ABSTRACT_BASE),
        # then by role depth (deepest = most specialised), then shorter FQN.
        _NAMED = {"SERVICE", "REPOSITORY", "COMMAND", "TRANSPORT", "FACTORY"}
        deeper.sort(key=lambda x: (
            0 if x[2] in _NAMED else 1,   # named roles before generic CLASS
            -_ROLE_DEPTH.get(x[2], 3),    # deepest named role first
            len(x[1]),                     # shorter FQN = more specific
        ))

        # Primary hop = most specialised field
        field_name, next_fqn, next_role = deeper[0]
        visited.add(next_fqn)

        # Siblings = other fields at this hop (context, not followed)
        siblings = [
            {"name": by_fqn.get(fqn, {}).get("name", fqn.split(".")[-1]),
             "role": role, "via_field": fn}
            for fn, fqn, role in deeper[1:_MAX_CHAIN_WIDTH]
            if fqn not in visited
        ]
        # mark siblings visited so we don't loop
        for _, sfqn, _ in deeper[1:_MAX_CHAIN_WIDTH]:
            visited.add(sfqn)

        next_info = by_fqn.get(next_fqn, {})
        chain_nodes.append({
            "fqn":       next_fqn,
            "name":      next_info.get("name", next_fqn.split(".")[-1]),
            "role":      next_role,
            "via_field": field_name,
            "siblings":  siblings,
            "depth":     depth,
        })

        curr_fqn = next_fqn
        curr_depth_val = _ROLE_DEPTH.get(next_role, 3)

    if len(chain_nodes) < 2:
        return None

    return chain_nodes


def _chain_to_output(chain_nodes: list[dict], entry_name: str) -> dict:
    """Convert raw chain node list to the stored JSON shape."""
    steps = [
        {"name": n["name"], "role": n["role"], "fqn": n["fqn"]}
        for n in chain_nodes
    ]
    via_fields = [
        n["via_field"] for n in chain_nodes if n["via_field"]
    ]
    return {
        "entry":      entry_name,
        "chain":      steps,
        "depth":      max(n["depth"] for n in chain_nodes),
        "via_field":  via_fields,
    }


# ---------------------------------------------------------------------------
# Batch write
# ---------------------------------------------------------------------------

def _write_chains(
    driver: Driver,
    repo_id: str,
    chain_by_fqn: dict[str, list[dict]],       # entry_fqn -> [chain_output]
    appears_in: dict[str, list[str]],           # fqn -> [entry_fqns]
    om_by_fqn: dict[str, str],                  # fqn -> current object_model JSON
) -> None:
    rows = []
    for fqn, chains in chain_by_fqn.items():
        om_str = om_by_fqn.get(fqn, "{}")
        try:
            om = json.loads(om_str)
        except ValueError:
            om = {}
        om["call_chains"] = chains[:_MAX_CHAINS_STORED]
        rows.append({
            "fqn":         fqn,
            "call_chains": json.dumps(chains[:_MAX_CHAINS_STORED],
                                      separators=(",", ":")),
            "object_model": json.dumps(om, separators=(",", ":")),
        })

    # Also update appears_in_chains for non-entry classes
    for fqn, entry_fqns in appears_in.items():
        if fqn in chain_by_fqn:
            continue  # already handled above
        om_str = om_by_fqn.get(fqn, "{}")
        try:
            om = json.loads(om_str)
        except ValueError:
            om = {}
        om["appears_in_chains"] = entry_fqns[:10]
        rows.append({
            "fqn":         fqn,
            "call_chains": None,
            "object_model": json.dumps(om, separators=(",", ":")),
        })

    for i in range(0, len(rows), _BATCH):
        batch = rows[i: i + _BATCH]
        with driver.session() as s:
            s.run("""
                UNWIND $rows AS row
                MATCH (c:Class {fqn: row.fqn, repo_id: $repo_id})
                SET c.object_model = row.object_model
            """, rows=batch, repo_id=repo_id)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def build_call_chains(
    driver: Driver,
    repo_id: str,
    fqn_filter: set[str] | None = None,
) -> int:
    """
    Build and store call chains for all TRANSPORT/COMMAND entry-point classes.
    Returns count of chains built.
    """
    log.info("Building call chains", repo_id=repo_id)

    by_fqn, by_name = _fetch_class_index(driver, repo_id)
    field_map       = _fetch_field_map(driver, repo_id)

    # Fetch current object_model strings for merging
    rows = _run(driver, """
        MATCH (c:Class {repo_id: $repo_id})
        RETURN c.fqn AS fqn, c.object_model AS om
    """, repo_id=repo_id)
    om_by_fqn = {r["fqn"]: (r["om"] or "{}") for r in rows}

    # Find entry points
    entry_fqns = [
        fqn for fqn, info in by_fqn.items()
        if info["role"] in _ENTRY_ROLES
        and (fqn_filter is None or fqn in fqn_filter)
    ]
    log.info("Entry points found", repo_id=repo_id, count=len(entry_fqns))

    chain_by_fqn: dict[str, list[dict]] = {}   # entry_fqn -> [chain_output]
    appears_in:   dict[str, list[str]]  = defaultdict(list)  # member_fqn -> [entry_fqns]

    built = 0
    for entry_fqn in entry_fqns:
        chain_nodes = _build_chain(entry_fqn, by_fqn, by_name, field_map)
        if chain_nodes is None:
            continue

        entry_name = by_fqn[entry_fqn]["name"]
        chain_out  = _chain_to_output(chain_nodes, entry_name)
        chain_by_fqn[entry_fqn] = [chain_out]

        # Record appears_in for every member
        for node in chain_nodes[1:]:   # skip the entry itself
            appears_in[node["fqn"]].append(entry_fqn)

        built += 1

    log.info("Chains built", repo_id=repo_id, chains=built)
    _write_chains(driver, repo_id, chain_by_fqn, dict(appears_in), om_by_fqn)
    log.info("Call chains written", repo_id=repo_id)
    return built
