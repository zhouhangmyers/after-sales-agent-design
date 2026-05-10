from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from types import TracebackType

from sqlalchemy.ext.asyncio import AsyncSession

from after_sales.application.ports import (
    AfterSalesRepository,
    AfterSalesUnitOfWork,
)
from after_sales.infrastructure.persistence.sqlalchemy.repositories import (
    SqlAlchemyAfterSalesRepository,
)


class SqlAlchemyAfterSalesUnitOfWork:
    def __init__(
        self,
        session_factory: Callable[[], AbstractAsyncContextManager[AsyncSession]],
    ) -> None:
        self._session_factory = session_factory
        self._session_context: AbstractAsyncContextManager[AsyncSession] | None = None
        self._session: AsyncSession | None = None
        self._repository: AfterSalesRepository | None = None
        self._committed = False

    @property
    def repository(self) -> AfterSalesRepository:
        if self._repository is None:
            raise RuntimeError("unit of work is not active")
        return self._repository

    async def __aenter__(self) -> AfterSalesUnitOfWork:
        self._session_context = self._session_factory()
        self._session = await self._session_context.__aenter__()
        self._repository = SqlAlchemyAfterSalesRepository(self._session)
        self._committed = False
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        if self._session is not None and not self._committed:
            await self.rollback()
        if self._session_context is not None:
            result = await self._session_context.__aexit__(exc_type, exc, traceback)
            self._session_context = None
            self._session = None
            self._repository = None
            return result
        return None

    async def commit(self) -> None:
        if self._session is None:
            raise RuntimeError("unit of work is not active")
        await self._session.commit()
        self._committed = True

    async def rollback(self) -> None:
        if self._session is None:
            raise RuntimeError("unit of work is not active")
        await self._session.rollback()
