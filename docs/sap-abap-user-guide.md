# codeKG for SAP ABAP Developers

This guide is for developers working in abapGit repos indexed by codeKG — OO ABAP classes, function modules, FORM subroutines, Open SQL, INCLUDE programs, and BAdI implementations.

---

## What codeKG indexes in your ABAP repo

| Artifact | What you get in the graph |
|----------|--------------------------|
| OO ABAP classes | Classes, interfaces, methods, fields, inheritance, interface implementations |
| Function modules & BAPIs | `CALL FUNCTION` call edges to function module names |
| FORM subroutines | Subroutines grouped under a synthetic module class; `PERFORM` edges |
| Open SQL | `SELECT`/`INSERT`/`UPDATE`/`DELETE` table access via regex extraction |
| INCLUDE programs | `INCLUDE` stitching — INCLUDE files connected to their host programs |
| BAdI implementations | Classes implementing `IF_EX_*`/`ZIF_EX_*` annotated as `@BAdI(...)` |
| Interfaces | ABAP interface definitions with method signatures |

---

## Reading the knowledge graph as an ABAP developer

### FQN conventions
| Artifact | FQN format | Example |
|----------|-----------|---------|
| OO class | `ClassName` | `ZCL_SALES_ORDER_FACTORY` |
| Interface | `InterfaceName` | `ZIF_SALES_HANDLER` |
| Function module | Function module name | `BAPI_SALESORDER_CREATEFROMDAT2` |
| FORM subroutine | `FormName` | `PROCESS_HEADER` |
| ABAP table (QUERIES target) | Table name | `VBAK`, `MARA`, `KNA1` |

### Edge types you'll encounter
| Edge | Meaning |
|------|---------|
| `CALLS` | Method calls another method / `CALL FUNCTION` / `PERFORM` / `INCLUDE` |
| `QUERIES` | Open SQL access to a database table |
| `EXTENDS` | Class inherits from another class (`INHERITING FROM`) |
| `IMPLEMENTS` | Class implements an interface (`INTERFACES`) |

---

## Things that look wrong but aren't

### BAdI implementations with no callers
Classes annotated `@BAdI(IF_EX_*)` implement a Business Add-In exit interface. Their methods are called at runtime via `CALL BADI <handle>` — the framework dispatches to them, not any code in this repo. They will have **zero inbound `CALLS` edges**. Do not treat them as dead code. The `@BAdI(...)` annotation is the signal.

### FORM subroutines with only one "caller" (the synthetic module)
FORM subroutines appear under a synthetic `<program_name>` class in the graph. If a subroutine only shows the module class as its parent and no inbound `CALLS` edges, it may be called from a report event block (`START-OF-SELECTION`, `END-OF-SELECTION`) that is not separately indexed. Check the raw source before removing it.

