# Key Dependencies — codeKG
_Generated 2026-06-08 14:12 UTC_

## Import edges by module
All outgoing imports from each module, including to shared/external code.

| From module | To | Import edges |
|---|---|---|
| `services/api` | `logging/codekg_logger.py` | 4 |
| `services/ingestion` | `logging/codekg_logger.py` | 3 |
| `services/console` | `logging/codekg_logger.py` | 1 |

## Highest blast radius classes
Changing these classes affects the most dependents — approach with care.

### `codekg_logger` — blast 8 classes
**FQN:** `shared.logging.codekg_logger`  **File:** `codeKG/shared/logging/codekg_logger.py`
> codekg_logger is a utility class designed to facilitate logging operations within an application. It includes methods such as `logInfo(String message)` for recording informational messages, `logError(
