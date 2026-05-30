# Configuration

PackVault is configured with a YAML file. The active file is selected with:

```bash
export PACKVAULT_CONFIG=/path/to/config.yaml
```

With Docker Compose, the container typically uses a path under `/config` (host `./config` is mounted read-only). See [`env.example`](../env.example) and [`config/dev.yaml`](../config/dev.yaml) / [`config/dev-localstack.yaml`](../config/dev-localstack.yaml) for working examples.

Runtime overrides use Pydantic settings with prefix `PACKVAULT_` and nested delimiter `__` (for example `PACKVAULT_SERVER__OPERATIONS_PORT=9090`).

For setup, health ports, and encryption operations, see [operations.md](operations.md).

## Environment variable substitution in YAML

Any **string value** in the YAML file may reference an environment variable:

```yaml
server:
  sessionSecret: "${env.PACKVAULT_SESSION_SECRET}"
database:
  url: "${env.PACKVAULT_DATABASE_URL}"
```

Syntax: `${env.VAR_NAME}` where `VAR_NAME` matches `[A-Za-z_][A-Za-z0-9_]*`.

Substitution runs when the config file is loaded, before validation. If a referenced variable is **not set**, PackVault fails to start with a clear error.

You can embed references inside a larger string:

```yaml
server:
  publicUrl: "https://${env.PACKVAULT_PUBLIC_HOST}"
```

### When to use `${env.*}` vs `PACKVAULT_*` overrides

| Mechanism              | Best for                                                                                                                             |
|------------------------|--------------------------------------------------------------------------------------------------------------------------------------|
| `${env.VAR}` in YAML   | Secrets and values injected by Kubernetes/Docker (`secretKeyRef`, `envFrom`) without duplicating key names in a second naming scheme |
| `PACKVAULT_*` env vars | Overriding individual settings without editing YAML (nested keys, e.g. `PACKVAULT_SERVER__PORT=8080`)                                |

Both can be used together. Only PackVault’s YAML loader understands `${env.NAME}`; Maven `settings.xml` uses its own syntax.

## Configuration reference

YAML keys may use **camelCase** in files; they map to snake_case internally. Below, YAML names are shown as in the repo configs.

### `server`

| YAML key | Env override (nested) | Default | Description |
|----------|----------------------|---------|-------------|
| `host` | `PACKVAULT_SERVER__HOST` | `0.0.0.0` | Bind address |
| `port` | `PACKVAULT_SERVER__PORT` | `8080` | Main application port (UI, auth, Maven API, `/ping`) |
| `operationsPort` | `PACKVAULT_SERVER__OPERATIONS_PORT` | `9090` | Operations port (`/livez`, `/readyz`, `/startupz`, `/metrics` only) |
| `publicUrl` | `PACKVAULT_SERVER__PUBLIC_URL` | `http://localhost:{port}` | External URL for redirects and links |
| `sessionSecret` | `PACKVAULT_SERVER__SESSION_SECRET` | (required) | Browser session signing secret |
| `maxUploadBytes` | `PACKVAULT_SERVER__MAX_UPLOAD_BYTES` | `524288000` | Max Maven PUT body size |
| `requestTimeoutSeconds` | `PACKVAULT_SERVER__REQUEST_TIMEOUT_SECONDS` | `300` | HTTP request timeout |
| `pingRateLimitPerMinute` | `PACKVAULT_SERVER__PING_RATE_LIMIT_PER_MINUTE` | `10` | Rate limit for `/ping` |

Example:

```yaml
server:
  host: 0.0.0.0
  port: 8080
  operationsPort: 9090
  publicUrl: ${env.PACKVAULT_PUBLIC_URL}
  sessionSecret: ${env.PACKVAULT_SESSION_SECRET}
  maxUploadBytes: ${env.PACKVAULT_MAX_UPLOAD_BYTES}
  requestTimeoutSeconds: ${env.PACKVAULT_REQUEST_TIMEOUT_SECONDS}
```

Health probes and Prometheus scraping must target **`operationsPort`**, not `port`. The main port returns **404** for `/metrics` and probe paths.

### `database`

| YAML key | Env override | Default | Description |
|----------|--------------|---------|-------------|
| `url` | `PACKVAULT_DATABASE__URL` or `PACKVAULT_DATABASE_URL` | `""` (empty) | Async SQLAlchemy URL, e.g. `postgresql+asyncpg://user:pass@host:5432/packvault` |

