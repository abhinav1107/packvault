from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


class DatabaseManager:
    def __init__(self, url: str) -> None:
        self._url = url
        self._engine: AsyncEngine | None = None
        self._session_factory: async_sessionmaker[AsyncSession] | None = None

    @property
    def enabled(self) -> bool:
        return bool(self._url.strip())

    @property
    def engine(self) -> AsyncEngine:
        if self._engine is None:
            raise RuntimeError("database engine is not initialized")
        return self._engine

    def initialize(self) -> None:
        if not self.enabled:
            return

        self._engine = create_async_engine(
            self._url,
            pool_pre_ping=True,
        )
        self._session_factory = async_sessionmaker(
            self._engine,
            expire_on_commit=False,
        )

    async def close(self) -> None:
        if self._engine is not None:
            await self._engine.dispose()
            self._engine = None
            self._session_factory = None

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        if self._session_factory is None:
            raise RuntimeError("database session factory is not initialized")

        async with self._session_factory() as db_session:
            yield db_session


def create_database_manager(url: str) -> DatabaseManager:
    return DatabaseManager(url)
