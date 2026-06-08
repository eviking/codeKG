# Architectural Policies

> Policies are machine-readable architectural constraints that are evaluated against the knowledge graph after every ingestion scan. They enforce the rules that would otherwise exist only as team conventions.

---

## What a policy is

A policy is a Cypher query that returns the classes or packages that violate a rule. If the query returns rows, those rows are violators. If it returns nothing, the constraint is satisfied.

```json
{
  "policy_id":        "auto-403ee21d",
  "title":            "Untested Package",
  "natural_language": "Every production package with 3 or more classes should have at least one test class",
  "cypher_constraint": "MATCH (p:Package {repo_id: 'codeKG'})-[:CONTAINS]->(c:Class) WHERE NOT c.fqn CONTAINS 'test' WITH p, count(c) AS class_count WHERE class_count >= 3 AND NOT EXISTS { MATCH (p)-[:CONTAINS]->(t:Class) WHERE t.role = 'TEST' } RETURN p.fqn AS violator",
  "severity":         "warning",
  "status":           "active",
  "source":           "auto-scan",
  "violator_count":   8
}
```

---

## Policy lifecycle

```
auto-scan generates draft policies
       │  status = "auto-draft"
       ▼
engineer reviews in console at /policies
       │
       ├── Approve → status = "active"
       │
       └── Reject / disable → status = "disabled"

on every ingestion scan:
  active policies → evaluate Cypher → write :VIOLATES edges → update violator_count
```

Auto-generated policies have `status="auto-draft"` and are not enforced until manually activated.

---

## Policy severity levels

| Severity | Meaning | When to use |
|----------|---------|-------------|
| `info` | Informational — no action required | Style suggestions, best-practice observations |
| `warning` | Should be addressed — not blocking | Technical debt, missing tests, high coupling |
| `error` | Must be fixed — architectural violation | Cross-layer imports, forbidden dependencies |

---

## How violations are stored

After evaluation, `VIOLATES` edges are written between violating classes and their policies:

```cypher
MATCH (c:Class {repo_id: "codeKG", fqn: "services.console.routes"})
      -[:VIOLATES]->
      (ap:ArchPolicy {repo_id: "codeKG", policy_id: "auto-403ee21d"})
RETURN c.fqn, ap.title, ap.severity
```

The `violator_count` on each `ArchPolicy` node is updated on each evaluation to reflect the current violation count.

---

## Writing policies

### Simple: class-level rule

```cypher
-- Policy: No class should have more than 500 lines
MATCH (c:Class {repo_id: $repo_id})
WHERE (c.end_line - c.start_line) > 500
  AND NOT c.kind IN ['module']
  AND NOT c.role IN ['TEST', 'GENERATED']
RETURN c.fqn AS violator, c.name AS name,
       (c.end_line - c.start_line) AS loc
```

### Cross-module dependency rule

```cypher
-- Policy: Console should not import directly from ingestion
MATCH (a:Class {repo_id: $repo_id})-[:IMPORTS]->(b:Class {repo_id: $repo_id})
WHERE a.file_path CONTAINS '/console/'
  AND b.file_path CONTAINS '/ingestion/'
RETURN a.fqn AS violator, b.fqn AS forbidden_dependency
```

### Package structure rule

```cypher
-- Policy: Every service module must have at least one test class
MATCH (m:Module {repo_id: $repo_id})
WHERE m.module_id STARTS WITH 'services/'
  AND NOT EXISTS {
    MATCH (c:Class {repo_id: $repo_id, role: 'TEST'})
    WHERE c.file_path STARTS WITH m.path
  }
RETURN m.module_id AS violator
```

### Annotation enforcement (Java)

```cypher
-- Policy: All @Repository classes must implement a Repository interface
MATCH (c:Class {repo_id: $repo_id})
WHERE "Repository" IN c.annotations
  AND NOT EXISTS {
    MATCH (c)-[:IMPLEMENTS]->(:Interface)
    WHERE "Repository" IN labels(c)
  }
RETURN c.fqn AS violator
```

---

## Console policy management

**`GET /policies`** — table of all policies with violator count, severity badge, and status toggle.

**`GET /policies/{policy_id}`** — detailed view:
- Policy description and Cypher constraint
- Full list of current violators with grade and blast radius
- When the policy was last evaluated
- Toggle to activate / disable

**`POST /api/policies/{policy_id}/activate`** — sets `status="active"`, policy will be evaluated on next scan.

---

## MCP integration

```python
# List active policies
list_arch_policies(repo_id="codeKG")
# → [{"policy_id": "...", "title": "Untested Package", "severity": "warning", "violator_count": 8}]

# Check violations for specific files you just changed
check_violations(
    repo_id="codeKG",
    file_paths=["services/api/main.py", "services/api/deps.py"]
)
# → {"violations": [], "files_checked": 2}
```

Always call `check_violations` after making changes to confirm you haven't introduced new violations.

---

## Auto-generated policies

The policy scanner (`ingestion/policy_scanner.py`) runs after each ingestion and generates policies from common patterns it detects:

| Auto-policy | Triggers when |
|-------------|--------------|
| `Untested Package` | Package has ≥3 classes and no test class |
| `High Coupling Class` | Class has coupling score > 0.3 |
| `Oversized Class` | Class has > 400 LOC |
| `Missing Javadoc` | Public class has no docstring and blast_size > 5 |
| `Circular Import` | Two classes import each other |

Generated policies start as `auto-draft` and appear in the console with an "Auto" badge. Activating them makes them enforced on future scans.

---

## Agent index integration

Active policy violations appear in `.codekg/policies/violations.md`:

```markdown
# Policy Violations — codeKG
_Generated 2026-06-05 20:34 UTC_

**8 violations across 2 active policies.**

## ⚠ Warning: Untested Package (8 violators)
_Every production package with 3+ classes should have at least one test class._

| Package | Classes | Grade |
|---------|---------|-------|
| `services.console.routes` | 12 | B |
| `shared.models.graph` | 4 | B |
| `services.ingestion.parser` | 8 | B |
...
```

And in `.codekg/policies/active.md`:

```markdown
# Active Policies — codeKG
_Generated 2026-06-05 20:34 UTC_

## Rules you must not violate

1. **Untested Package** (warning) — Every production package with 3+ classes must have at least one test class
2. **High Coupling Class** (warning) — No class should have coupling > 0.3

Read `policies/violations.md` to see which classes currently violate these rules.
```

Agents must read `policies/active.md` before writing any code. Writing code that creates new violations is a policy breach.

---

## Adding a custom policy

Via the console UI:
1. Go to `/policies`
2. Click "New policy"
3. Enter title, natural language description, severity
4. Write Cypher constraint (use `RETURN violator_fqn` convention)
5. Test against current graph
6. Activate

Via API (for CI/CD integration):
```python
POST /api/policies
{
  "repo_id": "codeKG",
  "title": "No direct Neo4j access from console routes",
  "natural_language": "Console route handlers must use run_query from deps.py, not connect directly",
  "cypher_constraint": "MATCH (c:Class {repo_id: 'codeKG'}) WHERE c.file_path CONTAINS '/console/routes/' AND c.object_model CONTAINS 'GraphDatabase.driver' RETURN c.fqn AS violator",
  "severity": "error",
  "status": "active"
}
```
