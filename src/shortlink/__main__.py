"""Run with: python -m shortlink [--port 8000] [--db links.db]"""

import argparse

from .ratelimit import TokenBucketLimiter
from .server import create_server
from .service import ShortenerService
from .storage import MemoryStorage, SQLiteStorage


def main() -> None:
    parser = argparse.ArgumentParser(description="URL shortener service")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--db", help="SQLite file path (default: in-memory, lost on exit)")
    parser.add_argument("--rate", type=float, default=5.0, help="requests/second per client")
    parser.add_argument("--burst", type=int, default=20, help="max burst size per client")
    args = parser.parse_args()

    storage = SQLiteStorage(args.db) if args.db else MemoryStorage()
    service = ShortenerService(storage)
    limiter = TokenBucketLimiter(rate=args.rate, capacity=args.burst)
    server = create_server(service, limiter, args.host, args.port)

    print(f"Listening on http://{args.host}:{server.server_address[1]}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
