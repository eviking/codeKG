# Module: services/watcher
_Generated 2026-06-08 18:37 UTC · commit `unpublished`_

**Path:** `/host-home/Documents/projects/codeKG/services/watcher`  **Classes:** 3

## Classes

### `TestIsScanRunning` — class
**File:** `services/watcher/tests/test_watcher.py`  **LOC:** 27  **Grade:** A  **Blast:** 0
**FQN:** `services.watcher.tests.test_watcher.TestIsScanRunning`

Exercises is scan running behavior in the watcher test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.

| Method | Parameters | Returns | Notes |
|--------|-----------|---------|-------|
| `public test_returns_false_when_no_matching_container` | — | — |  |
| `public test_returns_true_when_matching_container_exists` | — | — |  |

### `TestLaunchScan` — class
**File:** `services/watcher/tests/test_watcher.py`  **LOC:** 79  **Grade:** A  **Blast:** 0
**FQN:** `services.watcher.tests.test_watcher.TestLaunchScan`

Exercises launch scan behavior in the watcher test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.

| Method | Parameters | Returns | Notes |
|--------|-----------|---------|-------|
| `public test_home_mount_volume_added_when_set` | — | — |  |
| `public test_passes_scan_env_vars` | — | — |  |
| `public test_incremental_scan_passes_commits` | — | — |  |
| `public test_container_labelled_with_repo_id` | — | — |  |
| `protected _make_client` | — | — |  |

### `TestLoadRepos` — class
**File:** `services/watcher/tests/test_watcher.py`  **LOC:** 46  **Grade:** A  **Blast:** 0
**FQN:** `services.watcher.tests.test_watcher.TestLoadRepos`

Exercises load repos behavior in the watcher test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen.

| Method | Parameters | Returns | Notes |
|--------|-----------|---------|-------|
| `public test_reads_from_repos_json` | `tmp_path` | — |  |
| `public test_returns_empty_when_neither_exists` | `tmp_path` | — |  |
| `public test_falls_back_to_filesystem_discovery` | `tmp_path` | — |  |
