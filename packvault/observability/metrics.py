from __future__ import annotations

from prometheus_client import Counter, Histogram, generate_latest

MAVEN_REQUESTS = Counter(
    "maven_requests_total",
    "Maven HTTP requests",
    ["method", "repository", "status"],
)
MAVEN_DURATION = Histogram(
    "maven_request_duration_seconds",
    "Maven request duration",
    ["method", "repository"],
)
STORAGE_OPS = Counter(
    "maven_storage_operations_total",
    "Storage operations",
    ["operation", "backend"],
)
STORAGE_ERRORS = Counter(
    "maven_storage_operation_errors_total",
    "Storage operation errors",
    ["operation", "backend"],
)
AUTH_FAILURES = Counter("maven_auth_failures_total", "Authentication failures", ["kind"])
UPLOAD_BYTES = Counter("maven_upload_bytes_total", "Bytes uploaded", ["repository"])
DOWNLOAD_BYTES = Counter("maven_download_bytes_total", "Bytes downloaded", ["repository"])


def metrics_response() -> bytes:
    return generate_latest()
