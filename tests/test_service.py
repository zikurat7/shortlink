import os
import unittest

from shortlink.service import (
    AliasTaken,
    Expired,
    InvalidAlias,
    InvalidURL,
    NotFound,
    ShortenerService,
)
from shortlink.storage import MemoryStorage, PostgresStorage


class FakeClock:
    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


class ServiceContract:
    """Behaviour every storage backend must satisfy; mixed into concrete TestCases."""

    def make_storage(self):
        raise NotImplementedError

    def setUp(self):
        self.clock = FakeClock()
        self.storage = self.make_storage()
        self.service = ShortenerService(self.storage, cache_size=2, clock=self.clock)

    def test_generated_codes_are_unique_and_resolvable(self):
        a = self.service.shorten("https://example.com/a")
        b = self.service.shorten("https://example.com/b")
        self.assertNotEqual(a.code, b.code)
        self.assertEqual(self.service.resolve(a.code).url, "https://example.com/a")

    def test_custom_alias(self):
        link = self.service.shorten("https://example.com", alias="my-link")
        self.assertEqual(link.code, "my-link")
        with self.assertRaises(AliasTaken):
            self.service.shorten("https://other.com", alias="my-link")

    def test_generated_code_skips_taken_alias(self):
        # Advance the counter so the next generated id (62**2) encodes to "100".
        for _ in range(62**2 - 1):
            self.storage.next_id()
        self.service.shorten("https://example.com", alias="100")
        link = self.service.shorten("https://example.com/x")
        self.assertEqual(link.code, "101")

    def test_rejects_bad_input(self):
        for url in ["", "ftp://example.com", "example.com", "http://", "javascript:alert(1)"]:
            with self.subTest(url=url), self.assertRaises(InvalidURL):
                self.service.shorten(url)
        with self.assertRaises(InvalidURL):
            self.service.shorten("https://example.com/" + "a" * 3000)
        for alias in ["ab", "has space", "x" * 33, "bad/slash"]:
            with self.subTest(alias=alias), self.assertRaises(InvalidAlias):
                self.service.shorten("https://example.com", alias=alias)
        with self.assertRaises(ValueError):
            self.service.shorten("https://example.com", ttl_seconds=0)

    def test_unknown_code(self):
        with self.assertRaises(NotFound):
            self.service.resolve("nope")
        with self.assertRaises(NotFound):
            self.service.stats("nope")

    def test_clicks_are_counted_even_when_served_from_cache(self):
        link = self.service.shorten("https://example.com")
        for _ in range(3):
            self.service.resolve(link.code)
        self.assertEqual(self.service.stats(link.code).clicks, 3)

    def test_expiry(self):
        link = self.service.shorten("https://example.com", ttl_seconds=60)
        self.service.resolve(link.code)  # warms the cache
        self.clock.now += 61
        with self.assertRaises(Expired):
            self.service.resolve(link.code)
        # Still expired on the second attempt (cache entry was dropped, storage re-checked).
        with self.assertRaises(Expired):
            self.service.resolve(link.code)

    def test_cache_eviction_does_not_break_resolution(self):
        links = [self.service.shorten(f"https://example.com/{i}") for i in range(5)]
        for link in links:
            self.assertEqual(self.service.resolve(link.code).url, link.url)

    def test_recent_lists_newest_first_and_respects_limit(self):
        codes = []
        for i in range(3):
            self.clock.now += 1
            codes.append(self.service.shorten(f"https://example.com/{i}").code)

        self.assertEqual([l.code for l in self.service.recent()], codes[::-1])
        self.assertEqual([l.code for l in self.service.recent(2)], codes[:0:-1])

    def test_recent_has_live_click_counts(self):
        link = self.service.shorten("https://example.com/a")
        self.service.resolve(link.code)
        self.assertEqual(self.service.recent()[0].clicks, 1)

    def test_recent_on_empty_storage(self):
        self.assertEqual(self.service.recent(), [])


class MemoryServiceTest(ServiceContract, unittest.TestCase):
    def make_storage(self):
        return MemoryStorage()


@unittest.skipUnless(
    os.environ.get("SHORTLINK_TEST_DATABASE_URL"), "set SHORTLINK_TEST_DATABASE_URL to run"
)
class PostgresServiceTest(ServiceContract, unittest.TestCase):
    def make_storage(self):
        storage = PostgresStorage(os.environ["SHORTLINK_TEST_DATABASE_URL"])
        self.addCleanup(storage.close)
        with storage._lock:  # start every test from an empty database
            storage._conn.execute("TRUNCATE links")
            storage._conn.execute("ALTER SEQUENCE link_id_seq RESTART")
        return storage


if __name__ == "__main__":
    unittest.main()
