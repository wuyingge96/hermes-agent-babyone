"""Small, dependency-free contract checks for the CN packaging layer."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

from cn.packaging.scripts.build_runtime import detect_build_target, resolve_target


REPO = Path(__file__).resolve().parents[2]
STAGE = REPO / "cn/packaging/scripts/stage_source.py"
MANIFEST = REPO / "cn/packaging/scripts/write_manifest.py"


class PackagingContractTests(unittest.TestCase):
    def test_build_target_matches_selected_interpreter(self) -> None:
        detected = detect_build_target(Path(sys.executable), REPO)
        self.assertEqual(resolve_target("auto", "auto", detected), detected)
        self.assertEqual(resolve_target(*detected, detected), detected)
        other_platform = "darwin" if detected[0] == "win32" else "win32"
        other_arch = "arm64" if detected[1] == "x64" else "x64"
        with self.assertRaises(ValueError):
            resolve_target(other_platform, detected[1], detected)
        with self.assertRaises(ValueError):
            resolve_target(detected[0], other_arch, detected)

    def test_staging_records_the_requested_commit(self) -> None:
        commit = subprocess.check_output(
            ["git", "-C", str(REPO), "rev-parse", "HEAD"], text=True
        ).strip()
        with tempfile.TemporaryDirectory(prefix="hermes-cn-stage-") as directory:
            output = Path(directory) / "staged"
            subprocess.run(
                [
                    sys.executable,
                    str(STAGE),
                    "--source-commit",
                    commit,
                    "--repo-root",
                    str(REPO),
                    "--output",
                    str(output),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            metadata = json.loads((output / "cn-build-inputs.json").read_text(encoding="utf-8"))
            self.assertEqual(metadata["source_commit"], commit)
            self.assertEqual(metadata["patches"], [])
            self.assertTrue((output / "cn/capabilities/catalog.yaml").is_file())

    def test_manifest_digest_and_provenance(self) -> None:
        with tempfile.TemporaryDirectory(prefix="hermes-cn-manifest-") as directory:
            root = Path(directory)
            archive = root / "runtime.zip"
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr("hermes-agent-cn-runtime-win32-x64.exe", "contract")
            metadata = root / "inputs.json"
            metadata.write_text(
                json.dumps(
                    {
                        "source_commit": "a" * 40,
                        "catalog_sha256": "b" * 64,
                        "packaging_revision": 1,
                        "patches": [],
                    }
                ),
                encoding="utf-8",
            )
            output = root / "stable-win32-x64.json"
            subprocess.run(
                [
                    sys.executable,
                    str(MANIFEST),
                    "--archive",
                    str(archive),
                    "--staging-metadata",
                    str(metadata),
                    "--output",
                    str(output),
                    "--platform",
                    "win32",
                    "--arch",
                    "x64",
                    "--runtime-version",
                    "0.0.0-cn.1",
                    "--kernel-version",
                    "0.0.0",
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            manifest = json.loads(output.read_text(encoding="utf-8"))
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            self.assertEqual(manifest["schemaVersion"], 2)
            self.assertEqual(manifest["sha256"], digest)
            self.assertEqual(manifest["sourceCommit"], "a" * 40)
            self.assertEqual(manifest["platform"], "win32")
            self.assertEqual(manifest["arch"], "x64")

    def test_electron_archive_has_runtime_at_zip_root(self) -> None:
        with tempfile.TemporaryDirectory(prefix="hermes-cn-layout-") as directory:
            archive = Path(directory) / "runtime.zip"
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr("hermes-agent-cn-runtime-win32-x64.exe", "contract")
                bundle.writestr("_internal/base_library.zip", "contract")
            with zipfile.ZipFile(archive) as bundle:
                names = set(bundle.namelist())
            self.assertIn("hermes-agent-cn-runtime-win32-x64.exe", names)
            self.assertIn("_internal/base_library.zip", names)
            self.assertNotIn(
                "hermes-agent-cn-runtime-win32-x64/hermes-agent-cn-runtime-win32-x64.exe",
                names,
            )


if __name__ == "__main__":
    unittest.main()
