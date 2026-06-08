"""Console routes for module-level architecture views. Watch out for repo scoping here, because these handlers assemble several graph queries per request."""

from __future__ import annotations

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from deps import run_query, _template_ctx, templates, driver

router = APIRouter()


@router.get("/modules", response_class=HTMLResponse)
async def modules_list(request: Request):
    ctx           = _template_ctx(request)
    selected_repo = ctx["selected_repo"]
    repo_filter   = "WHERE mod.repo_id = $rid" if selected_repo else ""
    params        = {"rid": selected_repo} if selected_repo else {}

    modules = run_query(
        f"""
        MATCH (mod:Module) {repo_filter}
        OPTIONAL MATCH (c:Class) WHERE c.file_path STARTS WITH mod.path
        WITH mod, count(c) AS class_count
        RETURN mod.module_id AS module_id, mod.name AS name,
               mod.description AS description, mod.build_tool AS build_tool,
               mod.auto AS auto, mod.repo_id AS repo_id, class_count
        ORDER BY class_count DESC, mod.module_id
        """,
        **params,
    )

    edge_repo_filter = "WHERE m1.repo_id = $rid AND m2.repo_id = $rid" if selected_repo else ""
    edges = run_query(
        f"""
        MATCH (m1:Module), (m2:Module)
        {edge_repo_filter}
        {"AND" if selected_repo else "WHERE"} m1.module_id < m2.module_id
        MATCH (c1:Class)-[:IMPORTS]->(c2:Class)
        WHERE c1.file_path STARTS WITH m1.path AND c2.file_path STARTS WITH m2.path
        WITH m1.module_id AS source, m2.module_id AS target, count(*) AS weight
        WHERE weight > 1
        RETURN source, target, weight ORDER BY weight DESC LIMIT 200
        """,
        **params,
    )

    return templates.TemplateResponse("modules.html", {
        **ctx,
        "modules":     modules,
        "module_tree": _build_tree(modules),
        "edges":       edges,
    })


@router.get("/modules/{module_id:path}", response_class=HTMLResponse)
async def module_detail(request: Request, module_id: str):
    rows = run_query("MATCH (m:Module {module_id: $mid}) RETURN m", mid=module_id)
    if not rows:
        raise HTTPException(404)
    mod      = rows[0]["m"]
    mod_path = mod.get("path", "")

    stats = run_query(
        """
        MATCH (c:Class) WHERE c.file_path STARTS WITH $path
        RETURN count(c) AS total,
               sum(CASE WHEN c.fqn CONTAINS 'Test' OR c.name ENDS WITH 'Test' THEN 1 ELSE 0 END) AS tests,
               count(DISTINCT c.package_fqn) AS packages
        """,
        path=mod_path,
    )
    top_classes = run_query(
        """
        MATCH (c:Class) WHERE c.file_path STARTS WITH $path
        OPTIONAL MATCH (c)-[:HAS_METHOD]->(m:Method)
        WITH c, count(m) AS method_count ORDER BY method_count DESC LIMIT 20
        RETURN c.fqn AS fqn, c.name AS name, method_count,
               c.file_path AS file_path, c.annotations AS annotations
        """,
        path=mod_path,
    )
    deps_out = run_query(
        """
        MATCH (m2:Module) WHERE m2.module_id <> $mid
        MATCH (c1:Class)-[:IMPORTS]->(c2:Class)
        WHERE c1.file_path STARTS WITH $path AND c2.file_path STARTS WITH m2.path
        WITH m2.module_id AS dep_module, count(*) AS weight
        ORDER BY weight DESC LIMIT 15 RETURN dep_module, weight
        """,
        mid=module_id, path=mod_path,
    )
    deps_in = run_query(
        """
        MATCH (m1:Module) WHERE m1.module_id <> $mid
        MATCH (c1:Class)-[:IMPORTS]->(c2:Class)
        WHERE c1.file_path STARTS WITH m1.path AND c2.file_path STARTS WITH $path
        WITH m1.module_id AS dep_module, count(*) AS weight
        ORDER BY weight DESC LIMIT 15 RETURN dep_module, weight
        """,
        mid=module_id, path=mod_path,
    )
    sankey_flows = run_query(
        """
        MATCH (c1:Class)-[:IMPORTS]->(c2:Class) WHERE c1.file_path STARTS WITH $path
        MATCH (m2:Module) WHERE c2.file_path STARTS WITH m2.path AND m2.module_id <> $mid
        WITH m2.module_id AS target_mod, c2.package_fqn AS pkg, count(*) AS weight
        ORDER BY weight DESC LIMIT 30 RETURN target_mod, pkg, weight
        """,
        mid=module_id, path=mod_path,
    )
    patterns = run_query(
        """
        MATCH (ap:ArchPattern) WHERE ap.repo_id = $repo_id
        MATCH (c:Class)-[:EXHIBITS]->(ap) WHERE c.file_path STARTS WITH $path
        RETURN ap.name AS name, ap.anti_pattern AS anti, count(c) AS hits
        ORDER BY hits DESC LIMIT 10
        """,
        repo_id=mod.get("repo_id", ""), path=mod_path,
    )

    return templates.TemplateResponse("module_detail.html", {
        **_template_ctx(request),
        "mod":          mod,
        "module_id":    module_id,
        "stat":         stats[0] if stats else {},
        "top_classes":  top_classes,
        "deps_out":     deps_out,
        "deps_in":      deps_in,
        "sankey_flows": sankey_flows,
        "patterns":     patterns,
    })


@router.post("/modules")
async def create_module(
    module_id:   str = Form(...),
    description: str = Form(""),
    packages:    str = Form(""),
):
    pkg_list = [p.strip() for p in packages.split(",") if p.strip()]
    with driver.session() as s:
        s.run("MERGE (mod:Module {module_id: $mid}) SET mod.description = $desc",
              mid=module_id, desc=description)
        for pkg_fqn in pkg_list:
            s.run(
                """
                MATCH (mod:Module {module_id: $mid})
                MERGE (p:Package {fqn: $pkg})
                MERGE (mod)-[:OWNS]->(p)
                MERGE (p)-[:BELONGS_TO_MODULE]->(mod)
                """,
                mid=module_id, pkg=pkg_fqn,
            )
    return RedirectResponse("/modules", status_code=303)


def _build_tree(module_list: list[dict]) -> list[dict]:
    root: dict = {}
    for m in module_list:
        parts = m["module_id"].split("/")
        node  = root
        for part in parts[:-1]:
            node = node.setdefault(part, {"_data": None, "_children": {}})["_children"]
        entry = node.setdefault(parts[-1], {"_data": None, "_children": {}})
        entry["_data"] = m

    def to_list(d: dict, depth: int = 0) -> list[dict]:
        rows = []
        for key in sorted(d.keys()):
            node = d[key]
            rows.append({"key": key, "depth": depth, "data": node["_data"]})
            rows.extend(to_list(node["_children"], depth + 1))
        return rows

    return to_list(root)
