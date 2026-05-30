# Operations

Operator-focused notes for running PackVault day to day: local Compose, database setup, health and metrics, encryption, and recovery.

## Local Docker Compose workflow

PackVault's Docker Compose setup starts:

```text
packvault-postgres
packvault-localstack
packvault-localstack-init
packvault
```

- **PostgreSQL** stores application metadata (setup state, tokens, RBAC).
- **LocalStack** emulates AWS **S3** (artifact storage) and **Secrets Manager** (encryption master key).
- **localstack-init** creates the artifact bucket and encryption-key secret before PackVault starts.

Default config: `config/dev-localstack.yaml` (S3 + Secrets Manager via LocalStack).

Choose a different PackVault profile by setting `PACKVAULT_CONFIG` in `.env`.

### LocalStack mode (default)

```env
PACKVAULT_CONFIG=/config/dev-localstack.yaml
```

Run:

```bash
docker compose up --build
```

This uses:

- S3-compatible storage at `http://localstack:4566`
- Secrets Manager at the same endpoint for `encrypt_at_rest`
- PostgreSQL for the setup wizard and persistence

LocalStack health and resources:

```text
http://localhost:4566/_localstack/health
```

Default LocalStack credentials (conventional, not secret):

```text
test / test
```

### Local disk mode (no S3)

For lightweight runs without S3-backed storage (LocalStack still starts, but PackVault ignores it):

```env
PACKVAULT_CONFIG=/config/dev.yaml
```

Run:

```bash
docker compose up --build
```

Artifacts are stored on the `packvault-data` volume under `/data/maven`.

Compose exposes two application ports on the PackVault container:

| Port | Purpose |
|------|---------|
| `8080` | Main application (UI, auth, Maven API, `/ping`) |
| `9090` | Operations (health probes, Prometheus `/metrics`) |

Set host mappings with `PACKVAULT_HOST_PORT` and `PACKVAULT_OPS_PORT` in `.env` if needed.

## Database and one-time setup

PackVault does **not** apply schema changes or seed data on ordinary startup. Initialization is a deliberate, one-time action performed by the bootstrap platform admin through the UI.

### Prerequisites

