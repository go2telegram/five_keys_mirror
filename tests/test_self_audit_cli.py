import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "build" / "reports"


def test_self_audit_fast_creates_reports(monkeypatch):
    if REPORT_DIR.exists():
        shutil.rmtree(REPORT_DIR)

    monkeypatch.setenv("SELF_AUDIT_SKIP_MIGRATIONS", "1")
    monkeypatch.setenv("SELF_AUDIT_SKIP_CATALOG", "1")
    monkeypatch.setenv("SELF_AUDIT_SKIP_TESTS", "1")
    monkeypatch.setenv("SELF_AUDIT_OFFLINE_ONLY", "1")
    monkeypatch.setenv("NO_NET", "1")

    cmd = [sys.executable, "tools/self_audit.py", "--fast", "--no-net"]
    result = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True)
    assert result.returncode == 0, (result.stdout or "") + (result.stderr or "")

    markdown_path = REPORT_DIR / "self_audit.md"
    json_path = REPORT_DIR / "self_audit.json"
    timings_path = REPORT_DIR / "timings.json"

    assert markdown_path.exists()
    assert json_path.exists()
    assert timings_path.exists()

    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data["metadata"]["fast"] is True
    sections = data["sections"]
    assert sections["migrations"]["status"] == "skip"
    assert sections["catalog"]["status"] == "skip"
    assert sections["tests"]["status"] == "skip"
