<!-- codekg:start -->
## CodeKG Agent Index
_Auto-maintained — regenerated on every git commit. Do not edit this section manually._

## ⚠ MANDATORY: Read before doing anything else

**DO NOT** use `find`, `ls`, `grep`, or `Read` to explore this codebase.
**DO NOT** open source files to understand structure, find classes, or read method signatures.
**DO NOT** start writing code without first reading the index files below.

Pre-computed index files in `.codekg/` contain **complete, always-current** class and method
detail for every module. They were built from the full AST and knowledge graph — they are more
complete and accurate than anything you would find by exploring source files manually.
Raw file exploration wastes your context window and produces incomplete understanding.

**Your first action on every task MUST be:**
```
Read .codekg/INDEX.md
```
This takes 2 seconds and tells you exactly which files to read next.

### Index mode: **per-module** (repo LOC 12212 — separate files per module)
Each module has its own index file with full class and method detail.
Read the relevant module file before writing any code in that area.

### Required reading — do this before writing a single line of code
1. **Read `.codekg/policies/active.md`** — architectural rules you must not violate
2. **Read `.codekg/modules/<name>.md`** for the module you're working in
   — every class, every method with full parameter and return type signatures
3. **Read `.codekg/architecture/hotspots.md`** if you plan to touch any high-blast-radius class
If you skip these, you will write code that conflicts with existing patterns.

### Quick reference
| Need | File |
|---|---|
| Repo structure & module list | `.codekg/architecture/modules.md` |
| Cross-module dependencies | `.codekg/architecture/dependencies.md` |
| All data stores + schemas | `.codekg/architecture/datastores.md` |
| Pages/screens, routes, nav links | `.codekg/architecture/screens.md` |
| Design patterns | `.codekg/architecture/patterns.md` |
| Risky classes | `.codekg/architecture/hotspots.md` |
| Architectural rules | `.codekg/policies/active.md` |
| Current violations | `.codekg/policies/violations.md` |
| Full module detail (classes + methods) | `.codekg/modules/<name>.md` |
| Recent commits & index changes | `.codekg/architecture/recent_changes.md` |

### Modules in this repo
- `services/api` — services/api
- `services/console` — services/console
- `services/ingestion` — services/ingestion
- `services/mcp` — services/mcp
- `services/watcher` — services/watcher

### When to call CodeKG MCP tools directly
The module index files cover most tasks. Only go direct for:
- **`get_change_impact`** — live blast radius on files you just modified
- **`search_classes`** — finding a class when you don't know its module
- **`capture_insight`** — always call this when you discover something non-obvious
<!-- codekg:end -->
