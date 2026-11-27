from __future__ import annotations

import argparse
import os
from collections.abc import Sequence

import uvicorn

from product_studio.app import load_local_env

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="product-studio",
        description="Run the Product Studio FastAPI server.",
    )
    parser.add_argument(
        "--host",
        default=None,
        help=f"Bind host (default: HOST env var or {DEFAULT_HOST}).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help=f"Bind port (default: PORT env var or {DEFAULT_PORT}).",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable auto-reload for local development.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    load_local_env()
    args = build_parser().parse_args(argv)
    host = args.host or os.getenv("HOST") or DEFAULT_HOST
    port = (
        args.port if args.port is not None else int(os.getenv("PORT") or DEFAULT_PORT)
    )
    uvicorn.run(
        "product_studio.app:create_app",
        factory=True,
        host=host,
        port=port,
        reload=args.reload,
    )


if __name__ == "__main__":
    main()
