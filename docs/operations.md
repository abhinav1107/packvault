# Operations

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

A temporary S3 or LocalStack issue should make `/readyz` fail, but should not cause liveness restarts.

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
packvault_http_requests_total
packvault_http_request_duration_seconds
```

Metrics are served on the operations port (`9090` by default), not the main application port.

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
