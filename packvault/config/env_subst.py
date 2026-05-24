from __future__ import annotations

import os
import re
from typing import Any

# ${env.VAR_NAME} — explicit so Maven paths or secrets containing "$" are unlikely to match.
_ENV_REF = re.compile(r"\$\{env\.([A-Za-z_][A-Za-z0-9_]*)\}")


class EnvSubstitutionError(ValueError):
    """Raised when a config reference points to a missing environment variable."""


def substitute_env_vars(obj: Any, *, strict: bool = True) -> Any:
    """Recursively replace ${env.NAME} in string values with os.environ[NAME]."""
    if isinstance(obj, dict):
        return {key: substitute_env_vars(value, strict=strict) for key, value in obj.items()}

    if isinstance(obj, list):
        return [substitute_env_vars(item, strict=strict) for item in obj]

    if isinstance(obj, str):
        return _substitute_string(obj, strict=strict)

    return obj


def _substitute_string(value: str, *, strict: bool) -> str:
    def replace(match: re.Match[str]) -> str:
        name = match.group(1)

        if name not in os.environ:
            if strict:
                raise EnvSubstitutionError(
                    f"Environment variable {name!r} is not set "
                    f"(referenced in config as ${{env.{name}}})"
                )

            return match.group(0)

        return os.environ[name]

    return _ENV_REF.sub(replace, value)
