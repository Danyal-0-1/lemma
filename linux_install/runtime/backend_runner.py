#!/usr/bin/env python3
"""Start Lemma's installed backend without importing untrusted shell config."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def _directory(value: str) -> Path:
    path = Path(value).resolve(strict=True)
    if not path.is_dir():
        raise argparse.ArgumentTypeError(f"not a directory: {value}")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description="Start the installed Lemma backend")
    parser.add_argument("--backend", type=_directory, required=True)
    parser.add_argument("--vendor", type=_directory, required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    args = parser.parse_args()

    # The vendored dependency directory is architecture/Python specific and is made
    # by build.sh on Linux. The user's versioned source copy comes before it.
    sys.path.insert(0, str(args.vendor))
    sys.path.insert(0, str(args.backend))

    from dotenv import load_dotenv

    env_file = args.env_file.resolve(strict=True)
    if not env_file.is_file():
        raise SystemExit("Lemma configuration file is unavailable")
    load_dotenv(dotenv_path=env_file, override=False)

    # These values are transport invariants, not user preferences. Forcing them here
    # keeps a stale environment variable from widening the listening boundary.
    os.environ["HOST"] = "127.0.0.1"
    os.environ["PORT"] = "8000"
    os.environ["FRONTEND_ORIGINS"] = (
        "http://127.0.0.1:5173,http://localhost:5173"
    )

    import uvicorn
    from app.main import app

    uvicorn.run(
        app,
        host="127.0.0.1",
        port=8000,
        access_log=False,
        proxy_headers=False,
        server_header=False,
    )


if __name__ == "__main__":
    main()
