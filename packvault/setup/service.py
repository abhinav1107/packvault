from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from alembic.config import Config
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from alembic import command
from packvault.config.settings import Settings
from packvault.db.models import (
    Group,
    GroupPermission,
    SystemState,
    Token,
    TokenPermission,
)
from packvault.secrets.protector import SecretProtector

logger = logging.getLogger(__name__)

DEFAULT_GROUPS: tuple[tuple[str, str, tuple[tuple[str, str], ...]], ...] = (
    (
        "publishers",
        "Maven publishers with read/write access to configured repositories",
        (
            ("releases", "read"),
            ("releases", "write"),
            ("snapshots", "read"),
            ("snapshots", "write"),
        ),
    ),
    (
        "readers",
        "Maven readers with read-only access to releases",
        (("releases", "read"),),
    ),
)


@dataclass(frozen=True)
class DatabaseConnectionStatus:
    reachable: bool
    detail: str


@dataclass(frozen=True)
class SystemInitializationStatus:
    initialized: bool
    initialized_at: datetime | None = None
    initialized_by: str | None = None
    encryption_key_fingerprint: str | None = None


def _alembic_project_root() -> Path:
    candidates: list[Path] = []

    app_root = os.environ.get("PACKVAULT_APP_ROOT", "").strip()
    if app_root:
        candidates.append(Path(app_root))

    candidates.extend(
        [
            Path(__file__).resolve().parents[2],
            Path("/app"),
        ]
    )

    seen: set[Path] = set()
    for root in candidates:
        if root in seen:
            continue
        seen.add(root)
        if (root / "alembic.ini").is_file() and (root / "alembic").is_dir():
            return root

    raise RuntimeError(
        "Alembic migration files not found. Ensure alembic.ini and alembic/ are "
        "present in the deployment image or set PACKVAULT_APP_ROOT."
    )


def alembic_config() -> Config:
    project_root = _alembic_project_root()
    config = Config(str(project_root / "alembic.ini"))
    config.set_main_option("script_location", str(project_root / "alembic"))
    return config


def run_migrations(database_url: str) -> None:
    config = alembic_config()
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")


async def run_migrations_async(database_url: str) -> None:
    """Run Alembic in a worker thread so asyncio.run() in env.py is safe."""
    await asyncio.to_thread(run_migrations, database_url)


async def check_database_connection(session: AsyncSession) -> DatabaseConnectionStatus:
    try:
        await session.execute(text("SELECT 1"))
    except Exception as exc:
        return DatabaseConnectionStatus(reachable=False, detail=str(exc))
    return DatabaseConnectionStatus(reachable=True, detail="connected")


async def read_initialization_status(session: AsyncSession) -> SystemInitializationStatus:
    result = await session.execute(select(SystemState).where(SystemState.id == 1))
    row = result.scalar_one_or_none()
    if row is None:
        return SystemInitializationStatus(initialized=False)

    return SystemInitializationStatus(
        initialized=row.initialized,
        initialized_at=row.initialized_at,
        initialized_by=row.initialized_by,
        encryption_key_fingerprint=row.encryption_key_fingerprint,
    )


async def schema_tables_exist(session: AsyncSession) -> bool:
    result = await session.execute(
        text(
            "SELECT EXISTS ("
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = 'system_state'"
            ")"
        )
    )
    return bool(result.scalar())


async def initialize_system(
    session: AsyncSession,
    *,
    settings: Settings,
    protector: SecretProtector,
    initialized_by: str,
) -> None:
    from packvault.utils.errors import ConflictError

    if await schema_tables_exist(session):
        status = await read_initialization_status(session)
        if status.initialized:
            raise ConflictError("PackVault is already initialized")
    else:
        await run_migrations_async(settings.database.url)

    # Migrations run on a separate connection; reset any aborted transaction
    # from earlier checks in this session before seeding.
    await session.rollback()

    now = datetime.now(UTC)
    fingerprint = protector.key_fingerprint

    system_state = SystemState(
        id=1,
        initialized=True,
        initialized_at=now,
        initialized_by=initialized_by,
        encryption_key_fingerprint=fingerprint,
    )
    session.add(system_state)

    for group_name, description, permissions in DEFAULT_GROUPS:
        group = Group(name=group_name, description=description)
        session.add(group)
        await session.flush()

        for repository, action in permissions:
            session.add(
                GroupPermission(
                    group_id=group.id,
                    repository=repository,
                    action=action,
                )
            )

    for token_cfg in settings.auth.tokens:
        protected = protector.protect(token_cfg.token_hash)
        token = Token(
            name=token_cfg.name,
            token_hash=protected.stored,
            secret_status=protected.secret_status,
            expires_at=token_cfg.expires_at,
        )
        session.add(token)
        await session.flush()

        for permission in token_cfg.permissions:
            for action in permission.actions:
                session.add(
                    TokenPermission(
                        token_id=token.id,
                        repository=permission.repository,
                        action=action,
                    )
                )

    await session.commit()
    logger.info("PackVault database initialized by %s", initialized_by)