### INCLUDE files with no standalone callers
INCLUDE programs are code fragments — they only exist as part of their host program. An INCLUDE will show inbound `CALLS` edges from its host. If it has none, the host program may not have been scanned yet (perhaps it's in a different package not yet in the repo).

### CALL FUNCTION edges with `unresolved=true`
Function module calls where the FM is defined in another package, transport request, or external system appear with `unresolved=true` in the edge metadata. This is normal — do not attempt to resolve them across system boundaries. BAPIs starting with `BAPI_` are stable SAP contracts; their target classes are never in the local repo.

---

## Open SQL — what the graph captures and what it misses

codeKG extracts Open SQL via **regex on raw source text** (the tree-sitter ABAP grammar does not produce structured SQL AST nodes). This covers the common patterns reliably:

| Statement | Captured as |
|-----------|-------------|
| `SELECT … FROM <table>` | `QUERIES` edge to `<table>` |
| `INSERT INTO <table>` | `QUERIES` edge to `<table>` |
| `INSERT <table> FROM …` | `QUERIES` edge to `<table>` |
| `UPDATE <table> SET …` | `QUERIES` edge to `<table>` |
| `DELETE FROM <table>` | `QUERIES` edge to `<table>` |
| `MODIFY <table>` | `QUERIES` edge to `<table>` |

**What may be missed:**
- Complex inline conditions where the table name appears after many continuation lines
- `SELECT … INTO TABLE` patterns with uncommon formatting
- Dynamic `SELECT` with `(field_list)` or table name in a variable — these are unanalyzable statically

For security-sensitive objects or audits, verify critical table access by reading the source directly in addition to the graph.

---

## Common tasks with codeKG

### "What tables does this class/program access?"
Look up the class in the module index. All `QUERIES` edges will be listed. The target is the ABAP transparent table name (e.g. `VBAK`, `MARA`) — cross-reference with the SAP Data Dictionary (SE11) for field details.

### "I'm modifying a function module — what calls it?"
Function modules appear as nodes with `CALLS` edges from all callers that were scanned. If the FM is in a different package than its callers, callers from other packages are only included if those packages are also in the repo (or have been scanned).

### "Is this BAdI implementation active?"
The `@BAdI(IF_EX_*)` annotation on the class tells you which exit interface it implements. Whether it's currently active (filter conditions, multiple implementations) is determined by the BAdI definition in the system — this is runtime metadata not captured in the static graph.

### "What does this INCLUDE touch?"
An INCLUDE program's `CALLS` and `QUERIES` edges are attributed to the INCLUDE class node. To find the host programs that use this INCLUDE, look for inbound `CALLS` edges to the INCLUDE's FQN.

### "Which classes inherit from this base class?"
Look for `EXTENDS` edges pointing to the base class. These are direct subclasses only — for transitive subclasses, follow the chain through the graph.

### "What is the blast radius of changing this utility class?"
Run `get_change_impact` on the utility class's source file, or check the blast radius score in the module index. High-blast-radius utility classes in ABAP often include:
- Shared base classes for application frameworks
- Utility classes used across multiple programs (`ZCL_*_UTIL`, `ZCL_*_HELPER`)
- Function groups whose data is shared across all their function modules

---

## Blast radius in an ABAP context

High blast radius in ABAP means many classes or programs call this artifact. Key patterns to watch:

| Node type | Why high blast radius matters |
|-----------|-------------------------------|
| ABAP utility class (`ZCL_*_UTIL`) | Called from dozens of programs — interface change breaks all callers |
| Function group `TOP` INCLUDE | Shared data area for all FMs in the group — changing types breaks them all |
| Widely-used interface | All implementing classes must be updated if the interface changes |
| Shared INCLUDE program | Many host programs embed it — bugs here affect all of them |
| BAPI function module | External API contract — renaming the FM breaks all external callers permanently |

---

## Namespace rules — what's safe to modify

| Pattern | Rule |
|---------|------|
| `Z*`, `Y*` | Customer namespace — safe to modify |
| `/CUSTOMER/*` | Customer namespace reservation — safe to modify |
| `/SAP*/`, `/CORE*/`, `/BI*/` | SAP namespace — **never modify directly**. Create enhancement spots or BAdIs instead |
| `IF_EX_*` (interfaces) | SAP BAdI exit interfaces — implement, never modify |
| `BAPI_*` (function modules) | Stable SAP API — never rename; extend via wrapper if needed |

---

## Architecture policies for ABAP repos

Consider defining these Cypher policies in codeKG:

```cypher
-- No direct SELECT on SAP core tables from customer programs
-- (use function modules or APIs instead)
MATCH (c:Class {repo_id: $repo_id})-[q:QUERIES]->(t)
WHERE c.fqn STARTS WITH 'Z' OR c.fqn STARTS WITH 'Y'
  AND t.fqn IN ['T001', 'T005', 'USR02']  -- core config/auth tables
RETURN c.fqn AS violator, t.fqn AS table

-- BAdI implementations should only implement exit interfaces
MATCH (c:Class {repo_id: $repo_id})-[:IMPLEMENTS]->(i)
WHERE c.annotations CONTAINS '@BAdI'
  AND NOT (i.fqn STARTS WITH 'IF_EX_' OR i.fqn STARTS WITH 'ZIF_EX_')
RETURN c.fqn AS violator, i.fqn AS suspicious_interface
```

---

## Tribal knowledge — what to capture

After each session, call `capture_insight` with non-obvious facts. Examples of high-value ABAP insights:

- "The `BAPI_SALESORDER_CREATEFROMDAT2` call in `ZCL_ORDER_FACTORY` must always pass `CONVERT=X` in the ORDER_HEADER_IN structure — without it, the date conversion silently fails in non-DE locales."
- "The `ZCL_PRICING_HANDLER` implements `IF_EX_PRICING_ENGINE` — it is the active BAdI for pricing in this system. There is a second inactive implementation `ZCL_PRICING_HANDLER_LEGACY` that must not be activated."
- "The `ZINCLUDE_HEADER_TOP` INCLUDE is shared by 12 reports. Any change to the field declarations in it requires a full regression test of all host programs."
- "SELECT on `VBAP` without a WHERE clause on `MANDT` causes a full-table scan in production — always include `MANDT = SY-MANDT` in VBAP queries."
- "The `ZFUNC_PAYMENT_SETTLE` function module has a `COMMIT WORK` inside it. Never call it inside a `CALL FUNCTION … IN UPDATE TASK` wrapper — the COMMIT will raise a runtime error."
