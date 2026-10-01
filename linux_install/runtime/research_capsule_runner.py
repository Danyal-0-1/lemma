#!/usr/bin/env python3
"""Run the packaged research-capsule verifier in isolated Python mode."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _directory(value: str) -> Path:
    path = Path(value).resolve(strict=True)
    if not path.is_dir():
        raise argparse.ArgumentTypeError(f"not a directory: {value}")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--backend", type=_directory, required=True)
    parser.add_argument("--vendor", type=_directory, required=True)
    args, capsule_args = parser.parse_known_args()
    if capsule_args[:1] == ["--"]:
        capsule_args = capsule_args[1:]
    if not capsule_args:
        parser.error("research capsule command is required")

    # Isolated mode omits the working directory and user site-packages. Add only
    # manifest-covered application code and dependencies from this installation.
    sys.path.insert(0, str(args.vendor))
    sys.path.insert(0, str(args.backend))

    from app.lab.research_capsule import main as capsule_main

    return capsule_main(capsule_args)


if __name__ == "__main__":
    raise SystemExit(main())
