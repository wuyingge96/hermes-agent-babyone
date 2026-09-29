#!/usr/bin/env python3
"""Write the schema v2 manifest consumed by the CN Electron installer."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform as platform_module
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--staging-metadata", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--platform", required=True, choices=("win32", "darwin"))
    parser.add_argument("--arch", required=True, choices=("x64", "arm64"))
    parser.add_argument("--runtime-version", required=True)
    parser.add_argument("--kernel-version", required=True)
    parser.add_argument("--runtime-flavor", default="cn")
    parser.add_argument("--runtime-revision", type=int, default=1)
    parser.add_argument("--channel", default="stable")
    parser.add_argument("--source-repo", default="")
    args = parser.parse_args()

    archive = args.archive.resolve()
    metadata = json.loads(args.staging_metadata.read_text(encoding="utf-8"))
    if not isinstance(metadata, dict) or not metadata.get("source_commit"):
        raise ValueError("staging metadata must contain source_commit")
    manifest = {
        "schemaVersion": 2,
        "channel": args.channel,
        "runtimeVersion": args.runtime_version,
        "kernelVersion": args.kernel_version,
        "runtimeFlavor": args.runtime_flavor,
        "runtimeRevision": args.runtime_revision,
        "platform": args.platform,
        "arch": args.arch,
        "sha256": sha256(archive),
        "sourceRepo": args.source_repo,
        "sourceCommit": metadata["source_commit"],
        "catalogSha256": metadata.get("catalog_sha256"),
        "packagingRevision": metadata.get("packaging_revision"),
        "patches": metadata.get("patches", []),
        "builder": platform_module.platform(),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
