from __future__ import annotations

import logging

from sqlalchemy import select

from packvault.config.settings import Settings
from packvault.db.engine import DatabaseManager
from packvault.db.models import SystemState
from packvault.secrets.encryption import EncryptionContext
from packvault.setup.service import read_initialization_status, schema_tables_exist
from packvault.utils.errors import ServiceUnavailableError

logger = logging.getLogger(__name__)


async def load_system_initialized(
    database: DatabaseManager,
) -> bool:
    if not database.enabled:
        return False

    async with database.session() as session:
        if not await schema_tables_exist(session):
            return False
        status = await read_initialization_status(session)
        return status.initialized


async def validate_startup_database(
    settings: Settings,
    database: DatabaseManager,
    encryption: EncryptionContext,
) -> None:
    if not database.enabled:
        return

    try:
        async with database.session() as session:
            if not await schema_tables_exist(session):
                logger.info("database schema not present; awaiting setup initialization")
                return

            status = await read_initialization_status(session)
            if not status.initialized:
                logger.info("database present but PackVault is not initialized")
                return

            result = await session.execute(select(SystemState).where(SystemState.id == 1))
            row = result.scalar_one_or_none()
            if row is None:
                raise ServiceUnavailableError(
                    "PackVault is marked initialized but system_state row is missing. "
                    "Restore the database or reset initialization state."
                )

            if encryption.enabled and row.encryption_key_fingerprint:
                if encryption.fingerprint != row.encryption_key_fingerprint:
                    raise ServiceUnavailableError(
                        "Encryption key fingerprint does not match the value recorded "
                        "during initialization. Verify PACKVAULT_SECRETS_ENCRYPTION_KEY "
                        "or the configured AWS Secrets Manager secret."
                    )
    except ServiceUnavailableError:
        raise
    except Exception as exc:
        raise ServiceUnavailableError(
            "PackVault is initialized but the database is unreachable or invalid. "
            f"Detail: {exc}"
        ) from exc