When `url` is empty, PostgreSQL features (setup wizard, persisted tokens) are disabled. Production and Docker Compose installs should set `PACKVAULT_DATABASE_URL`.

Example:

```yaml
database:
  url: ${env.PACKVAULT_DATABASE_URL}
```

Schema is applied only during [one-time setup](operations.md#database-and-one-time-setup), not on every application start. For upgrades after initialization, see [Upgrading PackVault](operations.md#upgrading-packvault).

### `secrets`

Controls optional encryption of secret fields stored in PostgreSQL (token hashes; future local user password hashes). The master key is **never** stored in the database.

| YAML key | Env override | Default | Description |
|----------|--------------|---------|-------------|
| `encryptAtRest` | `PACKVAULT_SECRETS__ENCRYPT_AT_REST` | `false` | Enable AES-GCM field encryption |
| `encryptionKey.provider` | `PACKVAULT_SECRETS__ENCRYPTION_KEY__PROVIDER` | `environment` | `environment` or `aws_secrets_manager` |
| `encryptionKey.environment.variable` | — | `PACKVAULT_SECRETS_ENCRYPTION_KEY` | Env var name when provider is `environment` |
| `encryptionKey.awsSecretsManager.secretId` | — | `""` | Secrets Manager secret id |
| `encryptionKey.awsSecretsManager.region` | — | `us-east-1` | AWS region |
| `encryptionKey.awsSecretsManager.endpointUrl` | — | `""` | Optional custom endpoint (e.g. LocalStack) |
| `encryptionKey.awsSecretsManager.versionId` | — | `""` | Optional secret version id |
| `encryptionKey.awsSecretsManager.versionStage` | — | `""` | Optional version stage |

Example (local dev, encryption off):

```yaml
secrets:
  encryptAtRest: false
  encryptionKey:
    provider: environment
    environment:
      variable: PACKVAULT_SECRETS_ENCRYPTION_KEY
```

Example (production-style, AWS Secrets Manager):

```yaml
secrets:
  encryptAtRest: true
  encryptionKey:
    provider: aws_secrets_manager
    awsSecretsManager:
      secretId: packvault/prod/encryption-key
      region: us-east-1
```

When `encryptAtRest` is `true`, the master key must be available at startup. A fingerprint recorded at setup is checked on later boots. See [operations.md — Encryption at rest](operations.md#encryption-at-rest).

### `storage`

| Backend | YAML | Notes |
|---------|------|-------|
| `local` | `storage.backend: local`, `storage.local.root` | Single-server; path is source of truth |
| `s3` | `storage.backend: s3`, `storage.s3.*`, optional `storage.cache.*` | S3-compatible object store; local cache disposable |

Local:

```yaml
storage:
  backend: local
  local:
    root: ${env.PACKVAULT_LOCAL_ROOT}
```

S3:

```yaml
storage:
  backend: s3
  s3:
    endpointUrl: ${env.PACKVAULT_S3_ENDPOINT_URL}
    bucket: ${env.PACKVAULT_S3_BUCKET}
    region: ${env.PACKVAULT_AWS_REGION}
    pathStyle: ${env.PACKVAULT_S3_PATH_STYLE}
    prefix: ${env.PACKVAULT_S3_PREFIX}
  cache:
    path: ${env.PACKVAULT_CACHE_PATH}
    metadataTtlSeconds: ${env.PACKVAULT_CACHE_METADATA_TTL_SECONDS}
    snapshotTtlSeconds: ${env.PACKVAULT_CACHE_SNAPSHOT_TTL_SECONDS}
```

Object keys: `<prefix>/<repositoryName>/<mavenPath>` (default prefix `repositories`). Local layout: `<root>/<repositoryName>/<mavenPath>`.

### `auth`

| Area | YAML | Notes |
|------|------|-------|
| Providers | `auth.providers` | `local`, `google`, `oidc` |
| Bootstrap admin | `auth.local.username`, `auth.local.passwordHash` | **Env only** — never stored in PostgreSQL |
| Maven tokens | `auth.tokens[]` | `name`, `tokenHash`, `permissions`, optional `expiresAt` |

Bootstrap admin example:

```yaml
auth:
  providers:
    - local
  local:
    username: ${env.PACKVAULT_LOCAL_ADMIN_USERNAME}
    passwordHash: ${env.PACKVAULT_LOCAL_ADMIN_PASSWORD_HASH}
```

Maven token example (hash in config, raw secret in clients):

```yaml
  tokens:
    - name: ${env.PACKVAULT_CI_TOKEN_NAME}
      tokenHash: ${env.PACKVAULT_CI_TOKEN_HASH}
      expiresAt: null
      permissions:
        - repository: releases
          actions:
            - read
            - write
```

After [database initialization](operations.md#initialize-packvault), token definitions are copied into PostgreSQL (encrypted when `encryptAtRest` is true). Env/config remains the source for the bootstrap import in this release.

Generate hashes:

```bash
python scripts/hash_password.py '<password>'
python scripts/hash_token.py '<raw-token>'
```

### `repositories`

```yaml
repositories:
  - name: releases
    allowOverwrite: false
  - name: snapshots
    allowOverwrite: true
```

| Repository  | `allowOverwrite` | Meaning |
|-------------|-----------------:|---------|
| `releases`  | `false` | Immutable release artifacts (`409` if object exists) |
| `snapshots` | `true` | Mutable snapshot artifacts |

### `security`

```yaml
security:
  anonymousRead: ${env.PACKVAULT_ANONYMOUS_READ}
```

When `anonymousRead` is `false` (default), Maven reads require a valid token (or session for UI-only routes).

### `logging`

| Setting | Env (flat or nested) | CLI flag | Default |
|---------|----------------------|----------|---------|
| Level | `PACKVAULT_LOG_LEVEL`, `PACKVAULT_LOGGING__LEVEL` | `--log-level` | `INFO` |
| Format | `PACKVAULT_LOG_FORMAT`, `PACKVAULT_LOGGING__FORMAT` | `--log-format` | `json` |

Precedence: **CLI > environment variable > YAML > default**.

```yaml
logging:
  level: ${env.PACKVAULT_LOG_LEVEL}
  format: ${env.PACKVAULT_LOG_FORMAT}
```

Formats: `json` (structured, production) or `standard` (human-readable). Audit events use logger `packvault.audit` and never include secrets.

## Environment variables

### Required for a typical install

| Variable | Purpose |
|----------|---------|
| `PACKVAULT_CONFIG` | Path to YAML config file |
| `PACKVAULT_SESSION_SECRET` | Session signing secret (generate with `python -c 'import secrets; print(secrets.token_urlsafe(48))'`) |
| `PACKVAULT_LOCAL_ADMIN_PASSWORD_HASH` | Argon2 hash for bootstrap UI admin (when `local` provider enabled) |
| `PACKVAULT_CI_TOKEN_HASH` / others | SHA-256 hashes for configured Maven tokens |
| `PACKVAULT_DATABASE_URL` | PostgreSQL URL when using setup / persistence |

### Bootstrap admin and Maven tokens

| Variable | Purpose |
|----------|---------|
| `PACKVAULT_LOCAL_ADMIN_USERNAME` | Bootstrap admin username (default `admin`) |
| `PACKVAULT_LOCAL_ADMIN_PASSWORD_HASH` | Argon2 password hash (never plaintext) |
| `PACKVAULT_CI_TOKEN_NAME` | Maven token name for CI publisher |
| `PACKVAULT_CI_TOKEN_HASH` | Hash of CI token secret |
| `PACKVAULT_READER_TOKEN_NAME` | Maven token name for reader |
| `PACKVAULT_READER_TOKEN_HASH` | Hash of reader token secret |

### Server and operations

| Variable | Purpose |
|----------|---------|
| `PACKVAULT_PUBLIC_URL` | Public base URL |
| `PACKVAULT_HOST_PORT` | Docker Compose host mapping for main port (default `8080`) |
| `PACKVAULT_OPS_PORT` | Docker Compose host mapping for operations port (default `9090`) |
| `PACKVAULT_ANONYMOUS_READ` | Allow anonymous Maven reads (`true` / `false`) |
| `PACKVAULT_MAX_UPLOAD_BYTES` | Upload size limit |
| `PACKVAULT_REQUEST_TIMEOUT_SECONDS` | Request timeout |

### Database and encryption

| Variable | Purpose |
|----------|---------|
| `PACKVAULT_DATABASE_URL` | `postgresql+asyncpg://...` connection string |
| `PACKVAULT_SECRETS_ENCRYPTION_KEY` | Master key when `encryptAtRest: true` and provider is `environment` |
| `PACKVAULT_SECRETS_MANAGER_SECRET_ID` | LocalStack/AWS secret id (dev-localstack profile) |

### Storage (S3 / local)

| Variable | Purpose |
|----------|---------|
| `PACKVAULT_LOCAL_ROOT` | Local artifact root directory |
| `PACKVAULT_S3_ENDPOINT_URL` | S3 API endpoint |
| `PACKVAULT_S3_BUCKET` | Bucket name |
| `PACKVAULT_S3_PATH_STYLE` | Path-style addressing (`true` / `false`) |
| `PACKVAULT_S3_PREFIX` | Key prefix under bucket |
| `PACKVAULT_AWS_REGION` | AWS region |
| `PACKVAULT_AWS_ENDPOINT_URL` | Optional global AWS endpoint (LocalStack) |
| `PACKVAULT_AWS_ACCESS_KEY_ID` / `PACKVAULT_AWS_SECRET_ACCESS_KEY` | Credentials for S3 and Secrets Manager |
| `PACKVAULT_CACHE_PATH` | Local cache directory (S3 mode) |
| `PACKVAULT_CACHE_METADATA_TTL_SECONDS` | Cache TTL for metadata |
| `PACKVAULT_CACHE_SNAPSHOT_TTL_SECONDS` | Cache TTL for snapshots |

### Optional SSO

| Variable | Purpose |
|----------|---------|
| `PACKVAULT_GOOGLE_CLIENT_ID` / `PACKVAULT_GOOGLE_CLIENT_SECRET` | Google OAuth |
| `PACKVAULT_OIDC_CLIENT_ID` / `PACKVAULT_OIDC_CLIENT_SECRET` | Generic OIDC |

### Logging

| Variable | Purpose |
|----------|---------|
| `PACKVAULT_LOG_LEVEL` | Log level |
| `PACKVAULT_LOG_FORMAT` | `json` or `standard` |

## `.env` and Docker Compose

Copy the template and fill secrets locally:

```bash
cp env.example .env
```

Do not commit `.env`. `docker-compose.yaml` wires non-secret defaults; secret-like values come from `.env` (session secret, password hash, token hashes, optional OAuth secrets).

Choose a dev profile in `.env`:

```env
PACKVAULT_CONFIG=/config/dev-localstack.yaml
# or
PACKVAULT_CONFIG=/config/dev.yaml
```

## Maven repository URL layout

Maven and Gradle clients use a **Nexus-style** path:

```text
https://<host>/<repositoryName>/<mavenPath>
```

Examples:

- `https://packvault.example/releases/com/acme/foo/1.0.0/foo-1.0.0.jar`
- `https://packvault.example/snapshots/com/acme/foo/maven-metadata.xml`

| Part | Meaning |
|------|---------|
| `<repositoryName>` | Configured repository (`releases`, `snapshots`, …) |
| `<mavenPath>` | Standard Maven path: `groupId/as/path/artifact/version/file` |

## Client authentication (Maven / Gradle)

HTTP Basic authentication:

| Field | Value |
|-------|-------|
| Username | Token name (as configured) |
| Password | Raw token secret |

Gradle example:

```kotlin
maven {
    url = uri("https://packvault.example/releases")
    credentials {
        username = "ci-publisher"
        password = findProperty("packvaultToken") as String
    }
}
```

Maven `settings.xml`:

```xml
<server>
  <id>packvault-releases</id>
  <username>ci-publisher</username>
  <password>${env.PACKVAULT_TOKEN}</password>
</server>
```

## Example files

| File | Use case |
|------|----------|
| [`config/dev.yaml`](../config/dev.yaml) | Local disk storage, encryption off |
| [`config/dev-localstack.yaml`](../config/dev-localstack.yaml) | S3 + Secrets Manager via LocalStack, encryption on |
| [`env.example`](../env.example) | Full variable list for Compose |
| [`charts/packvault/values.yaml`](../charts/packvault/values.yaml) | Kubernetes Helm defaults |
