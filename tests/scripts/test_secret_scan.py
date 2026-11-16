import importlib.util
import sys
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "secret_scan", Path(__file__).resolve().parents[2] / "scripts" / "secret_scan.py"
)
secret_scan = importlib.util.module_from_spec(_spec)
sys.modules["secret_scan"] = secret_scan
_spec.loader.exec_module(secret_scan)


def test_detects_gemini_and_google_keys():
    key = "AQ." + "A" * 40
    assert secret_scan.scan_text("x.py", f'k = "{key}"')[0].rule == "gemini_auth_key"
    assert secret_scan.scan_text("y.py", "AIza" + "B" * 35)


def test_env_files_blocked_but_templates_allowed(monkeypatch):
    monkeypatch.setattr(secret_scan, "_read_blob", lambda path, staged: "")
    blocked = secret_scan.scan_paths([".env", "deploy/.env.prod", ".env.local"], staged=False)
    assert {f.path for f in blocked} == {".env", "deploy/.env.prod", ".env.local"}
    assert secret_scan.scan_paths([".env.example", "deploy/.env.prod.example"], staged=False) == []


def test_inline_allow_marker_skips_only_that_line():
    text = 'SECRET = "test-secret-0123456789abcdef"  # secret-scan: allow
token = "abcdefghijklmnopqrstuvwxyz123456"
'
    findings = secret_scan.scan_text("t.py", text)
    assert [f.line for f in findings] == [2]
