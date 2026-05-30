# PackVault — Implementation Plan

This document is the **single source of truth** for the current development batch. It survives across conversations: read it at the start of each session, pick the **first unchecked todo**, implement it, mark it done, commit the file update with the code.

**Status:** Awaiting approval — mark **Approved** below before implementation begins.

| Field | Value |
|-------|-------|
| Approved | No |
| Last todo completed | §7.2 docs/configuration.md |
| Last updated | 2026-05-30 |

---

## Todos

Work **top to bottom**. One todo (or one numbered sub-item) per conversation is fine. Mark `[x]` when complete; note the item in **Last todo completed** above.

### 1. Metrics on port 9090

- [x] 3.1 Secondary listener on `9090` serving only `/metrics`
- [x] 3.2 Remove `/metrics` from main app port (`8080`)
- [x] 3.3 Config: `server.metrics_port` (default `9090`)
- [x] 3.4 `docker-compose.yaml` — expose port 9090
- [x] 3.5 Helm chart — metrics port on Service
- [x] 3.6 Tests

### 2. UI error boundary

- [x] 1.1 HTML error page template (`error.html`) with safe message + reference ID
- [x] 1.2 Detect UI vs Maven/API requests; UI gets HTML, Maven keeps JSON
- [x] 1.3 Log all errors with `request_id`, route, user, exception detail
- [x] 1.4 Inline form error pattern (query param or context for login/setup forms)
- [x] 1.5 Tests

### 3. Auth pages

- [x] 2.1 Failed login → redirect to `/login` with message + reference ID (not JSON)
- [x] 2.2 Login template error banner
- [x] 2.3 `/logged-out` page; logout redirects there instead of `/`
- [x] 2.4 Google OAuth failure → same login error pattern
- [x] 2.5 Tests



### 4. PostgreSQL foundation + setup wizard