1. Configure `database.url` (env: `PACKVAULT_DATABASE_URL`) so PackVault can reach PostgreSQL.
2. Sign in as the **bootstrap platform admin** (credentials from environment only; see [Bootstrap admin recovery](#bootstrap-platform-admin-recovery)).
3. On first login, you are redirected to `/setup` until initialization completes.

### Setup page (`/setup`)

The setup page shows:

- PostgreSQL connection status
- Whether encryption at rest is enabled and whether the master key is available
- How many Maven tokens from config will be imported (hashes only)

Only the bootstrap admin can open the setup flow. Other signed-in users receive forbidden if they try.

### Initialize PackVault

Click **Initialize PackVault** (or call `POST /admin/setup/initialize` with a session cookie). A single action:

1. Runs Alembic migrations (`upgrade head`) if tables are not present yet.
2. Writes `system_state` (`initialized`, `initialized_at`, `initialized_by`, encryption key fingerprint when applicable).
3. Seeds default groups (`publishers`, `readers`) and group permissions.
4. Imports Maven token definitions from current config/env into PostgreSQL (hashed values only; encrypted when `secrets.encrypt_at_rest` is true).
5. Redirects to the dashboard with success confirmation.

After initialization:

- `/setup` shows an “already completed” page if visited again.
- `POST /admin/setup/initialize` returns **409 Conflict** if initialization was already performed.
- Normal navigation no longer offers setup.

### Before initialization

- Env-based bootstrap admin login and Maven tokens from config/env work as today.
- PostgreSQL must be reachable for setup; the app can start with an empty database awaiting setup.

### Startup behavior (read-only checks)

On boot, PackVault **never** runs DDL or seeds data automatically.

| State | Behavior |
|-------|----------|
| Not initialized | App serves normally; env auth and config tokens work; setup available to bootstrap admin. |
| Initialized, DB unreachable or schema missing | Process fails fast with a clear ops error. |
| Initialized, encryption enabled, key fingerprint mismatch | Fail fast — verify `PACKVAULT_SECRETS_ENCRYPTION_KEY` or the configured AWS Secrets Manager secret. |

## Bootstrap platform admin recovery

The bootstrap platform admin is **never** stored in PostgreSQL. Credentials always come from environment / config substitution:

| Item | Source |
|------|--------|
| Username | `PACKVAULT_LOCAL_ADMIN_USERNAME` |
| Password | `PACKVAULT_LOCAL_ADMIN_PASSWORD_HASH` (Argon2 hash, not plaintext) |

If you lose admin access:

1. Generate a new Argon2 hash:

   ```bash
   python scripts/hash_password.py 'your-new-password'
   ```

2. Update `PACKVAULT_LOCAL_ADMIN_PASSWORD_HASH` in your deployment (`.env`, Kubernetes Secret, etc.).
3. Restart PackVault.

No database surgery is required. The bootstrap admin retains platform privileges via session identity from env auth, not from a DB password row.

## Encryption at rest

Encryption is **opt-in** via `secrets.encrypt_at_rest` in config. When disabled (typical local dev), secret fields are stored as provided. When enabled, selected fields are encrypted with AES-GCM using a master key that is **never** stored in PostgreSQL.

### What is encrypted

| Field | When enabled |
|-------|----------------|
| `tokens.token_hash` | SHA-256 hashes imported at setup |
| Future `users.password_hash` | Argon2 hashes (bootstrap admin excluded) |

Usernames, repository names, group structure, audit metadata, and system flags are not encrypted.

### Key providers

| Provider | Configuration | Master key source |
|----------|---------------|-------------------|
| `environment` | `secrets.encryption_key.environment.variable` | Env var (e.g. `PACKVAULT_SECRETS_ENCRYPTION_KEY`) |
| `aws_secrets_manager` | `secret_id`, `region`, optional `endpoint_url` | AWS Secrets Manager via standard credential chain |

At initialization, PackVault records a **key fingerprint** in `system_state`. On later startups, a mismatch fails fast so operators detect a wrong or rotated key early.

### Decrypt failures

If the wrong key is used or ciphertext is corrupted, affected rows are marked `secret_status: decrypt_failed`. The application keeps running; bootstrap admin (env) remains available. Affected tokens must be re-provisioned (re-run setup is not possible — update token hashes in env and fix rows operationally, or plan a controlled DB reset in non-production).

The setup page surfaces whether the key is reachable when encryption is enabled.

### LocalStack dev profile

`config/dev-localstack.yaml` sets `encryptAtRest: true` with provider `aws_secrets_manager` pointing at LocalStack. `scripts/localstack-init.sh` seeds the secret; `PACKVAULT_SECRETS_ENCRYPTION_KEY` in `.env` is used when testing the environment provider locally.

## Health endpoints

Health and readiness probes are served only on the **operations port** (`server.operations_port`, default **9090**). They are **not** available on the main application port (`8080`).

| Endpoint    | Kubernetes probe  | Purpose                               |
|-------------|-------------------|---------------------------------------|
| `/startupz` | `startupProbe`    | One-time startup completed            |
| `/livez`    | `livenessProbe`   | Process is alive; no dependency I/O   |
| `/readyz`   | `readinessProbe`  | Safe to serve traffic; checks storage |
| `/metrics`  | Prometheus scrape | Prometheus metrics                    |

The Helm chart sets `probes.port: ops` so probes target the operations Service port.

Responses use:

| State               | HTTP |
|---------------------|-----:|
| healthy             | `200` |
| unhealthy/not ready | `503` |

Examples (Docker Compose defaults):

```bash
curl -i http://localhost:9090/livez
curl -i http://localhost:9090/startupz
curl -i http://localhost:9090/readyz
```

Expected healthy JSON bodies:

```json
{"status":"ok"}
```

```json
{"status":"started"}
```

```json
{"status":"ready"}
```

Public reachability on the main port (no storage check):

```bash
curl -i http://localhost:8080/ping
```

## Typical runtime behavior

| Condition                | `/livez` | `/startupz` | `/readyz` |
|--------------------------|---------:|------------:|----------:|
| process running normally |    `200` |       `200` |     `200` |
| startup not complete     |    `200` |       `503` |     `503` |
| storage unavailable      |    `200` |       `200` |     `503` |
| shutting down            |    `503` |       `200` |     `503` |

A temporary S3 or storage issue should make `/readyz` fail without necessarily failing `/livez` (avoid unnecessary liveness restarts).

## Metrics

Prometheus metrics are exposed **only** on the operations port:

```text
http://<host>:9090/metrics
```

Example:

```bash
curl http://localhost:9090/metrics
```

`GET /metrics` on port `8080` returns **404**.

Current metric families include:

```text
packvault_http_requests_total
packvault_http_request_duration_seconds
```

**Network exposure:** Restrict port `9090` to your monitoring network (firewall, Kubernetes NetworkPolicy, or internal Service only). The main port carries UI and Maven traffic and should remain reachable to clients as designed.

## Artifact management (UI)

Session-authenticated operators can list, search, and delete stored objects at `/artifacts` (linked from the dashboard header). This is separate from the Maven API (no `DELETE` on repository paths). Deletes are confirmed in the UI, emit an audit log line with `request_id`, and require the same session access as the dashboard.

Default listing hides checksum sidecars (`.sha1`, `.md5`, `.asc`) and `maven-metadata.xml`; use **Show all** to include them.

## Shutdown

Stop local Compose:

```bash
docker compose down
```

Remove volumes too:

```bash
docker compose down -v
```

`down -v` deletes local artifact data, cache, LocalStack state, and PostgreSQL data.
