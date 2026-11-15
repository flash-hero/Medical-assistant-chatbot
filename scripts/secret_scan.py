"""Block commits that contain credentials.

Usage:
  python scripts/secret_scan.py --staged      # pre-commit: scan staged blobs
  python scripts/secret_scan.py --all         # CI: scan every tracked file
Exit code 1 when anything matches; matches are reported by file and line, never printed in full.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections.abc import Iterable
from dataclasses import dataclass

PATTERNS: dict[str, re.Pattern[str]] = {
    "gemini_auth_key": re.compile(r"\bAQ\.[A-Za-z0-9_\-]{30,}"),
    "google_api_key": re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b"),
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----"),
    "aws_access_key": re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    "github_token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"),
    "slack_token": re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b"),
    "generic_assignment": re.compile(
        r"(?i)\b(?:api[_-]?key|secret|password|token)\b\s*[:=]\s*['\"][A-Za-z0-9_\-./+=]{24,}['\"]"
    ),
}

# Files that legitimately mention the patterns (docs about the scanner itself).
ALLOWLIST_PATHS = {"scripts/secret_scan.py", "tests/scripts/test_secret_scan.py"}
BLOCKED_FILENAMES = re.compile(r"(^|/)\.env($|\.(?!example$)[^/]+$)")


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    rule: str


def scan_text(path: str, text: str) -> list[Finding]:
    if path in ALLOWLIST_PATHS:
        return []
    findings: list[Finding] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        for rule, pattern in PATTERNS.items():
            if pattern.search(line):
                findings.append(Finding(path=path, line=lineno, rule=rule))
    return findings


def _git(*args: str) -> str:
    return subprocess.run(  # noqa: S603
        ["git", *args], check=True, capture_output=True, text=True, encoding="utf-8", errors="replace"
    ).stdout


def _staged_files() -> list[str]:
    out = _git("diff", "--cached", "--name-only", "--diff-filter=ACMR")
    return [p for p in out.splitlines() if p]


def _tracked_files() -> list[str]:
    return [p for p in _git("ls-files").splitlines() if p]


def _read_blob(path: str, staged: bool) -> str | None:
    try:
        return _git("show", f":{path}") if staged else open(path, encoding="utf-8", errors="replace").read()
    except (subprocess.CalledProcessError, OSError, UnicodeDecodeError):
        return None


def scan_paths(paths: Iterable[str], staged: bool) -> list[Finding]:
    findings: list[Finding] = []
    for path in paths:
        if BLOCKED_FILENAMES.search(path):
            findings.append(Finding(path=path, line=0, rule="env_file_committed"))
            continue
        text = _read_blob(path, staged)
        if text is not None:
            findings.extend(scan_text(path, text))
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--staged", action="store_true")
    group.add_argument("--all", action="store_true")
    args = parser.parse_args(argv)
    paths = _staged_files() if args.staged else _tracked_files()
    findings = scan_paths(paths, staged=args.staged)
    for f in findings:
        print(f"SECRET? {f.path}:{f.line} [{f.rule}]", file=sys.stderr)
    if findings:
        print(f"secret_scan: {len(findings)} finding(s); commit blocked.", file=sys.stderr)
        return 1
    print(f"secret_scan: 0 findings in {len(paths)} file(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
