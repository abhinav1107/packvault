# Configuration

PackVault is configured via YAML file and environment variable overrides (`PACKVAULT_` prefix).

## Configuration file

Set the file path with:

```bash
export PACKVAULT_CONFIG=/path/to/config.yaml
```

## Environment variable substitution in YAML

Any **string value** in the YAML file may reference an environment variable:

```yaml
server:
  sessionSecret: "${env.PACKVAULT_SESSION_SECRET}"
auth:
  google:
    clientId: "${env.GOOGLE_CLIENT_ID}"
    clientSecret: "${env.GOOGLE_CLIENT_SECRET}"
```

Syntax: `${env.VAR_NAME}` where `VAR_NAME` matches `[A-Za-z_][A-Za-z0-9_]*`.

Substitution runs when the config file is loaded, before validation. If a referenced variable is **not set**, PackVault fails to start with a clear error (fail-fast for secrets).

You can embed references inside a larger string:

```yaml
server:
  publicUrl: "https://${env.PACKVAULT_PUBLIC_HOST}"
```

### When to use this vs `PACKVAULT_` env overrides

| Mechanism | Best for |
|-----------|----------|
| `${env.VAR}` in YAML | Secrets and values injected by Kubernetes/Docker (`secretKeyRef`, `envFrom`) without duplicating key names in a second naming scheme |
| `PACKVAULT_*` env vars | Overriding individual settings without editing YAML (Pydantic nested keys, e.g. `PACKVAULT_SERVER__PORT=9090`) |

Both can be used together: YAML provides structure; `${env.*}` fills in secrets; `PACKVAULT_*` can still override at runtime.

**Note:** Only PackVault’s YAML config uses `${env.NAME}`. Maven `settings.xml` uses its own `${env.VAR}` syntax independently.

## Maven repository URL layout

Maven and Gradle clients use a **Nexus-style** path:

```
https://<host>/<repositoryName>/<mavenPath>
```

Examples:

- `https://packvault.example/releases/com/acme/foo/1.0.0/foo-1.0.0.jar`
- `https://packvault.example/snapshots/com/acme/foo/maven-metadata.xml`

| Part | Meaning |
|------|---------|
| `<repositoryName>` | Configured repository (`releases`, `snapshots`, …) |
| `<mavenPath>` | Standard Maven path: `groupId/as/path/artifact/version/file` |

Object storage keys mirror this layout:

```
<storage-prefix>/<repositoryName>/<mavenPath>
```

Default storage prefix is `repositories` (S3) or the local root directory contains one folder per repository name.

## Client authentication (Maven / Gradle)

Use **HTTP Basic** authentication:

| Field | Value |
|-------|-------|
| Username | Token name (as configured) |
| Password | Raw token secret (shown once when generated) |

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

Maven `settings.xml` server entry:

```xml
<server>
  <id>packvault-releases</id>
  <username>ci-publisher</username>
  <password>${env.PACKVAULT_TOKEN}</password>
</server>
```

## Logging

PackVault uses the standard library `logging` module with a single root configuration.

| Setting | Env variable | CLI flag | Default |
|---------|--------------|----------|---------|
| Level | `PACKVAULT_LOG_LEVEL` | `--log-level` | `INFO` |
| Format | `PACKVAULT_LOG_FORMAT` | `--log-format` | `json` |

Precedence: **CLI > environment variable > YAML config > default**.

YAML (optional):

```yaml
logging:
  level: INFO
  format: json   # or standard
```

Nested env vars also work: `PACKVAULT_LOGGING__LEVEL`, `PACKVAULT_LOGGING__FORMAT`.

**Levels:** `DEBUG`, `INFO`, `WARN` / `WARNING`, `ERROR`.

**Formats:**

- `json` — structured JSON to stdout (timestamp, level, logger, module, filename, line, message, optional `request_id`). Matches the design doc for production and log aggregation.
- `standard` — human-readable single line for local development.

