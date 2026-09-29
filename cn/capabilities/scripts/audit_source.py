#!/usr/bin/env python3
"""Audit an exact Hermes commit against the CN Desktop capability catalog.

This is an evidence inventory, not a runtime proof.  A matching source symbol
is recorded as ``present``; the generated report intentionally leaves the
delivery status as ``audit-required`` until the real contract and packaged
runtime tests pass.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class EvidenceCheck:
    pattern: str
    paths: tuple[str, ...]
    label: str


CHECKS: dict[str, tuple[EvidenceCheck, ...]] = {
    "runtime.startup": (
        EvidenceCheck(r"build_serve_parser|\"serve\"", ("hermes_cli/subcommands/dashboard.py",), "serve command"),
        EvidenceCheck(r"def start_server", ("hermes_cli/web_server.py",), "server entry point"),
        EvidenceCheck(r"/api/status", ("hermes_cli/web_routers/status.py",), "status route"),
    ),
    "runtime.authentication": (
        EvidenceCheck(r"HERMES_DASHBOARD_SESSION_TOKEN", ("hermes_cli/web_server.py", "hermes_cli/env_loader.py"), "dashboard token"),
        EvidenceCheck(r"auth|token", ("hermes_cli/web_routers/chat_ws.py", "hermes_cli/dashboard_auth"), "gateway auth gate"),
    ),
    "gateway.websocket": (
        EvidenceCheck(r"@router\.websocket\(\"/api/ws\"\)", ("hermes_cli/web_routers/chat_ws.py",), "WebSocket route"),
        EvidenceCheck(r"dispatch|handle_request", ("tui_gateway/rpc_dispatch.py", "tui_gateway/server.py"), "RPC dispatch"),
    ),
    "gateway.sessions": (
        EvidenceCheck(r"session\.create", ("tui_gateway",), "session create RPC"),
        EvidenceCheck(r"session\.resume", ("tui_gateway",), "session resume RPC"),
    ),
    "gateway.prompt": (
        EvidenceCheck(r"prompt\.submit", ("tui_gateway",), "prompt submit RPC"),
        EvidenceCheck(r"message\.delta|message\.complete", ("tui_gateway",), "prompt event names"),
    ),
    "gateway.approvals": (
        EvidenceCheck(r"server_request\(\"approval\"\)|send_async\(\"approval\"", ("tui_gateway",), "approval server request"),
        EvidenceCheck(r"approval\.respond", ("tui_gateway",), "approval response"),
    ),
    "gateway.attachments": (
        EvidenceCheck(r"file\.attach", ("tui_gateway",), "file attachment"),
        EvidenceCheck(r"image\.attach", ("tui_gateway",), "image attachment"),
        EvidenceCheck(r"image\.attach_bytes", ("tui_gateway",), "byte image attachment"),
    ),
    "rest.status": (
        EvidenceCheck(r"/api/status", ("hermes_cli/web_routers/status.py",), "status route"),
        EvidenceCheck(r"FastAPI\(", ("hermes_cli/web_server.py",), "OpenAPI application"),
    ),
    "rest.sessions": (
        EvidenceCheck(r"/api/sessions", ("hermes_cli/web_routers/sessions.py",), "session REST routes"),
    ),
    "rest.config": (
        EvidenceCheck(r"/api/config", ("hermes_cli/web_routers/config_env.py",), "config REST routes"),
    ),
    "rest.tools": (
        EvidenceCheck(r"/api/tools/toolsets", ("hermes_cli/web_routers/tools.py",), "legacy toolset route"),
        EvidenceCheck(r"discover_builtin_tools|registered tools", ("model_tools.py", "hermes_cli/web_routers/tools.py"), "tool discovery"),
    ),
    "model.session_header": (
        EvidenceCheck(r"llm_request", ("hermes_cli/middleware.py", "plugins"), "managed request middleware"),
        EvidenceCheck(r"session_id", ("hermes_cli/middleware.py", "run_agent.py", "tui_gateway"), "session context"),
    ),
    "response.media_protocol": (
        EvidenceCheck(r"MEDIA:", ("gateway/run.py", "gateway/platforms/base.py"), "MEDIA extraction"),
        EvidenceCheck(r"MEDIA_TAG_CLEANUP_RE", ("gateway/platforms/base.py",), "MEDIA cleanup"),
    ),
    "skills.catalog": (
        EvidenceCheck(r"commands\.catalog", ("tui_gateway",), "command catalog RPC"),
        EvidenceCheck(r"skills\.reload", ("tui_gateway",), "skills reload RPC"),
    ),
}


def run_git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
    )
    return result.stdout


def resolve_commit(repo: Path, requested: str) -> str:
    return run_git(repo, "rev-parse", "--verify", f"{requested}^{{commit}}").strip()


def git_grep(repo: Path, commit: str, check: EvidenceCheck) -> list[str]:
    command = ["git", "-C", str(repo), "grep", "-n", "-E", check.pattern, commit, "--", *check.paths]
    result = subprocess.run(
        command,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
    )
    if result.returncode not in (0, 1):
        raise RuntimeError(result.stderr.strip() or f"git grep failed for {check.label}")
    return result.stdout.splitlines()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def audit(repo: Path, requested: str, catalog: Path, output: Path) -> dict:
    commit = resolve_commit(repo, requested)
    rows: list[dict] = []
    for capability_id, checks in CHECKS.items():
        evidence: list[dict] = []
        for check in checks:
            matches = git_grep(repo, commit, check)
            evidence.append({
                "label": check.label,
                "pattern": check.pattern,
                "paths": list(check.paths),
                "matches": matches[:8],
                "match_count": len(matches),
            })
        matched = sum(bool(item["matches"]) for item in evidence)
        rows.append({
            "id": capability_id,
            "status": "audit-required",
            "evidence_status": "present" if matched == len(evidence) else ("partial" if matched else "absent"),
            "evidence": evidence,
            "contract_tests": [],
            "patch_id": None,
            "notes": "Static source evidence only; verify with the real client contract and packaged runtime.",
        })

    report = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_request": requested,
        "source_commit": commit,
        "catalog": str(catalog).replace("\\", "/"),
        "catalog_sha256": sha256_file(catalog),
        "audit_kind": "static-source-evidence",
        "capabilities": rows,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-commit", required=True, help="Git commit, tag, or ref to inspect")
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[3])
    parser.add_argument("--catalog", type=Path, default=None, help="Capability catalog (defaults to cn/capabilities/catalog.yaml)")
    parser.add_argument("--output", type=Path, default=None, help="Report path (defaults to cn/capabilities/audits/<sha>.json)")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo = args.repo_root.resolve()
    catalog = (args.catalog or repo / "cn/capabilities/catalog.yaml").resolve()
    commit = resolve_commit(repo, args.source_commit)
    output = (args.output or repo / "cn/capabilities/audits" / f"{commit}.json").resolve()
    report = audit(repo, args.source_commit, catalog, output)
    print(json.dumps({
        "source_commit": report["source_commit"],
        "output": str(output),
        "capabilities": {
            row["id"]: row["evidence_status"] for row in report["capabilities"]
        },
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
