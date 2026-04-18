#!/usr/bin/env python3
"""Rotate MinIO STS credentials for Unity Catalog local config.

This script performs the full local workflow:
1. Call MinIO STS AssumeRole using long-lived bootstrap credentials.
2. Update s3.accessKey.0 / s3.secretKey.0 / s3.sessionToken.0 in uc-conf/server.properties.
3. Optionally validate the temp credentials with an S3 list call.
4. Optionally restart the unitycatalog service via docker compose.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict


def run_cmd(
    cmd: list[str], env: Dict[str, str] | None = None, cwd: Path | None = None
) -> str:
    completed = subprocess.run(
        cmd,
        check=False,
        capture_output=True,
        text=True,
        env=env,
        cwd=str(cwd) if cwd else None,
    )
    if completed.returncode != 0:
        stderr = completed.stderr.strip()
        stdout = completed.stdout.strip()
        detail = stderr if stderr else stdout
        raise RuntimeError(f"Command failed ({' '.join(cmd)}): {detail}")
    return completed.stdout


def update_property(text: str, key: str, value: str, newline: str) -> str:
    pattern = re.compile(rf"^{re.escape(key)}=.*$", re.MULTILINE)
    replacement = f"{key}={value}"
    if pattern.search(text):
        return pattern.sub(replacement, text, count=1)
    suffix = "" if text.endswith(("\n", "\r")) else newline
    return f"{text}{suffix}{replacement}{newline}"


def update_server_properties(
    config_path: Path,
    access_key: str,
    secret_key: str,
    session_token: str,
) -> None:
    original = config_path.read_text(encoding="utf-8")
    newline = "\r\n" if "\r\n" in original else "\n"

    updated = original
    updated = update_property(updated, "s3.accessKey.0", access_key, newline)
    updated = update_property(updated, "s3.secretKey.0", secret_key, newline)
    updated = update_property(updated, "s3.sessionToken.0", session_token, newline)

    config_path.write_text(updated, encoding="utf-8", newline="")


def mask(value: str, visible: int = 4) -> str:
    if len(value) <= visible * 2:
        return "*" * len(value)
    return f"{value[:visible]}...{value[-visible:]}"


def parse_args() -> argparse.Namespace:
    repo_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(
        description="Rotate MinIO STS credentials for Unity Catalog config."
    )
    parser.add_argument(
        "--config",
        default=str(repo_root / "uc-conf" / "server.properties"),
        help="Path to UC server.properties",
    )
    parser.add_argument(
        "--minio-endpoint", default="http://localhost:9000", help="MinIO endpoint URL"
    )
    parser.add_argument("--region", default="us-east-1", help="AWS region value")
    parser.add_argument(
        "--role-arn",
        default="arn:aws:iam::minio:user/admin",
        help="AssumeRole ARN for MinIO",
    )
    parser.add_argument(
        "--duration-seconds", type=int, default=3600, help="STS credential lifetime"
    )
    parser.add_argument(
        "--session-name-prefix",
        default="uc-session",
        help="AssumeRole session name prefix",
    )
    parser.add_argument(
        "--bootstrap-access-key",
        default=os.getenv("MINIO_ROOT_USER", "admin"),
        help="Long-lived MinIO access key",
    )
    parser.add_argument(
        "--bootstrap-secret-key",
        default=os.getenv("MINIO_ROOT_PASSWORD", "password"),
        help="Long-lived MinIO secret key",
    )
    parser.add_argument(
        "--bucket", default="warehouse", help="Bucket used for validation"
    )
    parser.add_argument(
        "--compose-service", default="unitycatalog", help="Compose service to restart"
    )
    parser.add_argument(
        "--project-dir",
        default=str(repo_root),
        help="Project directory containing docker-compose.yml",
    )
    parser.add_argument(
        "--no-validate",
        action="store_true",
        help="Skip S3 validation with temp credentials",
    )
    parser.add_argument(
        "--no-restart", action="store_true", help="Skip docker compose service restart"
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    config_path = Path(args.config).resolve()
    project_dir = Path(args.project_dir).resolve()

    if not config_path.exists():
        print(f"Config file not found: {config_path}", file=sys.stderr)
        return 2

    session_name = f"{args.session_name_prefix}-{int(time.time())}"

    assume_env = os.environ.copy()
    assume_env["AWS_ACCESS_KEY_ID"] = args.bootstrap_access_key
    assume_env["AWS_SECRET_ACCESS_KEY"] = args.bootstrap_secret_key
    assume_env["AWS_DEFAULT_REGION"] = args.region

    print("Requesting STS credentials from MinIO...")
    assume_out = run_cmd(
        [
            "aws",
            "--endpoint-url",
            args.minio_endpoint,
            "sts",
            "assume-role",
            "--role-arn",
            args.role_arn,
            "--role-session-name",
            session_name,
            "--duration-seconds",
            str(args.duration_seconds),
            "--output",
            "json",
        ],
        env=assume_env,
    )

    payload = json.loads(assume_out)
    creds = payload.get("Credentials", {})
    access_key = creds.get("AccessKeyId")
    secret_key = creds.get("SecretAccessKey")
    session_token = creds.get("SessionToken")
    expiration = creds.get("Expiration", "unknown")

    if not access_key or not secret_key or not session_token:
        print("AssumeRole returned incomplete credentials payload.", file=sys.stderr)
        return 3

    update_server_properties(
        config_path=config_path,
        access_key=access_key,
        secret_key=secret_key,
        session_token=session_token,
    )
    print(f"Updated credentials in {config_path}")

    if not args.no_validate:
        print(f"Validating temporary credentials against s3://{args.bucket}...")
        validate_env = os.environ.copy()
        validate_env["AWS_ACCESS_KEY_ID"] = access_key
        validate_env["AWS_SECRET_ACCESS_KEY"] = secret_key
        validate_env["AWS_SESSION_TOKEN"] = session_token
        validate_env["AWS_DEFAULT_REGION"] = args.region
        run_cmd(
            [
                "aws",
                "--endpoint-url",
                args.minio_endpoint,
                "s3",
                "ls",
                f"s3://{args.bucket}",
            ],
            env=validate_env,
        )
        print("Validation succeeded.")

    if not args.no_restart:
        print(f"Restarting compose service: {args.compose_service}...")
        run_cmd(
            ["docker", "compose", "up", "-d", args.compose_service], cwd=project_dir
        )
        print("Service restart requested.")

    print("Done.")
    print(f"Access key: {mask(access_key)}")
    print(f"Expires at: {expiration}")
    print(
        "Note: This file is tracked by git; keep skip-worktree enabled locally if needed."
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
