"""HTTP API built on the standard library.

GET  /               -> 200 HTML web page
POST /shorten        {"url": ..., "alias": ..., "ttl_seconds": ...} -> 201 JSON
GET  /<code>         -> 302 redirect (404 unknown, 410 expired)
GET  /<code>/stats   -> 200 JSON
GET  /api/links      -> 200 JSON {"links": [...]}, newest first (?limit=1..200, default 50)
"""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Optional, Type
from urllib.parse import parse_qs, urlsplit

from .ratelimit import TokenBucketLimiter
from .service import (
    AliasTaken,
    Expired,
    InvalidAlias,
    InvalidURL,
    NotFound,
    ShortenerService,
)
from .storage import Link
from .web import INDEX_HTML

MAX_BODY_BYTES = 8 * 1024
DEFAULT_LIST_LIMIT = 50
MAX_LIST_LIMIT = 200


def _link_json(link: Link, base_url: str) -> Dict[str, Any]:
    return {
        "code": link.code,
        "short_url": f"{base_url}/{link.code}",
        "url": link.url,
        "created_at": link.created_at,
        "expires_at": link.expires_at,
        "clicks": link.clicks,
    }


def make_handler(
    service: ShortenerService,
    limiter: TokenBucketLimiter,
    base_url: str,
) -> Type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:  # keep tests quiet
            pass

        # --- helpers -------------------------------------------------------
        def _send_json(
            self, status: int, body: Dict[str, Any], headers: Optional[Dict[str, str]] = None
        ) -> None:
            payload = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            for name, value in (headers or {}).items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(payload)

        def _error(self, status: int, message: str) -> None:
            self._send_json(status, {"error": message})

        def _rate_limited(self) -> bool:
            allowed, retry_after = limiter.acquire(self.client_address[0])
            if not allowed:
                self._send_json(
                    429, {"error": "rate limit exceeded"}, {"Retry-After": str(retry_after)}
                )
            return not allowed

        def _list_links(self, query: str) -> None:
            try:
                limit = int(parse_qs(query).get("limit", [DEFAULT_LIST_LIMIT])[0])
            except ValueError:
                return self._error(400, "limit must be an integer")
            limit = max(1, min(limit, MAX_LIST_LIMIT))
            links = [_link_json(link, base_url) for link in service.recent(limit)]
            self._send_json(200, {"links": links})

        # --- routes --------------------------------------------------------
        def do_POST(self) -> None:
            if self.path != "/shorten":
                return self._error(404, "not found")
            if self._rate_limited():
                return

            try:
                length = int(self.headers.get("Content-Length", 0))
            except ValueError:
                return self._error(400, "invalid Content-Length")
            if length <= 0 or length > MAX_BODY_BYTES:
                return self._error(400, "body must be 1-8192 bytes")
            try:
                body = json.loads(self.rfile.read(length))
                if not isinstance(body, dict):
                    raise ValueError
            except ValueError:
                return self._error(400, "body must be a JSON object")

            try:
                link = service.shorten(
                    body.get("url"), body.get("alias"), body.get("ttl_seconds")
                )
            except AliasTaken:
                return self._error(409, "alias already taken")
            except (InvalidURL, InvalidAlias, ValueError, TypeError) as exc:
                return self._error(400, str(exc))
            self._send_json(201, _link_json(link, base_url))

        def do_GET(self) -> None:
            if self.path == "/":
                payload = INDEX_HTML.encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return
            if self._rate_limited():
                return

            url = urlsplit(self.path)
            if url.path == "/api/links":
                return self._list_links(url.query)

            parts = self.path.strip("/").split("/")
            try:
                if len(parts) == 1 and parts[0]:
                    link = service.resolve(parts[0])
                    self.send_response(302)
                    self.send_header("Location", link.url)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                elif len(parts) == 2 and parts[1] == "stats":
                    self._send_json(200, _link_json(service.stats(parts[0]), base_url))
                else:
                    self._error(404, "not found")
            except NotFound:
                self._error(404, "unknown code")
            except Expired:
                self._error(410, "link expired")

    return Handler


def create_server(
    service: ShortenerService,
    limiter: TokenBucketLimiter,
    host: str = "127.0.0.1",
    port: int = 8000,
    base_url: Optional[str] = None,
) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), BaseHTTPRequestHandler)
    if base_url is None:
        base_url = f"http://{host}:{server.server_address[1]}"
    server.RequestHandlerClass = make_handler(service, limiter, base_url.rstrip("/"))
    return server
