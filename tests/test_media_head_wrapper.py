from pathlib import Path

from tools.audit_sections import AuditContext
from tools.audit_sections import check_media_urls

ROOT = Path(__file__).resolve().parents[1]


def test_media_head_check_respects_no_net(tmp_path):
    ctx = AuditContext(root=ROOT, reports_dir=tmp_path, fast=False, ci=False, no_net=True)
    result = check_media_urls.run(ctx)
    assert result.status == "skip"
    assert "NO_NET" in result.summary
