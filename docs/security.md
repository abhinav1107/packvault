# Security defaults

- Anonymous write: never supported
- Anonymous read: disabled by default (`security.anonymousRead: false`)
- DELETE: not supported in v1
- Release repositories: immutable by default (`409 Conflict` on overwrite)
- Maven tokens: stored as SHA-256 hashes only
- Passwords: argon2 hashes only
- Strict Maven path validation (no `..`, encoding tricks, etc.)
- No public directory listing
- Write operations audit-logged (no secrets in logs)

Use HTTPS in production. Terminate TLS at ingress.

# Security

PackVault is intended to be internet-facing, so its defaults are intentionally conservative.

## Current security defaults

| Area | Default |
|---|---|
| Anonymous write | never supported |
| Anonymous read | disabled |
| DELETE | not supported in v1 |
| Release overwrite | blocked by default |
| Snapshot overwrite | allowed by default |
| Maven client auth | HTTP Basic using token name + raw token |
| Token storage | SHA-256 token hashes |
| Local UI password storage | Argon2 password hashes |
| Path validation | strict Maven path validation |
| Directory listing | not supported |
| Write audit logging | enabled |

## Authentication model

PackVault has two separate authentication paths.

### UI authentication

Used for browser access.

Supported or planned providers:

```text
local
google
oidc
```

Local auth uses a username and Argon2 password hash.

### Maven / Gradle authentication

Used by build tools and CI/CD.

Maven and Gradle use HTTP Basic authentication:

| Field | Value |
|---|---|
| Username | token name |
| Password | raw token secret |

PackVault stores only the token hash:

```yaml
auth:
  tokens:
    - name: ci-publisher
      tokenHash: ${env.PACKVAULT_CI_TOKEN_HASH}
```

Do not put raw tokens in config files.

## Token permissions

Tokens are scoped by repository and action.

Example:

```yaml
permissions:
  - repository: releases
    actions:
      - read
      - write
```

Supported actions:

```text
read
write
```

A token without `write` cannot upload artifacts.

A token without `read` cannot download artifacts.

## Secrets

Do not commit real secrets.

Never commit:

```text
.env
.env.local
.env.production
```

Commit only:

```text
env.example
```

Secret-like values include:

```text
PACKVAULT_SESSION_SECRET
PACKVAULT_LOCAL_ADMIN_PASSWORD_HASH
PACKVAULT_CI_TOKEN_HASH
PACKVAULT_READER_TOKEN_HASH
PACKVAULT_GOOGLE_CLIENT_SECRET
PACKVAULT_OIDC_CLIENT_SECRET
AWS_SECRET_ACCESS_KEY
MINIO_ROOT_PASSWORD
```

## Path validation

PackVault validates Maven artifact paths before storage access.

Rejected path classes include:

```text
empty paths
absolute paths
path traversal
segments containing ..
backslashes
drive-letter style paths
query strings
fragments
control characters
empty path segments
disallowed characters
URL-encoded traversal attempts
```

Examples that should be rejected:

```text
../secret
com//acme
com/acme%2e%2e/foo
com/acme/foo\x00bar
/com/acme/foo.jar
```

PackVault preserves case in Maven paths. This matters for versions such as:

```text
1.0.0-SNAPSHOT
```

## Release immutability

Release repositories should generally use:

```yaml
allowOverwrite: false
```

If an artifact already exists, PackVault returns:

```text
409 Conflict
```

This protects reproducible builds and reduces the risk of accidental or malicious artifact replacement.

## Snapshot mutability

Snapshot repositories may use:

```yaml
allowOverwrite: true
```

This allows repeated publishing of snapshot artifacts.

## Audit logging

Write attempts are audit logged.

Audit logs include:

```text
repository
path
principal
client IP
user agent
status code
bytes uploaded
request ID
```

Audit logs must not include:

```text
raw tokens
passwords
Authorization headers
cookies
session secrets
client secrets
```

## HTTP security headers

PackVault sets basic security headers, including:

```text
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
Referrer-Policy: no-referrer
Permissions-Policy: camera=(), microphone=(), geolocation=(), payment=()
```

HTML responses also receive a Content Security Policy.

## HTTPS

Use HTTPS in production.

It is acceptable for PackVault to receive HTTP traffic internally behind an ingress or reverse proxy, but external traffic should be TLS-only.

Recommended production shape:

```text
client
  -> HTTPS ingress / reverse proxy
  -> PackVault service
  -> local storage or S3-compatible storage
```

## S3 / object storage security

For S3 mode, use least-privilege credentials.

The application should only need access to the configured bucket/prefix.

Recommended permissions:

```text
s3:GetObject
s3:PutObject
s3:ListBucket
s3:HeadBucket
```

Avoid broad permissions such as:

```text
s3:*
```

For stronger release immutability later, consider:

```text
S3 Object Lock
bucket policies preventing overwrite/delete
separate read/write IAM roles
```

## Not supported in v1

These are intentionally not part of v1:

```text
anonymous write
DELETE
public directory listing
built-in malware scanning
built-in vulnerability scanning
storage-level object lock automation
complex RBAC
```
