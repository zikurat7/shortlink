"""Run with: python -m shortlink [--port 8000] [--database-url postgresql://...]"""

import argparse
import os

from .ratelimit import TokenBucketLimiter
from .server import create_server
from .service import ShortenerService
from .storage import MemoryStorage, PostgresStorage, Storage


def main() -> None:
    parser = argparse.ArgumentParser(description="URL shortener service")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL"),
        help="PostgreSQL connection string (default: $DATABASE_URL; without it links are kept in memory)",
    )
    parser.add_argument("--rate", type=float, default=5.0, help="requests/second per client")
    parser.add_argument("--burst", type=int, default=20, help="max burst size per client")
    parser.add_argument("--base-url", help="public URL used in short links (default: http://HOST:PORT)")
    args = parser.parse_args()

    storage: Storage
    if args.database_url:
        storage = PostgresStorage(args.database_url)
    else:
        storage = MemoryStorage()
    service = ShortenerService(storage)
    limiter = TokenBucketLimiter(rate=args.rate, capacity=args.burst)
    server = create_server(service, limiter, args.host, args.port, args.base_url)

    print(f"Listening on http://{args.host}:{server.server_address[1]}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