Every log line includes the **logger name** (typically the Python module path, e.g. `packvault.api.routes_maven`), plus **filename** and **line** number. Request-scoped logs also include `request_id` when handling HTTP traffic.

Audit events (`packvault.audit`) use the same formatters and include write metadata (repository, path, principal, etc.) without secrets.

Examples:

```bash
packvault --log-level DEBUG --log-format standard
PACKVAULT_LOG_LEVEL=ERROR PACKVAULT_LOG_FORMAT=json packvault
```

## Example configuration

See [`config/dev-s3.yaml`](../config/dev-s3.yaml) or [`config/dev.yaml`](../config/dev.yaml) files for references.

# Configuration

PackVault is configured with a YAML file. The YAML file may reference environment variables using PackVault's explicit `${env.VAR_NAME}` syntax.

The active config file is selected with:

```bash
export PACKVAULT_CONFIG=/path/to/config.yaml
```

When running with Docker Compose, the container reads:

```bash
PACKVAULT_CONFIG=/config/config.yaml
```

`docker-compose.yaml` mounts one of the local config files into that container path.

## Local development config files

The repository includes two development config files:

```text
config/dev.yaml
config/dev-s3.yaml
```

Use `PACKVAULT_CONFIG_FILE` in `.env` to choose which one Docker Compose mounts:

```env
PACKVAULT_CONFIG_FILE=./config/dev.yaml
```

or:

```env
PACKVAULT_CONFIG_FILE=./config/dev-s3.yaml
```

### Local backend

```yaml
storage:
  backend: local
  local:
    root: ${env.PACKVAULT_LOCAL_ROOT}
```

Local backend means:

- local disk is the source of truth
- suitable for single-server development
- not safe for multiple independent replicas

### S3 backend

```yaml
storage:
  backend: s3
  s3:
    endpointUrl: ${env.PACKVAULT_S3_ENDPOINT_URL}
    bucket: ${env.PACKVAULT_S3_BUCKET}
    region: ${env.PACKVAULT_S3_REGION}
    pathStyle: ${env.PACKVAULT_S3_PATH_STYLE}
    prefix: ${env.PACKVAULT_S3_PREFIX}
  cache:
    path: ${env.PACKVAULT_CACHE_PATH}
    metadataTtlSeconds: ${env.PACKVAULT_CACHE_METADATA_TTL_SECONDS}
    snapshotTtlSeconds: ${env.PACKVAULT_CACHE_SNAPSHOT_TTL_SECONDS}
```

S3 backend means:

- S3-compatible object storage is the source of truth
- app replicas can be stateless for artifact persistence
- local cache is optional and disposable
- MinIO can be used for local testing

## Environment variable substitution in YAML

Any string value in the YAML file may reference an environment variable:

```yaml
server:
  sessionSecret: ${env.PACKVAULT_SESSION_SECRET}

auth:
  local:
    passwordHash: ${env.PACKVAULT_LOCAL_ADMIN_PASSWORD_HASH}
```

Syntax:

```text
${env.VAR_NAME}
```

where `VAR_NAME` matches:

```text
[A-Za-z_][A-Za-z0-9_]*
```

Substitution happens before validation. If a referenced variable is missing, PackVault fails fast during startup.

You can embed references inside a larger string:

```yaml
server:
  publicUrl: https://${env.PACKVAULT_PUBLIC_HOST}
```

Only PackVault's YAML loader handles this syntax. Maven and Gradle have their own environment-variable handling.

## `.env` and `env.example`

Use `env.example` as the template:

```bash
cp env.example .env
```

Then edit `.env` and fill required values:

```env
PACKVAULT_SESSION_SECRET=
PACKVAULT_LOCAL_ADMIN_PASSWORD_HASH=
PACKVAULT_CI_TOKEN_HASH=
PACKVAULT_READER_TOKEN_HASH=
```

Do not commit `.env`.

The repository should commit:

```text
env.example
config/dev.yaml
config/dev-s3.yaml
docker-compose.yaml
```

The repository should not commit:

```text
.env
.env.*
```

## Docker Compose defaults

`docker-compose.yaml` provides safe non-secret defaults for paths, ports, logging, MinIO endpoint, cache path, and upload limits.

Secret-like values should come from `.env`, including:

```text
PACKVAULT_SESSION_SECRET
PACKVAULT_LOCAL_ADMIN_PASSWORD_HASH
PACKVAULT_CI_TOKEN_HASH
PACKVAULT_READER_TOKEN_HASH
PACKVAULT_GOOGLE_CLIENT_SECRET
PACKVAULT_OIDC_CLIENT_SECRET
```

## Maven repository URL layout

PackVault uses a Nexus-style repository URL layout:

```text
https://<host>/<repositoryName>/<mavenPath>
```

Examples:

```text
https://packvault.example/releases/com/acme/foo/1.0.0/foo-1.0.0.jar
https://packvault.example/snapshots/com/acme/foo/1.0.0-SNAPSHOT/foo-1.0.0-SNAPSHOT.jar
```

| Part | Meaning |
|---|---|
| `<repositoryName>` | Configured repository, such as `releases` or `snapshots` |
| `<mavenPath>` | Standard Maven artifact path |

S3 object keys use the configured S3 prefix:

```text
<storage-prefix>/<repositoryName>/<mavenPath>
```

Example:

```text
repositories/releases/com/acme/foo/1.0.0/foo-1.0.0.jar
```

Local storage stores artifacts under:

```text
<local-root>/<repositoryName>/<mavenPath>
```

## Repositories

Example:

```yaml
repositories:
  - name: releases
    allowOverwrite: false

  - name: snapshots
    allowOverwrite: true
```

Recommended defaults:

| Repository | `allowOverwrite` | Meaning |
|---|---:|---|
| `releases` | `false` | immutable release artifacts |
| `snapshots` | `true` | mutable snapshot artifacts |

If overwrite is disabled and an object already exists, PackVault returns:

```text
409 Conflict
```

## Maven / Gradle client authentication

Maven and Gradle clients use HTTP Basic authentication.

| Basic auth field | Value |
|---|---|
| Username | token name |
| Password | raw token secret |

The config stores only the token hash:

```yaml
auth:
  tokens:
    - name: ci-publisher
      tokenHash: ${env.PACKVAULT_CI_TOKEN_HASH}
      permissions:
        - repository: releases
          actions:
            - read
            - write
```

Generate a token hash with:

```bash
python scripts/hash_token.py
```

Use the raw token in Maven or Gradle. Use the hash in config.

## Local UI authentication

Local UI login uses:

```yaml
auth:
  providers:
    - local
  local:
    username: ${env.PACKVAULT_LOCAL_ADMIN_USERNAME}
    passwordHash: ${env.PACKVAULT_LOCAL_ADMIN_PASSWORD_HASH}
```

Generate a password hash with:

```bash
python scripts/hash_password.py
```

## Logging

PackVault supports JSON and standard text logs.

| Setting | Env variable | CLI flag | Default |
|---|---|---|---|
| Level | `PACKVAULT_LOG_LEVEL` | `--log-level` | `INFO` |
| Format | `PACKVAULT_LOG_FORMAT` | `--log-format` | `json` |

Precedence:

```text
CLI > environment variable > YAML config > default
```

YAML:

```yaml
logging:
  level: INFO
  format: json
```

Supported levels:

```text
DEBUG
INFO
WARN
WARNING
ERROR
```

Supported formats:

| Format | Use |
|---|---|
| `json` | structured logs for containers and log aggregation |
| `standard` | human-readable local development logs |

Audit logs are emitted on write attempts through the `packvault.audit` logger. They include repository, path, principal, status code, client IP, user agent, request ID, and uploaded bytes. Secrets are not logged.