- [x] 4.1 Config models: `database.url`, `secrets.*`, `server.metrics_port`
- [x] 4.2 SQLAlchemy async engine + session lifecycle
- [x] 4.3 Alembic migrations + initial schema (see [PostgreSQL schema](#postgresql-schema-initial))
- [x] 4.4 Encryption layer (`encrypt_at_rest`, env + AWS Secrets Manager key providers)
- [x] 4.5 `SecretProtector`: encrypt/decrypt secret fields; `decrypt_failed` row status
- [x] 4.6 Setup page `/setup` + `POST /admin/setup/initialize` (schema apply + seed + mark initialized)
- [x] 4.7 Redirect bootstrap admin to `/setup` until initialized; dashboard after
- [x] 4.8 “Already completed” page + API `409` on revisit
- [x] 4.9 Startup read-only checks (no DDL/seed on boot; fail fast if initialized but DB bad)
- [x] 4.10 Import Maven tokens from env/config into DB on initialize (hashes only)
- [x] 4.11 Bootstrap admin stays env-only — never store password in DB
- [x] 4.12 `docker-compose.yaml` — PostgreSQL service + `PACKVAULT_DATABASE_URL`
- [x] 4.13 `env.example`, `config/dev.yaml` updates
- [x] 4.14 Tests

### 5. Storage extensions

- [x] 5.1 Paginated `list_prefix` (local + S3 + cached)
- [x] 5.2 `delete(key)` on all storage backends
- [x] 5.3 Tests

### 6. Artifacts UI

- [x] 6.1 `/artifacts` route — list + search (path prefix) + pagination
- [x] 6.2 Default filter hides checksum sidecars and `maven-metadata.xml`
- [x] 6.3 Delete via POST + confirmation
- [x] 6.4 Audit log on delete (includes `request_id`)
- [x] 6.5 Dashboard nav link (`Dashboard | Artifacts | Logout`)
- [x] 6.6 Tests

### 7. Documentation

- [x] 7.1 `docs/operations.md` — setup flow, metrics port, bootstrap admin recovery, encryption
- [x] 7.2 `docs/configuration.md` — new config sections and env vars

---

## For future sessions (agents and humans)

1. Read this file first — especially **Todos** and **Locked design decisions**.
2. Implement the **first unchecked** item only unless the user asks for more.
3. Mark the todo `[x]` and update **Last todo completed** / **Last updated** when done.
4. Do not re-litigate locked decisions unless the user explicitly changes them.
5. Maven tokens remain env-based this batch; bootstrap admin password never goes in Postgres.

---

## Product context

PackVault is a **focused, self-hosted Maven/Gradle artifact gateway**. It is not competing with Nexus or Artifactory. The goal is to do one thing extremely well: host packages reliably, make publish/consume straightforward, and provide just enough operator tooling to run it day to day.

Functional quality matters; feature bloat does not.

---

## Scope summary

| # | Feature | In this batch |
|---|---------|---------------|
| 1 | Metrics on dedicated port (9090) | Yes |
| 2 | UI error handling with traceable reference IDs | Yes |
| 3 | Failed login, logout, and logged-out pages | Yes |
| 4 | PostgreSQL foundation + one-time setup wizard | Yes |
| 5 | Optional encryption at rest for secret fields | Yes |
| 6 | Artifact list, search, and delete (UI) | Yes |
| 7 | Maven tokens from environment (unchanged) | Yes — no change |
| 8 | App-managed token creation (CI + reader style) | **Future** |
| 9 | User/group/token admin UI | **Future** |
| 10 | SSO user provisioning into groups | **Future** |
| 11 | Local user creation (non-bootstrap) | **Future** |

---

## Locked design decisions

### Bootstrap platform admin (env-only, forever)

The initial platform admin **never** has credentials stored in PostgreSQL.

| Item | Source |
|------|--------|
| Username | `PACKVAULT_LOCAL_ADMIN_USERNAME` (env / config substitution) |
| Password | `PACKVAULT_LOCAL_ADMIN_PASSWORD_HASH` (Argon2 hash in env) |
| Database | **Not stored** — login always validates against env |

Recovery if admin access is lost: regenerate Argon2 hash (existing `scripts/hash_password.py`), update env, restart. No database surgery required.

The bootstrap admin retains **platform admin** privileges via session identity derived from env auth, not from a DB password row.

### Database initialization (Option A — UI-driven, one-time)

- **No** schema changes or data seeding on ordinary application startup.
- **No** pipeline/job requirement for operators to run setup.
- After first successful login as bootstrap admin, redirect to `/setup` until initialization completes.
- Initialization is triggered manually via the setup page (and matching API).
- Once initialized, the setup flow **never appears again** in normal navigation.
- Direct access to `/setup` after initialization shows an “already completed” page (polite, firm — setup cannot be re-run).
- Setup API returns `409 Conflict` if initialization was already performed.

**What “Initialize PackVault” does (single admin action):**

1. Apply database schema (create tables — only at this moment, not on every start).
2. Record `initialized_at`, `initialized_by` in `system_state`.
3. Import Maven token definitions from current env/config into PostgreSQL (hashes only).
4. Seed minimal RBAC structure (e.g. default groups) — structure only, no full admin UI yet.
5. Store encryption key fingerprint (when encryption is enabled).
6. Redirect to dashboard with success confirmation.

**Before initialization:**

- Application behaves as today: bootstrap admin via env, Maven tokens from env/config.
- PostgreSQL connection must be configured; setup page shows connection status.

**On application startup (read-only checks only):**

- If `initialized=true` and database is unreachable or schema is missing → fail fast with a clear ops message.
- If `initialized=false` → serve app normally; env auth works.
- **Never** run DDL or seed data automatically on start.

### Maven tokens (this batch vs future)

**This batch:** No change. Tokens continue to be defined via environment variables / YAML config (`PACKVAULT_CI_TOKEN_HASH`, `PACKVAULT_READER_TOKEN_HASH`, etc.). After initialization, token definitions are **also** stored in PostgreSQL for persistence, but env/config remains the source for bootstrap import and runtime fallback behavior is unchanged from an operator perspective.

**Future (not this batch):** Tokens become app-managed features. Initial pair equivalent to today’s CI publisher and reader tokens. Environment variables for token hashes will be removed. Schema and encryption plumbing built now should accommodate this without a breaking redesign.

### Encryption at rest (opt-in, secret fields only)

Encryption is controlled by configuration, not hard-coded for all environments.

```yaml
secrets:
  encrypt_at_rest: false   # typical for local dev
  # encrypt_at_rest: true  # recommended for production

  encryption_key:
    provider: environment   # environment | aws_secrets_manager

    environment:
      variable: PACKVAULT_SECRETS_ENCRYPTION_KEY

    aws_secrets_manager:
      secret_id: packvault/prod/encryption-key
      region: us-east-1
      # optional: version_id or version_stage
```

**Encrypted when `encrypt_at_rest: true`:**

| Field | Notes |
|-------|-------|
| `token_hash` (DB-stored Maven tokens) | SHA-256 hashes |
| `password_hash` (future local users) | Argon2 hashes — bootstrap admin excluded (env-only) |

**Not encrypted:**

- Usernames, subjects (login lookup)
- Repository names, group names, permission structure
- System flags (`initialized`, timestamps)
- Audit metadata

**Key handling:**

- Master key loaded at startup from configured provider (env var or AWS Secrets Manager via existing AWS credential chain).
- Key is **never** stored in PostgreSQL.
- Key fingerprint stored in `system_state` for mismatch detection on restart.
- When `encrypt_at_rest: true` and key is missing → fail fast at startup with clear message.

**Decrypt failure → reset, not catastrophe:**

- Wrong key or corrupted ciphertext marks affected row with `secret_status: decrypt_failed`.
- Application continues running; bootstrap admin (env) remains available.
- Affected tokens/users must be re-provisioned (re-import from env, reset password, delete and recreate).
- Setup/init UI and future admin surfaces can surface “needs re-provisioning” state.

**Initialization screen (when encryption enabled):**

- Explain that encryption is active and key must be available via configured provider.
- For `environment` provider: verify env var is set; warn explicitly to keep key safe — loss means secret fields must be reset.
- For `aws_secrets_manager` provider: show configured `secret_id` and connection status.

### Metrics (port 9090)

- Main application remains on port **8080** (UI, auth, Maven API, health probes).
- Dedicated listener on port **9090** serves **only** `/metrics`.
- Remove `/metrics` from the main application port.
- Health probes (`/livez`, `/readyz`, `/startupz`) stay on **8080** for Kubernetes/Docker compatibility.
- Docker Compose and Helm updated to expose/document port 9090 for Prometheus scraping.
- Operators should firewall 9090 to monitoring networks only.

### UI error handling

| Request type | Error format |
|--------------|--------------|
| Maven API (`/releases/...`, etc.) | JSON (required for Gradle/Maven clients) |
| Browser UI (HTML pages and forms) | Friendly HTML message + reference ID |

Rules:

- No raw JSON, stack traces, or internal details in the UI.
- Every error logged server-side with `request_id`, route, user (if any), and exception detail.
- UI displays a short, safe message and **Reference: `<request_id>`** for log correlation.
- Reusable error page template for unexpected failures; inline banners for form-level errors.

### Auth pages

| Route / flow | Behavior |
|--------------|----------|
| Failed login | `POST /login` failure → redirect to `/login` with friendly message + reference ID (not JSON) |
| Logout | Clear session cookie → redirect to `/logged-out` |
| Logged out | Confirmation page with link back to sign-in |
| Google OAuth failures | Redirect to `/login` with appropriate error (same pattern as local login) |

All pages reuse existing dark theme and `app.css`.

### Artifact management (UI)

Session-authenticated operator feature — **not** exposed on Maven repository URLs.

| Capability | Detail |
|------------|--------|
| List | Objects under a repository prefix with pagination |
| Search | Path prefix filter (e.g. `com/example/myapp`) |
| Delete | Single object via **POST** with confirmation dialog |
| Default view | Hides checksum sidecars (`.sha1`, `.md5`, `.asc`) and `maven-metadata.xml`; optional toggle to show all |
| Auth | Session required; same as dashboard access in this batch |
| Maven API | Unchanged — GET/HEAD/PUT only; no DELETE on Maven paths |

Storage layer changes:

- Extend `list_prefix` with pagination (continuation token for S3; cursor for local).
- Add `delete(key)` to local, S3, and cached storage backends.
- Audit log entry on delete (includes `request_id`; no secrets).

UI placement: `/artifacts` linked from dashboard header (`Dashboard | Artifacts | Logout`).

---

## PostgreSQL schema (initial)

Tables created during initialization (not on app startup):

| Table | Purpose |
|-------|---------|
| `system_state` | `initialized`, `initialized_at`, `initialized_by`, encryption key fingerprint |
| `users` | SSO and future local users; **no bootstrap admin password** |
| `groups` | Permission boundary containers |
| `user_groups` | Many-to-many membership |
| `group_permissions` | Repository + action (`read`, `write`) per group |
| `tokens` | Maven token metadata and hashes |
| `token_permissions` | Repository + action scopes per token |

Bootstrap admin may optionally have a `users` row for audit/group linkage with **no** `password_hash`, or be recognized purely from env session identity — implementation will favor minimal DB coupling for bootstrap admin.

---

## Configuration and deployment touchpoints

### New / updated configuration

```yaml
database:
  url: ${env.PACKVAULT_DATABASE_URL}   # PostgreSQL connection string

secrets:
  encrypt_at_rest: false
  encryption_key:
    provider: environment
    environment:
      variable: PACKVAULT_SECRETS_ENCRYPTION_KEY
    aws_secrets_manager:
      secret_id: ""
      region: us-east-1

server:
  port: 8080
  metrics_port: 9090
  # ... existing fields unchanged
```

### Environment variables (additions)

| Variable | Purpose |
|----------|---------|
| `PACKVAULT_DATABASE_URL` | PostgreSQL connection string |
| `PACKVAULT_SECRETS_ENCRYPTION_KEY` | Master key when `encrypt_at_rest: true` and provider is `environment` |
| `PACKVAULT_LOCAL_ADMIN_USERNAME` | Bootstrap admin (unchanged) |
| `PACKVAULT_LOCAL_ADMIN_PASSWORD_HASH` | Bootstrap admin Argon2 hash (unchanged, never in DB) |
| `PACKVAULT_CI_TOKEN_HASH` / `PACKVAULT_READER_TOKEN_HASH` | Maven tokens (unchanged this batch) |

### Files / areas to update

- `docker-compose.yaml` — add PostgreSQL service, database env vars, port 9090 mapping.
- `env.example` — document new variables.
- `config/dev.yaml` — database and secrets sections with dev-friendly defaults (`encrypt_at_rest: false`).
- `charts/packvault/` — metrics port on Service; PostgreSQL config; no init Job (setup is UI-driven).
- `docs/operations.md` / `docs/configuration.md` — setup flow, encryption, metrics port, bootstrap admin recovery.
- `pyproject.toml` — add dependencies (SQLAlchemy/async driver, Alembic, cryptography; AWS SDK already present for S3).

### Dependencies (expected additions)

- SQLAlchemy 2.x + async PostgreSQL driver (e.g. `asyncpg`)
- Alembic (migrations invoked from setup initialize, not app startup)
- `cryptography` (AES-GCM field encryption)

---

## Explicitly out of scope (this batch)

- App-managed token creation UI (future: CI + reader tokens without env vars)
- User, group, or token administration UI beyond setup initialize
- SSO auto-provisioning and group mapping rules
- Local user creation (non-bootstrap)
- DELETE on Maven API paths
- Bulk / version-directory delete
- Group-based UI permission enforcement (schema ready; enforcement comes with admin UI)
- Key rotation / re-encryption tooling (design allows it later)
- Additional secret managers beyond env and AWS Secrets Manager

---

## Testing approach

- Unit tests for encryption round-trip, decrypt-failure flagging, and key fingerprint mismatch.
- Integration tests for setup initialize (once), setup revisit (409 / already completed page).
- Auth page tests (failed login redirect, not JSON).
- Metrics port availability and absence of `/metrics` on 8080.
- Storage list pagination and delete (local backend at minimum).
- Artifact UI routes require session; delete emits audit log.
- Existing Maven API and health probe tests remain green.

---

## Approval

After review:

- Request modifications by commenting on specific sections, or
- Approve with **“go”** — then set **Approved** to `Yes` in the status table at the top and start todo **1.1**.

---

*Design agreed in conversation prior to implementation. Todos added for multi-session continuity.*
