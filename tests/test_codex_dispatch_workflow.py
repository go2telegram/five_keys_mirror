from __future__ import annotations

from pathlib import Path

WORKFLOW_PATH = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "codex_dispatch.yml"


def read_workflow_text() -> str:
    return WORKFLOW_PATH.read_text(encoding="utf-8")


def test_list_publish_content_step_present():
    text = read_workflow_text()
    assert "name: List publish content" in text, "List publish content step is missing"


def test_index_html_always_built():
    text = read_workflow_text()
    assert "- name: Build index.html" in text, "Build index step missing"
    assert "mkdir -p artifacts/menu" in text, "index.html step must create target directory"
    assert "cat > artifacts/menu/index.html" in text, "index.html is not created"
    assert (
        "if: steps.gate.outputs.allowed == 'true'" in text
    ), "Build index step should not depend on render outcome"


def test_logs_include_pages_url():
    text = read_workflow_text()
    assert (
        'echo "Pages URL: ${{ steps.deploy.outputs.page_url }}"' in text
    ), "Pages URL log is missing"


def test_debug_artifact_uploaded():
    text = read_workflow_text()
    assert "codex_dispatch-debug-${{ github.run_id }}" in text, "Debug artifact name changed"
    assert "actions/upload-artifact@v4" in text, "Debug artifact must use upload-artifact"
    assert "if: always()" in text, "Debug artifact upload must run regardless of failures"
