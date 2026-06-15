# codeKG for Salesforce Developers

This guide is for developers working in Salesforce DX repos indexed by codeKG — Apex, LWC, Aura, Flows, sObjects, and permission sets.

---

## What codeKG indexes in your Salesforce org

| Artifact | File pattern | What you get in the graph |
|----------|-------------|--------------------------|
| Apex classes | `*.cls` | Classes, methods, SOQL queries, call chains |
| Apex triggers | `*.trigger` | Trigger class, sObject, events (`before insert` etc.) |
| Lightning Web Components | `*.html`, `*.js`, `*.js-meta.xml` | Component composition, `@wire` adapters, target metadata |
| Aura components | `*.cmp`, `*.app`, `*.design` | Child components, Apex controller wiring, App Builder attributes |
| Flows | `*.flow-meta.xml` | Apex actions, subflow calls, record ops, screen components |
| sObject schemas | `*.object-meta.xml`, `*.field-meta.xml` | Fields, types, lookup/MasterDetail relationships |
| Permission sets | `*.permissionSet-meta.xml` | Class access, object permissions, flow access |
| Profiles | `*.profile-meta.xml` | Class access, object permissions, flow access |

---

## Reading the knowledge graph as a Salesforce developer

### FQN conventions
Every artifact has a fully qualified name (FQN) in the graph. Know these patterns:

| Artifact | FQN format | Example |
|----------|-----------|---------|
| Apex class | `ClassName` | `AccountService` |
| Apex trigger | `TriggerName` | `AccountTrigger` |
| LWC component | `lwc/componentName` | `lwc/accountCard` |
| Aura component | `aura/componentName` | `aura/myOpportunityApp` |
| Flow | `flow/FlowName` | `flow/CreateCaseOnEscalation` |
| sObject | `sobject/ObjectName` | `sobject/Account`, `sobject/Revenue__c` |
| Permission set | `permission_set/PSName` | `permission_set/SalesRepPermissions` |
| Profile | `profile/ProfileName` | `profile/Standard` |

### Edge types you'll encounter
| Edge | Meaning |
|------|---------|
| `CALLS` | Apex method calls another method / Apex action invoked from a Flow / `@wire` adapter call |
| `QUERIES` | SOQL query against an sObject / Flow record op / `@wire` sObject reference |
| `USES` | LWC or Aura component references a child component |
| `REFERENCES` | sObject field has a Lookup or MasterDetail to another sObject |
| `GRANTS` | Permission set grants access to a class, object, or Flow |
| `EXTENDS` | Apex class extends another class |
| `IMPLEMENTS` | Apex class implements an interface |

---

## Things that look wrong but aren't

### `@InvocableMethod` with no callers
Apex methods annotated `@InvocableMethod` are invoked exclusively from Flows at runtime — no Apex class ever calls them directly. In the graph they will have zero `CALLS` edges from other classes. Their callers are `flow/` nodes. Before marking one as unused, search the graph for `flow/` nodes that have a `CALLS` edge to the Apex class.

### `@AuraEnabled` methods with surprising blast radius
Every LWC/Aura component that invokes an `@AuraEnabled` method connects to it via a `CALLS` edge. These methods sit at the Apex/UI boundary and often have higher blast radius than they appear to in source code alone. Always run `get_change_impact` before touching them.

### Classes in permission sets with no Apex callers
If a class is referenced only in `GRANTS` edges from permission sets, it is a Visualforce controller or an Apex class exposed to REST/SOAP. It has no internal callers by design.

### Flows with no `CALLS` inbound edges
Scheduled flows, platform event–triggered flows, and flows launched via Process Builder have no static callers in the repo. They are triggered at runtime by Salesforce infrastructure. Check `@flowType(...)` and `@triggerObject(...)` annotations on the flow class node.

---

## Common tasks with codeKG

### "What does this Apex class connect to?"
Use `get_class_context` via the MCP tool or look up the class in `.codekg/modules/<name>.md`. The class entry shows:
- Outbound `CALLS` edges (which methods does it call?)
- Outbound `QUERIES` edges (which sObjects does it query?)
- Inbound connections (which classes and Flows call it?)

### "I'm modifying an sObject field — what will break?"
1. Look up the sObject in the graph: `sobject/MyObject__c`
2. Check `REFERENCES` edges — which other sObjects point to this one?
3. Check which Apex classes query this sObject (`QUERIES` edges pointing to it)
4. Check which Flows read or write it (`QUERIES` edges from `flow/` nodes)
5. Run `get_change_impact` on the `.object-meta.xml` or `.field-meta.xml` file

### "Is this Flow calling the right Apex method?"
Flow `CALLS` edges point to Apex class names directly (not method names — Flow invokes `@InvocableMethod` by class). If the edge target doesn't match a class in the graph, the Flow references a class in a managed package not indexed in this repo.

### "What permission sets expose this class/object?"
Search for `GRANTS` edges where the target is your class or sObject. Permission set nodes are `kind=permission_set` or `kind=profile`.

### "Which LWC components use this child component?"
Find the component's FQN (`lwc/componentName`) and look for inbound `USES` edges. These come from parent LWC and Aura components.

---

## Blast radius in a Salesforce context

The blast radius score reflects how many other classes, components, and artifacts depend on a given node. High-blast-radius nodes to watch for:

| Node type | Why high blast radius matters |
|-----------|-------------------------------|
| Utility Apex class (`TriggerHandler`, `SObjectUtils`) | Called from many triggers and service classes |
| `@AuraEnabled` method | Depended on by all LWC/Aura callers — changing signature breaks components |
| sObject with many `REFERENCES` edges | Removing/renaming fields breaks all lookup relationships |
| Widely-used Flow | Called by other Flows (subflow edges) and invoked from Process Builder |
| Base permission set | Grants access that many profiles inherit — changes affect many users |

Before touching any node with blast > 10, read `.codekg/architecture/hotspots.md`.

---

## Architecture policies for Salesforce repos

Consider defining these Cypher policies in codeKG (via the console's policy editor):

```cypher
-- Triggers must not contain business logic directly (use handler classes)
MATCH (c:Class {repo_id: $repo_id, kind: "trigger"})
WHERE NOT EXISTS {
    MATCH (c)-[:CALLS]->(:Class {repo_id: $repo_id})
}
RETURN c.fqn AS violator

-- @InvocableMethod classes should not also have @AuraEnabled methods
-- (mixing invocable and UI surface is a separation-of-concerns smell)
MATCH (c:Class {repo_id: $repo_id})-[:HAS_METHOD]->(m1:Method)
WHERE m1.annotations CONTAINS '@InvocableMethod'
WITH c
MATCH (c)-[:HAS_METHOD]->(m2:Method)
WHERE m2.annotations CONTAINS '@AuraEnabled'
RETURN DISTINCT c.fqn AS violator
```

---

## Tribal knowledge — what to capture

After each session, call `capture_insight` with non-obvious facts. Examples of high-value Salesforce insights:

- "The `CaseEscalationFlow` is a Scheduled flow — it runs nightly at 02:00 UTC. Any Apex called from it must be bulkified and governor-limit-safe."
- "The `AccountTrigger` uses a static flag (`TriggerHelper.isFirstRun`) to prevent recursion. Never call DML in a loop in this handler."
- "The `Revenue__c` MasterDetail to `Opportunity` has cascade delete. Deleting an Opportunity deletes all Revenue records — this is a known data loss risk."
- "`CommunitiesLoginCtrl` is exposed in the `GuestUserProfile` — any change to its `@AuraEnabled` methods affects unauthenticated community users."
