#!/usr/bin/env python3
"""Write the complete immutable inventory for a staged MasCloner release."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("release_dir", type=Path)
    parser.add_argument("--revision", required=True, help="immutable Git commit for this artifact")
    args = parser.parse_args()
    if re.fullmatch(r"[0-9a-f]{40}", args.revision) is None:
        parser.error("--revision must be a full lowercase 40-character Git commit hash")
    root = args.release_dir.resolve()
    version = (root / "VERSION").read_text(encoding="utf-8").strip()
    (root / ".commit_hash").write_text(args.revision + "\n", encoding="utf-8")
    inventory = {
        path.relative_to(root).as_posix(): digest(path)
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.name != "RELEASE.json"
    }
    (root / "RELEASE.json").write_text(
        json.dumps({"format": 1, "version": version, "revision": args.revision, "inventory": inventory}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
