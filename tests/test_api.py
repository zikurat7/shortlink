import http.client
import json
import threading
import unittest

from shortlink.ratelimit import TokenBucketLimiter
from shortlink.server import create_server
from shortlink.service import ShortenerService
from shortlink.storage import MemoryStorage


class ApiTest(unittest.TestCase):
    def setUp(self):
        self.service = ShortenerService(MemoryStorage())
        self.start_server(capacity=100)

    def start_server(self, capacity):
        # Frozen clock: the bucket never refills, so rate-limit behaviour is deterministic.
        limiter = TokenBucketLimiter(rate=1, capacity=capacity, clock=lambda: 0.0)
        server = create_server(self.service, limiter, port=0)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)  # runs first (LIFO)
        self.port = server.server_address[1]

    def request(self, method, path, body=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        self.addCleanup(conn.close)
        payload = json.dumps(body) if body is not None else None
        conn.request(method, path, body=payload)
        resp = conn.getresponse()
        raw = resp.read()
        return resp, json.loads(raw) if raw else None

    def test_shorten_redirect_and_stats(self):
        resp, data = self.request("POST", "/shorten", {"url": "https://example.com/page"})
        self.assertEqual(resp.status, 201)
        self.assertTrue(data["short_url"].endswith("/" + data["code"]))

        resp, _ = self.request("GET", "/" + data["code"])
        self.assertEqual(resp.status, 302)
        self.assertEqual(resp.getheader("Location"), "https://example.com/page")

        resp, stats = self.request("GET", f"/{data['code']}/stats")
        self.assertEqual(resp.status, 200)
        self.assertEqual(stats["clicks"], 1)

    def test_serves_web_page(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        self.addCleanup(conn.close)
        conn.request("GET", "/")
        resp = conn.getresponse()
        body = resp.read().decode()
        self.assertEqual(resp.status, 200)
        self.assertTrue(resp.getheader("Content-Type").startswith("text/html"))
        self.assertIn("<form", body)

    def test_error_statuses(self):
        resp, _ = self.request("POST", "/shorten", {"url": "not a url"})
        self.assertEqual(resp.status, 400)
        resp, _ = self.request("POST", "/shorten", {"url": 123})
        self.assertEqual(resp.status, 400)
        resp, _ = self.request("POST", "/shorten", {"url": "https://a.com", "ttl_seconds": "x"})
        self.assertEqual(resp.status, 400)
        resp, _ = self.request("GET", "/missing")
        self.assertEqual(resp.status, 404)

        self.request("POST", "/shorten", {"url": "https://a.com", "alias": "taken"})
        resp, _ = self.request("POST", "/shorten", {"url": "https://b.com", "alias": "taken"})
        self.assertEqual(resp.status, 409)

    def test_malformed_json(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        self.addCleanup(conn.close)
        conn.request("POST", "/shorten", body="{not json")
        resp = conn.getresponse()
        resp.read()
        self.assertEqual(resp.status, 400)

    def test_rate_limit(self):
        self.start_server(capacity=2)

        statuses = [self.request("GET", "/missing")[0].status for _ in range(3)]
        self.assertEqual(statuses, [404, 404, 429])
        resp, _ = self.request("GET", "/missing")
        self.assertEqual(resp.getheader("Retry-After"), "1")


if __name__ == "__main__":
    unittest.main()
