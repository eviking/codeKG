# Module: services/mcp
_Generated 2026-06-09 20:27 UTC · commit `unpublished`_

**Path:** `/host-home/Documents/projects/codeKG/services/mcp`  **Classes:** 9

## ⚡ Insights from previous sessions

_Non-obvious facts from engineering sessions — treat as expert hints._

- **services.mcp** (100%): codekg_request_id in the MCP response footer was previously the JSON-RPC request_id — a different value for every single tool call. This is why using the 'first call's request_id' was so fragile: any mistake in tracking which call was first gave a wrong value. Fixed by making codekg_request_id equal to turn_id in the footer, so both values are always the same stable string and there is no ambiguity about which to use.
- **services.mcp.main** (95%): sync_claude_md must return content to Claude Code rather than writing server-side — server-side writes break remote usage where the codeKG server and the engineer's filesystem are on different machines. The correct pattern is: tool returns content, Claude Code calls Write.
- **services.mcp.main** (85%): The sync_claude_md tool includes a save_as comment header in the response so Claude Code knows what filename to use without needing to infer it from context.

## Classes

### `TestCaptureInsight` — class
**File:** `services/mcp/tests/test_mcp_tools.py`  **LOC:** 37  **Grade:** ?  **Blast:** 0
**FQN:** `services.mcp.tests.test_mcp_tools.TestCaptureInsight`

Exercises capture insight behavior in the mcp tools test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.

### `TestErrorHandling` — class
**File:** `services/mcp/tests/test_mcp_tools.py`  **LOC:** 22  **Grade:** ?  **Blast:** 0
**FQN:** `services.mcp.tests.test_mcp_tools.TestErrorHandling`

Exercises error handling behavior in the mcp tools test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.

### `TestGetChangeImpact` — class
**File:** `services/mcp/tests/test_mcp_tools.py`  **LOC:** 16  **Grade:** ?  **Blast:** 0
**FQN:** `services.mcp.tests.test_mcp_tools.TestGetChangeImpact`

Exercises get change impact behavior in the mcp tools test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.

### `TestGetClass` — class
**File:** `services/mcp/tests/test_mcp_tools.py`  **LOC:** 13  **Grade:** ?  **Blast:** 0
**FQN:** `services.mcp.tests.test_mcp_tools.TestGetClass`

Exercises get class behavior in the mcp tools test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.

### `TestGetCodebaseTemplate` — class
**File:** `services/mcp/tests/test_mcp_tools.py`  **LOC:** 14  **Grade:** ?  **Blast:** 0
**FQN:** `services.mcp.tests.test_mcp_tools.TestGetCodebaseTemplate`

Exercises get codebase template behavior in the mcp tools test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.

### `TestGetRepoSummary` — class
**File:** `services/mcp/tests/test_mcp_tools.py`  **LOC:** 14  **Grade:** ?  **Blast:** 0
**FQN:** `services.mcp.tests.test_mcp_tools.TestGetRepoSummary`

Exercises get repo summary behavior in the mcp tools test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.

### `TestListArchPolicies` — class
**File:** `services/mcp/tests/test_mcp_tools.py`  **LOC:** 13  **Grade:** ?  **Blast:** 0
**FQN:** `services.mcp.tests.test_mcp_tools.TestListArchPolicies`

Exercises list arch policies behavior in the mcp tools test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.

### `TestSearchClasses` — class
**File:** `services/mcp/tests/test_mcp_tools.py`  **LOC:** 13  **Grade:** ?  **Blast:** 0
**FQN:** `services.mcp.tests.test_mcp_tools.TestSearchClasses`

Exercises search classes behavior in the mcp tools test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.

### `TestSessionId` — class
**File:** `services/mcp/tests/test_mcp_tools.py`  **LOC:** 12  **Grade:** ?  **Blast:** 0
**FQN:** `services.mcp.tests.test_mcp_tools.TestSessionId`

Exercises session id behavior in the mcp tools test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.
