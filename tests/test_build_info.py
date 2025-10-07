from __future__ import annotations

from importlib import reload

from app import build_info


def test_build_info_fields_present() -> None:
    reload(build_info)
    assert isinstance(build_info.GIT_BRANCH, str)
    assert build_info.GIT_BRANCH
    assert isinstance(build_info.GIT_COMMIT, str)
    assert len(build_info.GIT_COMMIT) >= 7
    assert isinstance(build_info.BUILD_TIME, str)
    assert build_info.BUILD_TIME
