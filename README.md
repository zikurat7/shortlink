# shortlink

A URL shortener with a small web interface and a JSON API, written in plain Python
(standard library only, Python 3.9+). Paste a long URL, get a short one back. Links can have
custom aliases and expiry times, and every link keeps a click count.

## Quick start

```
PYTHONPATH=src python -m shortlink --port 8000 --db links.db   # or `pip install -e .` and drop PYTHONPATH
```

Then open <http://localhost:8000/> in your browser.

Without `--db`, links are kept in memory and lost when the server stops.

Run the tests:

```
PYTHONPATH=src python -m unittest discover -s tests            # or just `pytest`
```

## Web interface

The page at `/` lets you:

- shorten a URL, optionally with a custom alias and an expiry time
- copy the resulting short link
- look up a link's click count and expiry by code or short URL

## API

```
curl -X POST localhost:8000/shorten -d '{"url": "https://example.com/very/long", "ttl_seconds": 3600}'
curl -i localhost:8000/<code>          # 302 redirect
curl localhost:8000/<code>/stats       # click count, expiry
```

`POST /shorten` takes a JSON body with `url` (required), `alias` (optional, 3-32 characters of
`A-Za-z0-9_-`) and `ttl_seconds` (optional, positive number).

| Status | Meaning |
|--------|---------|
| 201 | created |
| 302 | redirect |
| 400 | bad URL, alias, TTL, or JSON |
| 404 | unknown code |
| 409 | alias taken |
| 410 | link expired |
| 429 | rate limited (`Retry-After` header set) |

### Options

| Flag | Default | Meaning |
|------|---------|---------|
| `--host` | `127.0.0.1` | address to listen on |
| `--port` | `8000` | port to listen on |
| `--db` | in-memory | SQLite file for persistent storage |
| `--rate` | `5.0` | allowed requests per second per client |
| `--burst` | `20` | maximum burst size per client |

## Project layout

| File | What it does |
|------|--------------|
| `base62.py` | converts integer IDs to short strings and back |
| `cache.py` | thread-safe LRU cache with O(1) operations |
| `ratelimit.py` | per-client token bucket rate limiter |
| `storage.py` | `Storage` protocol with in-memory and SQLite backends |
| `service.py` | validation, code generation, caching, expiry |
| `server.py` | HTTP handlers |
| `web.py` | the single-page web interface |

## Design notes

**Code generation: counter + base62.** Each link gets a unique integer ID that is base62-encoded.
Collision-free by construction, and 62^7 ≈ 3.5 trillion codes fit in 7 characters.
*Trade-off:* codes are sequential and therefore guessable. If links need to be private, permute
the ID with a bijective function (e.g. multiply by a large odd number mod 62^7, or a Feistel
network), or use random codes with a retry on collision.

**Custom aliases share the namespace with generated codes**, so a generated code can collide with
an earlier alias. `shorten` retries with the next ID on `CodeExists`
(see `test_generated_code_skips_taken_alias`).

**Storage behind a protocol.** `ShortenerService` only knows `next_id / add / get / record_click`.
The same contract test suite runs against both backends (`ServiceContract` in `tests/test_service.py`),
so adding Postgres or Redis means implementing four methods and adding a three-line test class.

**LRU cache in front of storage** for the read-heavy path (redirects far outnumber creates).
Clicks are written to storage on every resolve, so `stats` reads storage directly instead of the
cache (cached copies have stale counts). Expired entries are evicted from the cache on access.

**Token bucket rate limiting.** Allows bursts up to `capacity`, then a steady `rate`.
Lazy refill means no timer thread. Fixed windows allow 2x bursts at window edges; a sliding-window
log is exact but uses O(requests) memory. The clock is injected, so tests are deterministic.

**Testability.** Time is injected (`clock=`) in the service and limiter; no `sleep` in tests.

**Redirect is 302, not 301.** 301 gets cached by browsers, which would bypass click counting
and make expiry/deletion ineffective.

## Known limitations

- **Single process.** Locks protect in-process state only. Running multiple instances needs shared
  state: ID allocation from the DB (or ID ranges leased per instance), and the rate limiter in
  Redis (atomic Lua script or `INCR` + `EXPIRE`).
- **One SQLite connection behind a lock.** Serialises all DB access. For heavier traffic, use a
  connection pool + Postgres, with click counts moved off the hot path (buffer and batch
  increments, or an event stream), since a write per redirect won't scale.
- **Rate limiter buckets are never evicted.** Memory grows with distinct client IPs. A TTL sweep
  or an LRU bound would fix this.
- **Client IP is the socket peer.** Behind a proxy that's the proxy's IP; trust
  `X-Forwarded-For` only from known proxies.
- **`http.server` is meant for light use.** For production, use an ASGI framework
  (FastAPI/Starlette) behind a reverse proxy. The stdlib keeps this project dependency-free.
- **No URL safety checks.** A public service should check links against a blocklist / Safe
  Browsing to avoid being used for phishing.

## Ideas for next steps

1. Make codes non-enumerable (see the trade-off above) and add a property-based test for uniqueness.
2. Add a Redis storage backend and run the contract tests against it.
3. Batch click counting with a background flush thread.
4. Port `server.py` to FastAPI.
5. Add a `DELETE /<code>` endpoint with an owner token.
