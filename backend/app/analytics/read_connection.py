"""Short-lived, read-only PostgreSQL connections for AnalyticsTools."""

from __future__ import annotations

from contextlib import contextmanager
from collections.abc import Callable, Iterator
from typing import Any


AnalyticsConnectionFactory = Callable[[], Any]


class ShortReadConnection:
    """Open one bounded read-only transaction for each AnalyticsTools query."""

    __slots__ = ("_factory",)

    def __init__(self, factory: AnalyticsConnectionFactory) -> None:
        if not callable(factory):
            raise ValueError("connection factory must be callable")
        self._factory = factory

    @contextmanager
    def cursor(self) -> Iterator[Any]:
        connection: Any | None = None
        cursor: Any | None = None
        committed = False
        try:
            connection = self._factory()
            if getattr(connection, "autocommit", None) is not False:
                raise RuntimeError("analytics connection must use autocommit=False")
            cursor = connection.cursor()
            cursor.execute("SET TRANSACTION READ ONLY")
            cursor.execute("SET LOCAL statement_timeout = '10000ms'")
            yield cursor
            cursor.close()
            cursor = None
            connection.commit()
            committed = True
        except Exception:
            if connection is not None and not committed:
                try:
                    connection.rollback()
                except Exception:
                    pass
            # Driver errors can contain SQL, credentials, or server details.
            raise RuntimeError("analytics_query_failed") from None
        finally:
            if cursor is not None:
                try:
                    cursor.close()
                except Exception:
                    pass
            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    pass

    def __repr__(self) -> str:
        return "ShortReadConnection(factory=[configured])"
