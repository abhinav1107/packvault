from __future__ import annotations


class PackVaultError(Exception):
    """Base application error."""

    status_code: int = 500
    code: str = "packvault_error"

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        code: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message

        if status_code is not None:
            self.status_code = status_code

        if code is not None:
            self.code = code


class BadRequestError(PackVaultError):
    status_code = 400
    code = "bad_request"


class UnauthorizedError(PackVaultError):
    status_code = 401
    code = "unauthorized"


class ForbiddenError(PackVaultError):
    status_code = 403
    code = "forbidden"


class NotFoundError(PackVaultError):
    status_code = 404
    code = "not_found"


class ConflictError(PackVaultError):
    status_code = 409
    code = "conflict"


class ServiceUnavailableError(PackVaultError):
    status_code = 503
    code = "service_unavailable"
