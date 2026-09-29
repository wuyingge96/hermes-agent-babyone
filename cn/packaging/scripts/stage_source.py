#!/usr/bin/env python3
"""Stage an exact Hermes source commit with the current CN overlay.

The staged tree is a build input, not a second source checkout. The source is
exported from Git, the overlay is copied from the checkout that runs this
script, and only patches listed in the patch manifest are applied.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path
from typing import Any


PACKAGING_REVISION = 1


def run_git(repo: Path, *args: str, stdout: int | None = None) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        stdout=stdout,
        text=stdout is None,
        capture_output=stdout is None,
    )
    if stdout is None:
        return result.stdout.strip()
    return ""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_patch_manifest(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise ValueError(f"unsupported patch manifest: {path}")
    patches = payload.get("patches")
    if not isinstance(patches, list):
        raise ValueError(f"patches must be a list: {path}")
    result: list[dict[str, Any]] = []
    for entry in patches:
        if not isinstance(entry, dict):
            raise ValueError(f"patch entry must be an object: {path}")
        patch_id = entry.get("id")
        patch_file = entry.get("file")
        if not isinstance(patch_id, str) or not patch_id.strip():
            raise ValueError(f"patch entry has no id: {path}")
        if not isinstance(patch_file, str) or not patch_file.strip():
            raise ValueError(f"patch entry has no file: {patch_id}")
        result.append({"id": patch_id, "file": patch_file})
    return result


def safe_extract(tar_path: Path, destination: Path) -> None:
    destination_root = destination.resolve()
    with tarfile.open(tar_path) as archive:
        for member in archive.getmembers():
            target = (destination / member.name).resolve()
            if target != destination_root and destination_root not in target.parents:
                raise ValueError(f"git archive contains an unsafe path: {member.name}")
        archive.extractall(destination, filter="data")


def apply_patch(staged_root: Path, patch_path: Path) -> None:
    subprocess.run(
        ["git", "-C", str(staged_root), "apply", "--check", str(patch_path)],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(staged_root), "apply", str(patch_path)],
        check=True,
    )


def stage_source(
    repo: Path,
    source_commit: str,
    output: Path,
    patch_manifest: Path,
    *,
    force: bool = False,
) -> dict[str, Any]:
    resolved_commit = run_git(repo, "rev-parse", "--verify", f"{source_commit}^{{commit}}")
    overlay_root = repo / "cn"
    if not overlay_root.is_dir():
        raise ValueError(f"CN overlay directory is missing: {overlay_root}")
    patches = load_patch_manifest(patch_manifest)
    output = output.resolve()
    if output == repo or output in repo.parents:
        raise ValueError(f"staging output cannot replace the source checkout or its parent: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="hermes-cn-archive-") as temp_dir:
        archive_path = Path(temp_dir) / "source.tar"
        with archive_path.open("wb") as archive:
            run_git(repo, "archive", "--format=tar", resolved_commit, stdout=archive)
        if output.exists() and not force:
            raise FileExistsError(f"staging output exists; pass --force to replace it: {output}")
        if output.exists():
            shutil.rmtree(output)
        output.mkdir(parents=True)
        safe_extract(archive_path, output)

    staged_overlay = output / "cn"
    if staged_overlay.exists():
        shutil.rmtree(staged_overlay)
    shutil.copytree(overlay_root, staged_overlay)

    applied: list[dict[str, str]] = []
    for entry in patches:
        patch_path = (repo / entry["file"]).resolve()
        if not patch_path.is_file():
            raise FileNotFoundError(f"patch file does not exist: {patch_path}")
        apply_patch(output, patch_path)
        applied.append({"id": entry["id"], "file": entry["file"]})

    catalog_path = staged_overlay / "capabilities" / "catalog.yaml"
    metadata = {
        "schema_version": 1,
        "packaging_revision": PACKAGING_REVISION,
        "source_commit": resolved_commit,
        "source_request": source_commit,
        "catalog_sha256": sha256_file(catalog_path),
        "patch_manifest": str(patch_manifest.relative_to(repo)).replace("\\", "/"),
        "patches": applied,
    }
    (output / "cn-build-inputs.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return metadata


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-commit", required=True, help="Git commit, tag, or ref to export")
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[3])
    parser.add_argument("--output", type=Path, required=True, help="Empty or replaceable staging directory")
    parser.add_argument("--force", action="store_true", help="Replace an existing staging directory")
    parser.add_argument(
        "--patch-manifest",
        type=Path,
        default=None,
        help="Patch manifest relative to repo root (defaults to cn/patches/manifest.json)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo = args.repo_root.resolve()
    patch_manifest = (args.patch_manifest or repo / "cn/patches/manifest.json").resolve()
    metadata = stage_source(repo, args.source_commit, args.output, patch_manifest, force=args.force)
    print(json.dumps(metadata, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
