"""Persistence helpers for the API service's agent index views. Watch out for schema drift here, because the console and shared tooling depend on the same stored shape."""

# Single source of truth lives in shared/agent_index/store.py.
# This shim re-exports everything so existing imports continue to work unchanged.
from shared.agent_index.store import *  # noqa: F401 F403
from shared.agent_index.store import (  # noqa: F401
    AGENT_INDEX_DB,
    _validate_table,
    _con,
    _lock,
    _VALID_TABLES,
    init_db,
    upsert_file,
    get_file,
    list_files,
    update_manual_additions,
    toggle_hidden,
    mark_published,
    mark_stale,
)
