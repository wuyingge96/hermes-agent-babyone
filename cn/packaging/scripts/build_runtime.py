#!/usr/bin/env python3
"""Build a standalone PyInstaller runtime from one Hermes commit.

The default mode performs a real build. ``--check-only`` validates the exact
source, overlay metadata, spec inputs, and PyInstaller availability without
running the expensive freeze step.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path


def run(command: list[str], *, cwd: Path | None = None) -> None:
    print("+", " ".join(command))
    subprocess.run(command, cwd=cwd, check=True)


def origin_url(repo: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), "remote", "get-url", "origin"],
        check=True,
        capture_output=True,
        text=True,
    )
    value = result.stdout.strip()
    # Local mirrors such as gh-proxy wrap the canonical GitHub URL. Keep the
    # provenance useful to a release reviewer instead of recording the mirror.
    prefix = "https://gh-proxy.com/"
    if value.startswith(prefix):
        value = value[len(prefix) :]
    return value.removesuffix(".git")


def load_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected an object: {path}")
    return value


def validate_freeze_inputs(stage_dir: Path, config_path: Path) -> None:
    config = load_json(config_path)
    packages = config.get("data_packages", [])
    if not isinstance(packages, list) or not all(isinstance(item, str) for item in packages):
        raise ValueError(f"data_packages must be a list of strings: {config_path}")
    missing = [
        package
        for package in packages
        if not (stage_dir / Path(package.replace(".", "/"))).exists()
    ]
    if missing:
        raise ValueError(
            "freeze config references packages missing from the selected source: "
            + ", ".join(missing)
        )


def validate_build_python(python_executable: Path, config_path: Path) -> None:
    config = load_json(config_path)
    policy = config.get("python", {})
    if not isinstance(policy, dict):
        raise ValueError(f"python policy must be an object: {config_path}")
    minimum = tuple(int(part) for part in str(policy.get("minimum", "3.14")).split(".", 2))
    maximum = tuple(int(part) for part in str(policy.get("maximum", "3.15")).split(".", 2))
    version = tuple(
        int(part)
        for part in subprocess.check_output(
            [str(python_executable), "-c", "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"],
            text=True,
        ).strip().split(".")
    )
    if version < minimum or version >= maximum:
        raise RuntimeError(
            f"selected Python {version[0]}.{version[1]} is outside the runtime policy "
            f">={minimum[0]}.{minimum[1]}, <{maximum[0]}.{maximum[1]}"
        )


def validate_build_dependencies(python_executable: Path, config_path: Path) -> None:
    config = load_json(config_path)
    dependencies = config.get("build_dependencies", [])
    if not isinstance(dependencies, list) or not all(isinstance(item, str) for item in dependencies):
        raise ValueError(f"build_dependencies must be a list of strings: {config_path}")
    missing = []
    for module in dependencies:
        result = subprocess.run(
            [str(python_executable), "-c", f"import {module.replace('-', '_')}"],
            capture_output=True,
            text=True,
        )
        if result.returncode:
            missing.append(module)
    if missing:
        raise RuntimeError(
            "selected Python is missing build/runtime dependencies: "
            + ", ".join(missing)
            + "; install the exact Hermes runtime dependencies before freezing"
        )


def detect_build_target(python_executable: Path, repo: Path) -> tuple[str, str]:
    command = (
        "import json; "
        "from hermes_platform.host.facts import os_family, process_arch; "
        "print(json.dumps([os_family(), process_arch()]))"
    )
    detected = json.loads(subprocess.check_output(
        [str(python_executable), "-c", command], cwd=repo, text=True,
    ))
    platform, process_arch = detected
    arch = {"amd64": "x64", "arm64": "arm64"}.get(process_arch)
    if platform not in {"win32", "darwin"} or arch is None:
        raise RuntimeError(f"unsupported build Python target: {platform}/{process_arch}")
    return platform, arch


def resolve_target(requested_platform: str, requested_arch: str, detected: tuple[str, str]) -> tuple[str, str]:
    platform, arch = detected
    if requested_platform not in {"auto", platform}:
        raise ValueError(f"--platform {requested_platform} does not match build Python: {platform}")
    if requested_arch not in {"auto", arch}:
        raise ValueError(f"--arch {requested_arch} does not match build Python: {arch}")
    return platform, arch


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[3])
    parser.add_argument("--build-root", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--platform", default="auto")
    parser.add_argument("--arch", default="auto")
    parser.add_argument("--python", dest="python_executable", default=sys.executable)
    parser.add_argument("--source-repo", default=None)
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    repo = args.repo_root.resolve()
    python_executable = Path(args.python_executable).expanduser().resolve()
    if not python_executable.is_file():
        raise FileNotFoundError(f"selected Python executable does not exist: {python_executable}")
    source_repo = args.source_repo or origin_url(repo)
    build_root = (args.build_root or repo / ".cn-build" / "runtime").resolve()
    output_dir = (args.output_dir or build_root / "artifacts").resolve()
    platform, arch = resolve_target(
        args.platform, args.arch, detect_build_target(python_executable, repo)
    )
    artifact_base = f"hermes-agent-cn-runtime-{platform}-{arch}"
    stage_dir = build_root / "staged-source"
    dist_dir = build_root / "dist"
    work_dir = build_root / "work"

    stage_script = repo / "cn" / "packaging" / "scripts" / "stage_source.py"
    spec_file = repo / "cn" / "packaging" / "runtime.spec"
    imports_file = repo / "cn" / "packaging" / "config" / "frozen_imports.json"
    for required in (stage_script, spec_file, imports_file):
        if not required.is_file():
            raise FileNotFoundError(required)

    run(
        [
            str(python_executable),
            str(stage_script),
            "--source-commit",
            args.source_commit,
            "--output",
            str(stage_dir),
            "--repo-root",
            str(repo),
            "--force",
        ]
    )
    metadata = load_json(stage_dir / "cn-build-inputs.json")
    if metadata.get("source_commit") is None or metadata.get("catalog_sha256") is None:
        raise ValueError("staging metadata is missing source provenance")
    validate_freeze_inputs(stage_dir, stage_dir / "cn/packaging/config/frozen_imports.json")
    validate_build_python(python_executable, stage_dir / "cn/packaging/config/frozen_imports.json")
    validate_build_dependencies(python_executable, stage_dir / "cn/packaging/config/frozen_imports.json")

    if args.check_only:
        module_available = subprocess.run(
            [str(python_executable), "-c", "import PyInstaller"],
            capture_output=True,
            text=True,
        ).returncode == 0
        print(json.dumps({
            "ok": True,
            "source_commit": metadata["source_commit"],
            "stage_dir": str(stage_dir),
            "platform": platform,
            "arch": arch,
            "pyinstaller_available": module_available,
            "next_step": (
                "rerun without --check-only after installing PyInstaller"
                if not module_available
                else "rerun without --check-only"
            ),
        }, indent=2, sort_keys=True))
        return 0

    pyinstaller_command = [str(python_executable), "-m", "PyInstaller"]
    if subprocess.run([str(python_executable), "-c", "import PyInstaller"], capture_output=True).returncode != 0:
        raise RuntimeError(
            "PyInstaller is not installed for the selected Python; "
            "use --check-only or install it"
        )
    if output_dir.exists() and args.force:
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    for directory in (dist_dir, work_dir):
        if directory.exists() and args.force:
            shutil.rmtree(directory)
        directory.mkdir(parents=True, exist_ok=True)

    run(
        pyinstaller_command
        + [
            "--noconfirm",
            "--clean",
            "--distpath",
            str(dist_dir),
            "--workpath",
            str(work_dir),
            str(stage_dir / "cn" / "packaging" / "runtime.spec"),
        ],
        cwd=stage_dir,
    )
    generated = dist_dir / "hermes-agent-cn-runtime"
    if not generated.is_dir():
        raise FileNotFoundError(f"PyInstaller did not create onedir output: {generated}")
    final_runtime = output_dir / artifact_base
    if final_runtime.exists():
        if not args.force:
            raise FileExistsError(final_runtime)
        shutil.rmtree(final_runtime)
    shutil.copytree(generated, final_runtime)

    executable = final_runtime / (artifact_base + (".exe" if platform == "win32" else ""))
    source_candidates = [
        final_runtime / "hermes-agent-cn-runtime",
        final_runtime / "hermes-agent-cn-runtime.exe",
    ]
    source_executable = next((path for path in source_candidates if path.is_file()), None)
    if source_executable and source_executable != executable:
        source_executable.rename(executable)
    if not executable.is_file():
        raise FileNotFoundError(f"runtime executable missing: {executable}")

    archive_path = output_dir / f"{artifact_base}.zip"
    archive_stem = output_dir / artifact_base
    shutil.make_archive(str(archive_stem), "zip", root_dir=final_runtime)
    if not archive_path.is_file():
        raise FileNotFoundError(archive_path)
    project_version = "0.0.0"
    pyproject = stage_dir / "pyproject.toml"
    if pyproject.is_file():
        project = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        project_version = str(project.get("project", {}).get("version", project_version))
    runtime_version = (
        f"{project_version}-cn.{metadata['source_commit'][:12]}.r{metadata['packaging_revision']}"
    )
    manifest_path = output_dir / f"stable-{platform}-{arch}.json"
    run(
        [
            str(python_executable),
            str(repo / "cn/packaging/scripts/write_manifest.py"),
            "--archive",
            str(archive_path),
            "--staging-metadata",
            str(stage_dir / "cn-build-inputs.json"),
            "--output",
            str(manifest_path),
            "--platform",
            platform,
            "--arch",
            arch,
            "--runtime-version",
            runtime_version,
            "--kernel-version",
            project_version,
            "--source-repo",
            source_repo,
        ]
    )
    print(json.dumps({
        "ok": True,
        "artifact": str(archive_path),
        "manifest": str(manifest_path),
        "runtime_dir": str(final_runtime),
        "source_commit": metadata["source_commit"],
        "platform": platform,
        "arch": arch,
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
