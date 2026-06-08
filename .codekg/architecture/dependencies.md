# Key Dependencies — codeKG
_Generated 2026-06-08 18:37 UTC_

## Import edges by module
All outgoing imports from each module, including to shared/external code.

| From module | To | Import edges |
|---|---|---|
| `external` | `shared/config.py` | 11 |
| `services/api` | `shared/config.py` | 7 |
| `services/api` | `logging/codekg_logger.py` | 5 |
| `external` | `shared/llm.py` | 5 |
| `services/ingestion` | `logging/codekg_logger.py` | 3 |
| `services/ingestion` | `shared/config.py` | 2 |
| `services/console` | `shared/config.py` | 1 |
| `services/console` | `logging/codekg_logger.py` | 1 |

## Highest blast radius classes
Changing these classes affects the most dependents — approach with care.

### `config` — blast 21 classes
**FQN:** `shared.config`  **File:** `projects/codeKG/shared/config.py`
> codeKG centralised configuration. Every tuneable value in the system is defined here.  Each setting is read from an environment variable with a documented default.  Environment variables always win — 

### `codekg_logger` — blast 9 classes
**FQN:** `shared.logging.codekg_logger`  **File:** `codeKG/shared/logging/codekg_logger.py`
> CodeKG centralized structured logging. Usage in any service: from shared.logging.codekg_logger import get_logger log = get_logger(__name__, service="ingestion") log.info("Scan started", repo_id="org/m

### `llm` — blast 5 classes
**FQN:** `shared.llm`  **File:** `projects/codeKG/shared/llm.py`
> codeKG unified LLM client. Wraps Anthropic, OpenAI, and Ollama behind a single interface so every call site in the codebase can stay provider-agnostic. Usage ----- from shared.llm import llm, LLMRespo

### `_Provider` — blast 3 classes
**FQN:** `shared.llm._Provider`  **File:** `projects/codeKG/shared/llm.py`
> Implement these two methods to add a new LLM provider.
