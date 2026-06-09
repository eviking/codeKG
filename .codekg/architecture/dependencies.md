# Key Dependencies — codeKG
_Generated 2026-06-09 20:27 UTC_

## Import edges by module
All outgoing imports from each module, including to shared/external code.

| From module | To | Import edges |
|---|---|---|
| `external` | `shared/config.py` | 11 |
| `services/ingestion` | `shared/config.py` | 1 |

## Highest blast radius classes
Changing these classes affects the most dependents — approach with care.

### `config` — blast 12 classes
**FQN:** `shared.config`  **File:** `projects/codeKG/shared/config.py`
> codeKG centralised configuration. Every tuneable value in the system is defined here.  Each setting is read from an environment variable with a documented default.  Environment variables always win — 
