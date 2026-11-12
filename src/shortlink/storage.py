"""Storage backends. The service depends only on the `Storage` protocol."""

import sqlite3
from dataclasses import dataclass, replace
from threading import Lock
from typing import Dict, Optional, Protocol


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


class SQLiteStorage:
    def __init__(self, path: str = ":memory:") -> None:
        # One shared connection guarded by a lock; fine for a single-process demo.
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._lock = Lock()
        with self._lock, self._conn:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS links (
                    code       TEXT PRIMARY KEY,
                    url        TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    expires_at REAL,
                    clicks     INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS counter (
                    id    INTEGER PRIMARY KEY CHECK (id = 1),
                    value INTEGER NOT NULL
                );
                INSERT OR IGNORE INTO counter (id, value) VALUES (1, 0);
                """
            )

    def next_id(self) -> int:
        with self._lock, self._conn:
            (value,) = self._conn.execute(
                "UPDATE counter SET value = value + 1 WHERE id = 1 RETURNING value"
            ).fetchone()
            return value

    def add(self, link: Link) -> None:
        with self._lock:
            try:
                with self._conn:
                    self._conn.execute(
                        "INSERT INTO links (code, url, created_at, expires_at, clicks)"
                        " VALUES (?, ?, ?, ?, ?)",
                        (link.code, link.url, link.created_at, link.expires_at, link.clicks),
                    )
            except sqlite3.IntegrityError:
                raise CodeExists(link.code) from None

    def get(self, code: str) -> Optional[Link]:
        with self._lock:
            row = self._conn.execute(
                "SELECT code, url, created_at, expires_at, clicks FROM links WHERE code = ?",
                (code,),
            ).fetchone()
        return Link(*row) if row else None

    def record_click(self, code: str) -> None:
        with self._lock, self._conn:
            self._conn.execute("UPDATE links SET clicks = clicks + 1 WHERE code = ?", (code,))
