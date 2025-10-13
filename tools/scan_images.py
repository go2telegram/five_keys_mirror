#!/usr/bin/env python3
"""Build an index of catalog product images for offline and online sources."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, Sequence
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from slugify import slugify  # noqa: E402

EXPECTED_IMAGE_COUNT = 38
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
DEFAULT_IMAGES_DIR = ROOT / "app" / "static" / "images" / "products"
GITHUB_API_BASE = "https://api.github.com"
GITHUB_ACCEPT_HEADER = "application/vnd.github+json"


class ScanImagesError(RuntimeError):
    """Raised when images cannot be scanned."""


@dataclass(frozen=True)
class GithubLocation:
    owner: str
    repo: str
    ref: str
    path: str


@dataclass(frozen=True)
class GithubEntry:
    name: str
    path: str
    type: str
    download_url: str | None


def _http_get(url: str) -> bytes:
    request = Request(
        url, headers={"User-Agent": "five-keys-bot/scan-images", "Accept": GITHUB_ACCEPT_HEADER}
    )
    try:
        with urlopen(request) as response:  # type: ignore[arg-type]
            return response.read()
    except OSError as exc:  # pragma: no cover - surfaced as ScanImagesError
        raise ScanImagesError(f"Failed to fetch {url}: {exc}") from exc


def _parse_github_tree_url(url: str) -> GithubLocation:
    parts = urlsplit(url)
    if parts.netloc.lower() != "github.com":
        raise ScanImagesError("Only github.com URLs are supported for --images-url")
    segments = [segment for segment in parts.path.split("/") if segment]
    if len(segments) < 5 or segments[2] != "tree":
        raise ScanImagesError(
            "Expected a GitHub tree URL like https://github.com/<owner>/<repo>/tree/<ref>/<path>"
        )
    owner, repo, _, ref, *path_segments = segments
    path = "/".join(path_segments)
    return GithubLocation(owner=owner, repo=repo, ref=ref, path=path)


def _github_contents_url(location: GithubLocation, path: str) -> str:
    quoted_path = quote(path, safe="/")
    return f"{GITHUB_API_BASE}/repos/{location.owner}/{location.repo}/contents/{quoted_path}?ref={location.ref}"


def _load_github_directory(location: GithubLocation, path: str | None = None) -> list[GithubEntry]:
    target_path = location.path if path is None else path
    url = _github_contents_url(location, target_path)
    payload = json.loads(_http_get(url))
    entries: list[GithubEntry] = []
    if isinstance(payload, dict):
        payload = [payload]
    if not isinstance(payload, list):
        raise ScanImagesError(f"Unexpected GitHub API response for {url}")
    for item in payload:
        if not isinstance(item, dict):
            continue
        entry = GithubEntry(
            name=str(item.get("name", "")),
            path=str(item.get("path", "")),
            type=str(item.get("type", "")),
            download_url=item.get("download_url"),
        )
        entries.append(entry)
    return entries


def _iter_github_files(location: GithubLocation, path: str | None = None) -> Iterator[GithubEntry]:
    for entry in _load_github_directory(location, path):
        if entry.type == "dir":
            yield from _iter_github_files(location, entry.path)
        elif entry.type == "file":
            yield entry


def _list_remote_images(images_url: str) -> list[str]:
    location = _parse_github_tree_url(images_url)
    filenames: set[str] = set()
    for entry in _iter_github_files(location):
        extension = Path(entry.name).suffix.lower()
        if extension in IMAGE_EXTENSIONS:
            filenames.add(entry.name)
    return sorted(filenames)


def _list_local_images(images_dir: Path) -> list[str]:
    if not images_dir.exists() or not images_dir.is_dir():
        raise ScanImagesError(f"Images directory does not exist: {images_dir}")
    filenames: set[str] = set()
    for file in images_dir.rglob("*"):
        if not file.is_file():
            continue
        extension = file.suffix.lower()
        if extension in IMAGE_EXTENSIONS:
            filenames.add(file.name)
    return sorted(filenames)


def _is_suffix_token(token: str) -> bool:
    if token in {"main", "front", "back", "side", "preview"}:
        return True
    return bool(re.fullmatch(r"\d+[a-z]?", token))


def _iter_trimmed_tokens(tokens: list[str]) -> Iterator[list[str]]:
    index = len(tokens)
    while index > 0:
        current = tokens[:index]
        yield current
        if not _is_suffix_token(current[-1]):
            break
        index -= 1


def _generate_variants(slug: str) -> list[str]:
    variants: list[str] = []
    if not slug:
        return variants
    tokens = slug.split("-")
    for trimmed in _iter_trimmed_tokens(tokens):
        hyphenated = "-".join(trimmed)
        for candidate in (hyphenated, hyphenated.replace("-", ""), hyphenated.replace("-", "_")):
            if candidate and candidate not in variants:
                variants.append(candidate)
    return variants


def _build_records(filenames: Iterable[str]) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for filename in sorted(filenames):
        stem = Path(filename).stem
        slug = slugify(stem, lowercase=True)
        variants = _generate_variants(slug)
        records.append(
            {
                "filename": filename,
                "stem": stem,
                "slug": slug,
                "variants": variants,
            }
        )
    return records


def scan_images(
    *, images_dir: Path | None = None, images_url: str | None = None
) -> list[dict[str, object]]:
    if images_url and images_dir:
        raise ScanImagesError("Specify only one of --images-dir or --images-url")
    if not images_url and not images_dir:
        images_dir = DEFAULT_IMAGES_DIR
    if images_url:
        filenames = _list_remote_images(images_url)
    else:
        assert images_dir is not None
        filenames = _list_local_images(images_dir)
    return _build_records(filenames)


def _write_output(path: Path, records: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(records, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def _emit_warning_if_needed(records: Sequence[dict[str, object]]) -> None:
    count = len(records)
    if count == EXPECTED_IMAGE_COUNT:
        return
    filenames = ", ".join(record["filename"] for record in records)
    print(
        f"WARNING: expected {EXPECTED_IMAGE_COUNT} images, found {count}. Files: {filenames}",
        file=sys.stderr,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scan catalog product images")
    parser.add_argument(
        "--images-dir", type=Path, help="Path to local images directory", default=None
    )
    parser.add_argument("--images-url", help="URL of GitHub directory with images", default=None)
    parser.add_argument("--out", type=Path, required=True, help="Path to output JSON index")
    args = parser.parse_args(argv)

    try:
        if args.images_url and args.images_dir:
            raise ScanImagesError("Specify only one of --images-dir or --images-url")
        records = scan_images(images_dir=args.images_dir, images_url=args.images_url)
    except ScanImagesError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    _write_output(args.out, records)
    _emit_warning_if_needed(records)
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    raise SystemExit(main())
