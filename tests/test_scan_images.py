from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools import scan_images


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "catalog" / "images"


def test_scan_images_from_directory(tmp_path, capsys):
    output = tmp_path / "images_index.json"
    exit_code = scan_images.main(
        ["--images-dir", str(FIXTURE_DIR), "--out", str(output)]
    )
    assert exit_code == 0

    data = json.loads(output.read_text(encoding="utf-8"))
    assert len(data) == 10
    filenames = [item["filename"] for item in data]
    assert filenames == sorted(
        [
            "active-move.jpg",
            "brain_focus.jpg",
            "detox-mix_01.png",
            "fiber_joy.jpg",
            "immuno_guard-main.jpeg",
            "night-calm.webp",
            "omega3_main.jpg",
            "skin-glow_main.jpg",
            "slimstart.png",
            "t8-blend_main.jpg",
        ]
    )

    detox_mix = next(item for item in data if item["filename"] == "detox-mix_01.png")
    assert detox_mix["stem"] == "detox-mix_01"
    assert detox_mix["slug"] == "detox-mix-01"
    assert detox_mix["variants"] == [
        "detox-mix-01",
        "detoxmix01",
        "detox_mix_01",
        "detox-mix",
        "detoxmix",
        "detox_mix",
    ]

    omega_main = next(item for item in data if item["filename"] == "omega3_main.jpg")
    assert omega_main["variants"] == ["omega3-main", "omega3main", "omega3_main", "omega3"]

    captured = capsys.readouterr()
    assert "WARNING" in captured.err
    assert "found 10" in captured.err


def test_scan_images_requires_source():
    with pytest.raises(scan_images.ScanImagesError):
        scan_images.scan_images(images_dir=FIXTURE_DIR, images_url="https://example.com")


def test_parse_github_tree_url():
    location = scan_images._parse_github_tree_url(
        "https://github.com/example/repo/tree/main/media/products"
    )
    assert location.owner == "example"
    assert location.repo == "repo"
    assert location.ref == "main"
    assert location.path == "media/products"
