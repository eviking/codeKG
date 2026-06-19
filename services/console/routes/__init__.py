"""Console route package. Watch out for circular imports here, because the main app imports these modules eagerly during startup."""

from routes import (  # noqa: F401
    repos, dashboard, policies, modules, classes,
    patterns, ask, mcp_audit, system_health, audit_log,
    insights, hygiene, agent_index, telemetry, getstarted, commits,
)
