# Operations

## Local Docker Compose workflow

PackVault's Docker Compose setup starts:

```text
packvault
packvault-minio
packvault-minio-init
```

MinIO runs even when PackVault is using local disk mode. This keeps the local development workflow simple.

Choose the PackVault backend by changing `PACKVAULT_CONFIG_FILE` in `.env`.

### Local disk mode

```env
PACKVAULT_CONFIG_FILE=./config/dev.yaml
```

Run:

```bash
docker compose up --build
```

### S3 / MinIO mode

```env
PACKVAULT_CONFIG_FILE=./config/dev-s3.yaml
```

Run:

```bash
docker compose up --build
```

MinIO console is available at:

```text
http://localhost:9001
```

Default local credentials are:

```text
minioadmin / minioadmin
```

These are acceptable for local development only. Change them in `.env` for anything else.

## Health endpoints

| Endpoint    | Kubernetes probe  | Purpose                               |
|-------------|-------------------|---------------------------------------|
| `/startupz` | `startupProbe`    | one-time startup completed            |
| `/livez`    | `livenessProbe`   | process is alive; no dependency I/O   |
| `/readyz`   | `readinessProbe`  | safe to serve traffic; checks storage |
| `/metrics`  | Prometheus scrape | metrics endpoint                      |

Responses use:

| State               |  HTTP |
|---------------------|------:|
| healthy             | `200` |
| unhealthy/not ready | `503` |

Example:

```bash
curl -i http://localhost:8080/livez
curl -i http://localhost:8080/startupz
curl -i http://localhost:8080/readyz
```

Expected healthy responses:

```json
{"status":"ok"}
```

```json
{"status":"started"}
```

```json
{"status":"ready"}
```

## Typical runtime behavior

| Condition                | `/livez` | `/startupz` | `/readyz` |
|--------------------------|---------:|------------:|----------:|
| process running normally |    `200` |       `200` |     `200` |
| startup not complete     |    `200` |       `503` |     `503` |
| storage unavailable      |    `200` |       `200` |     `503` |
| shutting down            |    `503` |       `200` |     `503` |

A temporary S3 or MinIO issue should make `/readyz` fail, but should not cause liveness restarts.

## Metrics

Prometheus metrics are exposed at:

```text
/metrics
```

Example:

```bash
curl http://localhost:8080/metrics
```

Current metric families include:

```text
maven_requests_total
maven_request_duration_seconds
maven_storage_operations_total
maven_storage_operation_errors_total
maven_auth_failures_total
maven_upload_bytes_total
maven_download_bytes_total
```

## Basic artifact validation

Set raw token values in your shell:

```bash
export PACKVAULT_CI_TOKEN_RAW='<raw-ci-token>'
export PACKVAULT_READER_TOKEN_RAW='<raw-reader-token>'
```

Upload to releases:

```bash
echo "hello packvault" > /tmp/test-0.1.0.txt

curl -i \
  -u "ci-publisher:${PACKVAULT_CI_TOKEN_RAW}" \
  -X PUT \
  --data-binary @/tmp/test-0.1.0.txt \
  http://localhost:8080/releases/com/rtifact/test/0.1.0/test-0.1.0.txt
```

Expected:

```text
HTTP/1.1 201 Created
```

Download:

```bash
curl -i \
  -u "app-reader:${PACKVAULT_READER_TOKEN_RAW}" \
  http://localhost:8080/releases/com/rtifact/test/0.1.0/test-0.1.0.txt
```

Expected:

```text
HTTP/1.1 200 OK
hello packvault
```

Upload the same release again:

```bash
curl -i \
  -u "ci-publisher:${PACKVAULT_CI_TOKEN_RAW}" \
  -X PUT \
  --data-binary @/tmp/test-0.1.0.txt \
  http://localhost:8080/releases/com/rtifact/test/0.1.0/test-0.1.0.txt
```

Expected:

```text
HTTP/1.1 409 Conflict
```

Snapshot overwrite test:

```bash
echo "snapshot v1" > /tmp/test-0.1.0-SNAPSHOT.txt

curl -i \
  -u "ci-publisher:${PACKVAULT_CI_TOKEN_RAW}" \
  -X PUT \
  --data-binary @/tmp/test-0.1.0-SNAPSHOT.txt \
  http://localhost:8080/snapshots/com/rtifact/test/0.1.0-SNAPSHOT/test-0.1.0-SNAPSHOT.txt

echo "snapshot v2" > /tmp/test-0.1.0-SNAPSHOT.txt

curl -i \
  -u "ci-publisher:${PACKVAULT_CI_TOKEN_RAW}" \
  -X PUT \
  --data-binary @/tmp/test-0.1.0-SNAPSHOT.txt \
  http://localhost:8080/snapshots/com/rtifact/test/0.1.0-SNAPSHOT/test-0.1.0-SNAPSHOT.txt
```

Expected both times:

```text
HTTP/1.1 201 Created
```

## Logs

Default logs are JSON to stdout.

Write attempts emit audit entries like:

```json
{
  "logger": "packvault.audit",
  "message": "artifact_write",
  "repository": "releases",
  "path": "com/rtifact/test/0.1.0/test-0.1.0.txt",
  "principal": "ci-publisher",
  "status_code": 201,
  "bytes_uploaded": 16
}
```

Do not log raw tokens, passwords, cookies, authorization headers, or client secrets.

## Shutdown

Stop local Compose:

```bash
docker compose down
```

Remove volumes too:

```bash
docker compose down -v
```

`down -v` deletes local artifact data, cache, and MinIO data.
