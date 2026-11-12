import unittest

from shortlink import base62
from shortlink.cache import LRUCache
from shortlink.ratelimit import TokenBucketLimiter


class FakeClock:
    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


class Base62Test(unittest.TestCase):
    def test_known_values(self):
        self.assertEqual(base62.encode(0), "0")
        self.assertEqual(base62.encode(61), "z")
        self.assertEqual(base62.encode(62), "10")

    def test_round_trip(self):
        for n in [0, 1, 61, 62, 12345, 10**12, 2**63]:
            self.assertEqual(base62.decode(base62.encode(n)), n)

    def test_invalid(self):
        with self.assertRaises(ValueError):
            base62.encode(-1)
        with self.assertRaises(ValueError):
            base62.decode("")
        with self.assertRaises(ValueError):
            base62.decode("ab!")


class LRUCacheTest(unittest.TestCase):
    def test_evicts_least_recently_used(self):
        cache = LRUCache(2)
        cache.put("a", 1)
        cache.put("b", 2)
        cache.get("a")  # "b" is now the oldest
        cache.put("c", 3)
        self.assertIsNone(cache.get("b"))
        self.assertEqual(cache.get("a"), 1)
        self.assertEqual(cache.get("c"), 3)

    def test_update_existing_key_does_not_grow(self):
        cache = LRUCache(2)
        cache.put("a", 1)
        cache.put("a", 2)
        self.assertEqual(len(cache), 1)
        self.assertEqual(cache.get("a"), 2)

    def test_discard(self):
        cache = LRUCache(2)
        cache.put("a", 1)
        cache.discard("a")
        cache.discard("missing")
        self.assertIsNone(cache.get("a"))

    def test_invalid_capacity(self):
        with self.assertRaises(ValueError):
            LRUCache(0)


class TokenBucketTest(unittest.TestCase):
    def test_burst_then_reject(self):
        limiter = TokenBucketLimiter(rate=1, capacity=3, clock=FakeClock())
        self.assertEqual([limiter.acquire("k")[0] for _ in range(3)], [True] * 3)
        allowed, retry_after = limiter.acquire("k")
        self.assertFalse(allowed)
        self.assertEqual(retry_after, 1)

    def test_refills_over_time_up_to_capacity(self):
        clock = FakeClock()
        limiter = TokenBucketLimiter(rate=2, capacity=2, clock=clock)
        limiter.acquire("k")
        limiter.acquire("k")
        self.assertFalse(limiter.acquire("k")[0])
        clock.now += 0.5  # refills exactly one token
        self.assertTrue(limiter.acquire("k")[0])
        self.assertFalse(limiter.acquire("k")[0])
        clock.now += 100  # refill is capped at capacity
        self.assertEqual([limiter.acquire("k")[0] for _ in range(3)], [True, True, False])

    def test_keys_are_independent(self):
        limiter = TokenBucketLimiter(rate=1, capacity=1, clock=FakeClock())
        self.assertTrue(limiter.acquire("a")[0])
        self.assertFalse(limiter.acquire("a")[0])
        self.assertTrue(limiter.acquire("b")[0])


if __name__ == "__main__":
    unittest.main()
