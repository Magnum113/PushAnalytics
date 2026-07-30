from __future__ import annotations

import re
import subprocess
from pathlib import Path

from mindbox_delta import load_env


ROOT = Path(__file__).resolve().parents[2]
SECRET_KEYS = {
    "NEXT_PUBLIC_SUPABASE_ANON_KEY",
    "PUSH_ANALYTICS_ADMIN_KEY",
    "SECRET_KEY",
    "SHIFR_KEY",
    "SUPABASE_DB_PASSWORD",
    "SUPABASE_KEY",
    "SUPABASE_SERVICE_ROLE_KEY",
    "SUPABASE_STUDIO_PASSWORD",
    "VITE_SUPABASE_PUBLISHABLE_KEY",
}
TEXT_SUFFIXES = {
    ".css",
    ".html",
    ".js",
    ".json",
    ".md",
    ".mjs",
    ".py",
    ".sql",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".yaml",
    ".yml",
}
OBVIOUS_SECRET_PATTERNS = {
    "jwt": re.compile(rb"\beyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\."),
    "credential_url": re.compile(
        rb"\b(?:postgres(?:ql)?|https?)://[^/\s:@]+:[^/\s@]{8,}@"
    ),
    "secret_assignment": re.compile(
        rb"(?im)^\s*(?:"
        rb"SECRET_KEY|SHIFR_KEY|SUPABASE_(?:KEY|DB_PASSWORD|SERVICE_ROLE_KEY|"
        rb"STUDIO_PASSWORD)|NEXT_PUBLIC_SUPABASE_ANON_KEY|"
        rb"VITE_SUPABASE_PUBLISHABLE_KEY|PUSH_ANALYTICS_ADMIN_KEY"
        rb")\s*[:=]\s*[\"']?([^\s\"'#,}]{12,})"
    ),
}


def repository_text_files() -> list[Path]:
    result = subprocess.run(
        [
            "git",
            "ls-files",
            "--cached",
            "--others",
            "--exclude-standard",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return [
        ROOT / relative_path
        for relative_path in result.stdout.splitlines()
        if (ROOT / relative_path).suffix.casefold() in TEXT_SUFFIXES
        and relative_path != ".env"
    ]


def test_local_secret_values_are_not_present_in_repository_files() -> None:
    env = load_env()
    secrets = {
        key: value.encode()
        for key, value in env.items()
        if key in SECRET_KEYS
        and len(value) >= 12
        and value.casefold() not in {"ci-placeholder", "change-me"}
    }
    if not secrets:
        return

    leaked_keys: set[str] = set()
    for path in repository_text_files():
        payload = path.read_bytes()
        leaked_keys.update(
            key
            for key, secret_value in secrets.items()
            if secret_value in payload
        )
    assert not leaked_keys, (
        "Repository files contain configured secret values for keys: "
        f"{sorted(leaked_keys)}"
    )


def test_repository_has_no_obvious_embedded_credentials() -> None:
    findings: list[str] = []
    for path in repository_text_files():
        payload = path.read_bytes()
        for pattern_name, pattern in OBVIOUS_SECRET_PATTERNS.items():
            for match in pattern.finditer(payload):
                assigned_value = match.group(1) if match.lastindex else b""
                if assigned_value.startswith((b"$", b"process.env", b"os.environ")):
                    continue
                if assigned_value.lower() in {b"ci-placeholder", b"change-me"}:
                    continue
                findings.append(f"{path.relative_to(ROOT)}:{pattern_name}")
    assert not findings, f"Possible embedded credentials: {sorted(findings)}"
