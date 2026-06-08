# Setting Up GitHub Authentication

By default codeKG runs in single-user mode with no authentication — appropriate for
localhost development. This guide walks through enabling GitHub OAuth so that only
specific people can access your codeKG instance.

---

## Prerequisites

- codeKG is running (`docker compose up -d`)
- You have a GitHub account
- The console is reachable at a URL you control (e.g. `http://localhost:8080` for local,
  or a real domain for a shared deployment)

---

## Step 1 — Register a GitHub OAuth App

1. Go to **https://github.com/settings/developers**
2. Click **"OAuth Apps"** in the left sidebar
3. Click **"New OAuth App"**
4. Fill in the form:

   | Field | Value |
   |-------|-------|
   | **Application name** | `codeKG` (or anything you like) |
   | **Homepage URL** | `http://localhost:8080` |
   | **Authorization callback URL** | `http://localhost:8080/auth/callback` |

   > For a production deployment replace `http://localhost:8080` with your actual URL,
   > e.g. `https://codekg.yourcompany.com`.

5. Click **"Register application"**
6. On the next screen you will see your **Client ID** — copy it.
7. Click **"Generate a new client secret"** — copy the secret immediately.
   GitHub only shows it once.

---

## Step 2 — Generate a session secret

The session secret signs the browser cookies so they cannot be forged.
Run this once and save the output:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

Example output: `3Kx9mPqR7vLnWzYtAhJcBdEsFgUiOk2N`

---

## Step 3 — Add the credentials to your `.env` file

Open `.env` (copy from `.env.example` if it doesn't exist yet) and add:

```bash
# GitHub OAuth
GITHUB_CLIENT_ID=Ov23li...          # from Step 1
GITHUB_CLIENT_SECRET=abc123...      # from Step 1
SESSION_SECRET=3Kx9mPqR7vLnWzYtAhJcBdEsFgUiOk2N   # from Step 2
```

---

## Step 4 — Choose your access control policy

Pick **one** of the options below. Add the relevant lines to `.env`.

---

### Option A — Restrict to a GitHub organisation

Everyone in the org can access codeKG. Access is managed entirely in GitHub —
add or remove org members there and access updates immediately.

```bash
GITHUB_ORG=your-org-name
```

> The OAuth App needs `read:org` scope to check membership. codeKG requests this
> automatically when `GITHUB_ORG` is set.

---

### Option B — Restrict to a team within an org

More granular than option A. Only members of a specific team get access.

```bash
GITHUB_ORG=your-org-name
GITHUB_TEAM=platform-engineers     # the team's slug (not display name)
```

**Finding the team slug:**
Go to `https://github.com/orgs/<your-org>/teams` → click the team →
the slug is the last segment of the URL:
`https://github.com/orgs/acme/teams/platform-engineers` → slug is `platform-engineers`

---

### Option C — Allowlist specific GitHub usernames

No org required. Useful for small groups or open source maintainers.

```bash
ALLOWED_GITHUB_USERS=alice,bob,carol
```

To add or remove someone: edit this value and restart the console container
(`docker compose restart console`).

---

### Option D — Any authenticated GitHub user

Leave `GITHUB_ORG`, `GITHUB_TEAM`, and `ALLOWED_GITHUB_USERS` all empty (or unset).
Anyone with a GitHub account can log in.

```bash
# nothing extra needed beyond GITHUB_CLIENT_ID / GITHUB_CLIENT_SECRET / SESSION_SECRET
```

---

## Step 5 — Restart the console

```bash
docker compose restart console
```

Or if you changed `requirements.txt` (first-time setup):

```bash
docker compose up -d --build console
```

---

## Step 6 — Verify it works

1. Open `http://localhost:8080` in your browser (or your production URL)
2. You should be redirected to `http://localhost:8080/auth/login`
3. Click **"Continue with GitHub"**
4. GitHub asks you to authorise the app — click **"Authorize"**
5. You are redirected back to the console, logged in
6. Your GitHub avatar and username appear in the top-right corner of every page
7. Clicking the arrow icon next to your name signs you out

---

## Step 7 — Secure the API (recommended)

The console talks to the API service internally. If your API port (`8000`) is exposed
to a network you don't fully trust, add a token so that only authorised callers
can use it.

Generate a token:
```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

Add it to `.env`:
```bash
API_TOKEN=your-generated-token-here
```

Then restart both services:
```bash
docker compose restart api console
```

The console and MCP server read `API_TOKEN` from their environment and pass it
automatically on every request to the API. No other configuration needed.

> **If you leave `API_TOKEN` empty** the API remains open — fine for localhost where
> port `8000` is not reachable from outside your machine.

---

## Troubleshooting

### Redirect loop after login

The callback URL registered in GitHub doesn't match the URL your browser used.

Fix: go to https://github.com/settings/developers → your OAuth App → update
**Authorization callback URL** to exactly match your console URL, including the
`/auth/callback` path.

---

### "Access denied — not a member of your-org"

The GitHub account you logged in with is not in the org (or team). Either:
- Add the account to the org/team in GitHub, or
- Switch to option C (allowlist) and add the username directly

---

### "Access denied — your GitHub account is not on the allowed users list"

Your username isn't in `ALLOWED_GITHUB_USERS`. Edit `.env`, add your username,
and restart the console: `docker compose restart console`

---

### The login page shows but clicking the button does nothing / error from GitHub

`GITHUB_CLIENT_ID` or `GITHUB_CLIENT_SECRET` is wrong or blank.
Double-check the values in `.env` against https://github.com/settings/developers.

---

### Session keeps expiring immediately

`SESSION_SECRET` changed between restarts (or was never set consistently).
Every time `SESSION_SECRET` changes all existing sessions are invalidated.
Set it once to a fixed value in `.env` and don't change it.

---

### API returns 401 after adding `API_TOKEN`

The MCP server or console is not picking up the new token. Restart all services:

```bash
docker compose restart api console mcp
```

If using the API directly (curl, scripts), add the header:
```bash
curl -H "Authorization: Bearer your-token-here" http://localhost:8000/repos
```

---

## Production checklist

Before exposing codeKG to the internet:

- [ ] `SESSION_SECRET` is set to a random value (not the default `dev-secret-change-me`)
- [ ] `API_TOKEN` is set if port `8000` is reachable externally
- [ ] GitHub OAuth callback URL uses `https://` not `http://`
- [ ] Set `secure=True` on the session cookie in `services/console/auth.py` (one line change, required for HTTPS)
- [ ] `GITHUB_CLIENT_SECRET` is in `.env` and `.env` is in `.gitignore` ✓

---

## Summary of all auth-related env vars

| Variable | Required | Description |
|----------|----------|-------------|
| `GITHUB_CLIENT_ID` | Yes (to enable auth) | From your GitHub OAuth App |
| `GITHUB_CLIENT_SECRET` | Yes (to enable auth) | From your GitHub OAuth App |
| `SESSION_SECRET` | Yes (to enable auth) | Random string — signs session cookies |
| `GITHUB_ORG` | No | Restrict to members of this GitHub org |
| `GITHUB_TEAM` | No | Restrict to this team within `GITHUB_ORG` (team slug) |
| `ALLOWED_GITHUB_USERS` | No | Comma-separated GitHub usernames |
| `API_TOKEN` | No | Bearer token required on all API requests |
