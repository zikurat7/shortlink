"""Storage backends. The service depends only on the `Storage` protocol."""

from dataclasses import dataclass, replace
from threading import Lock
from typing import Dict, List, Optional, Protocol


class CodeExists(Exception):
    """Raised when adding a link whose code is already taken."""


@dataclass(frozen=True)
class Link:
    code: str
    url: str
    created_at: float
    expires_at: Optional[float] = None
    clicks: int = 0


class Storage(Protocol):
    def next_id(self) -> int: ...
    def add(self, link: Link) -> None: ...
    def get(self, code: str) -> Optional[Link]: ...
    def record_click(self, code: str) -> None: ...
    def list_recent(self, limit: int) -> List[Link]:
        """Newest links first."""
        ...


class MemoryStorage:
    def __init__(self) -> None:
        self._links: Dict[str, Link] = {}
        self._counter = 0
        self._lock = Lock()

    def next_id(self) -> int:
        with self._lock:
            self._counter += 1
            return self._counter

    def add(self, link: Link) -> None:
        with self._lock:
            if link.code in self._links:
                raise CodeExists(link.code)
            self._links[link.code] = link

    def get(self, code: str) -> Optional[Link]:
        with self._lock:
            return self._links.get(code)

    def record_click(self, code: str) -> None:
        with self._lock:
            link = self._links.get(code)
            if link is not None:
                self._links[code] = replace(link, clicks=link.clicks + 1)

    def list_recent(self, limit: int) -> List[Link]:
        with self._lock:
            return list(reversed(self._links.values()))[:limit]  # dicts keep insertion order


class PostgresStorage:
    """PostgreSQL backend (needs `pip install shortlink[postgres]`)."""

    def __init__(self, dsn: str) -> None:
        import psycopg  # imported lazily so the stdlib-only backends need no dependencies

        self._unique_violation = psycopg.errors.UniqueViolation
        # One shared autocommit connection guarded by a lock; fine for a single-process app.
        # Each statement is its own transaction, so a failed INSERT leaves nothing to roll back.
        self._conn = psycopg.connect(dsn, autocommit=True)
        self._lock = Lock()
        with self._lock:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS links (
                    code       TEXT PRIMARY KEY,
                    url        TEXT NOT NULL,
                    created_at DOUBLE PRECISION NOT NULL,
                    expires_at DOUBLE PRECISION,
                    clicks     BIGINT NOT NULL DEFAULT 0
                )
                """
            )
            self._conn.execute("CREATE SEQUENCE IF NOT EXISTS link_id_seq")

    def next_id(self) -> int:
        with self._lock:
            (value,) = self._conn.execute("SELECT nextval('link_id_seq')").fetchone()
            return value

    def add(self, link: Link) -> None:
        with self._lock:
            try:
                self._conn.execute(
                    "INSERT INTO links (code, url, created_at, expires_at, clicks)"
                    " VALUES (%s, %s, %s, %s, %s)",
                    (link.code, link.url, link.created_at, link.expires_at, link.clicks),
                )
            except self._unique_violation:
                raise CodeExists(link.code) from None

    def get(self, code: str) -> Optional[Link]:
        with self._lock:
            row = self._conn.execute(
                "SELECT code, url, created_at, expires_at, clicks FROM links WHERE code = %s",
                (code,),
            ).fetchone()
        return Link(*row) if row else None

    def record_click(self, code: str) -> None:
        with self._lock:
            self._conn.execute("UPDATE links SET clicks = clicks + 1 WHERE code = %s", (code,))

    def list_recent(self, limit: int) -> List[Link]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT code, url, created_at, expires_at, clicks FROM links"
                " ORDER BY created_at DESC, code LIMIT %s",
                (limit,),
            ).fetchall()
        return [Link(*row) for row in rows]

    def close(self) -> None:
        self._conn.close()
