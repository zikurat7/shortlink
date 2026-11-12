"""Business logic: validation, code generation, caching, expiry."""

import re
import time
from typing import Callable, List, Optional
from urllib.parse import urlsplit

from . import base62
from .cache import LRUCache
from .storage import CodeExists, Link, Storage

MAX_URL_LENGTH = 2048
_ALIAS_RE = re.compile(r"[A-Za-z0-9_-]{3,32}")


class ShortlinkError(Exception):
    """Base class for errors the API maps to 4xx responses."""


class InvalidURL(ShortlinkError):
    pass


class InvalidAlias(ShortlinkError):
    pass


class AliasTaken(ShortlinkError):
    pass


class NotFound(ShortlinkError):
    pass


class Expired(ShortlinkError):
    pass


class ShortenerService:
    def __init__(
        self,
        storage: Storage,
        cache_size: int = 1024,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._storage = storage
        self._cache: LRUCache[str, Link] = LRUCache(cache_size)
        self._clock = clock

    def shorten(
        self,
        url: str,
        alias: Optional[str] = None,
        ttl_seconds: Optional[float] = None,
    ) -> Link:
        self._validate_url(url)
        if ttl_seconds is not None and ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")

        now = self._clock()
        expires_at = now + ttl_seconds if ttl_seconds is not None else None

        if alias is not None:
            if not _ALIAS_RE.fullmatch(alias):
                raise InvalidAlias("alias must be 3-32 chars of [A-Za-z0-9_-]")
            link = Link(alias, url, now, expires_at)
            try:
                self._storage.add(link)
            except CodeExists:
                raise AliasTaken(alias) from None
            return link

        # Generated codes can collide with a user-chosen alias, so retry on conflict.
        while True:
            link = Link(base62.encode(self._storage.next_id()), url, now, expires_at)
            try:
                self._storage.add(link)
                return link
            except CodeExists:
                continue

    def resolve(self, code: str) -> Link:
        """Look up a code for redirecting; counts a click."""
        link = self._cache.get(code)
        if link is None:
            link = self._storage.get(code)
            if link is None:
                raise NotFound(code)
            self._cache.put(code, link)

        if self._is_expired(link):
            self._cache.discard(code)
            raise Expired(code)

        self._storage.record_click(code)
        return link

    def stats(self, code: str) -> Link:
        # Read straight from storage: cached copies have stale click counts.
        link = self._storage.get(code)
        if link is None:
            raise NotFound(code)
        return link

    def recent(self, limit: int = 50) -> List[Link]:
        """Newest links first, with live click counts (read from storage, not the cache)."""
        return self._storage.list_recent(limit)

    def _is_expired(self, link: Link) -> bool:
        return link.expires_at is not None and self._clock() >= link.expires_at

    @staticmethod
    def _validate_url(url: str) -> None:
        if not isinstance(url, str) or len(url) > MAX_URL_LENGTH:
            raise InvalidURL("url must be a string of at most 2048 characters")
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.netloc:
            raise InvalidURL("url must be an absolute http(s) URL")
