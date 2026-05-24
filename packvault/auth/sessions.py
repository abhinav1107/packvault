from __future__ import annotations

from typing import Any

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from packvault.auth.permissions import SessionUser


class SessionManager:
    def __init__(self, secret: str, *, max_age_seconds: int = 86400) -> None:
        self._serializer = URLSafeTimedSerializer(secret, salt="packvault-session")
        self._max_age = max_age_seconds

    def create(self, user: SessionUser) -> str:
        return self._serializer.dumps(
            {
                "subject": user.subject,
                "email": user.email,
                "name": user.name,
                "provider": user.provider,
            }
        )

    def load(self, cookie: str) -> SessionUser | None:
        try:
            data: dict[str, Any] = self._serializer.loads(cookie, max_age=self._max_age)
        except (BadSignature, SignatureExpired):
            return None

        subject = data.get("subject")
        if not isinstance(subject, str) or not subject:
            return None

        email = data.get("email")
        if email is not None and not isinstance(email, str):
            return None

        name = data.get("name")
        if name is not None and not isinstance(name, str):
            return None

        provider = data.get("provider", "local")
        if not isinstance(provider, str) or not provider:
            return None

        return SessionUser(
            subject=subject,
            email=email,
            name=name,
            provider=provider,
        )
