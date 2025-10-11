import re
from difflib import SequenceMatcher
from typing import Tuple


def _normalize(text: str) -> str:
    cleaned = re.sub(r"[+\-]", "", text)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip().lower()


def _workflow_heuristic(file_path: str, body: str, file_text: str) -> Tuple[str, str]:
    if ".github/workflows" not in file_path:
        return "", ""
    if "continue-on-error" in body.lower():
        if "continue-on-error: true" in file_text:
            return "present", "Workflow still allows continue-on-error"
        return "absent", "continue-on-error flag not found"
    return "", ""


def _module_call_heuristic(body: str, file_text: str) -> Tuple[str, str]:
    lowered = body.lower()
    if "modulenotfounderror" in lowered or "python tools/" in lowered:
        if "python tools/" in file_text:
            return "present", "Direct python tools/ invocation still present"
        if "python -m tools" in file_text:
            return "absent", "Module invocation uses python -m"
    return "", ""


def _head_check_heuristic(body: str, file_text: str) -> Tuple[str, str]:
    if "wrong type of the web page content" in body.lower():
        if "utils_media.fetch_image_as_file" in file_text:
            return "absent", "fetch_image_as_file helper already used"
        return "present", "fetch_image_as_file helper missing"
    return "", ""


def evaluate_context(
    file_path: str,
    body: str,
    excerpt: str,
    file_text: str,
) -> Tuple[str, str]:
    if not file_text:
        return "absent", "File not present on main"

    heuristics = [
        _workflow_heuristic(file_path, body, file_text),
        _module_call_heuristic(body, file_text),
        _head_check_heuristic(body, file_text),
    ]
    for status, reason in heuristics:
        if status:
            return status, reason

    normalized_file = _normalize(file_text)
    normalized_excerpt = _normalize(excerpt or body)
    if not normalized_excerpt:
        return "manual", "Unable to build excerpt for comparison"

    if normalized_excerpt and normalized_excerpt in normalized_file:
        return "present", "Excerpt found verbatim in file"

    ratio = SequenceMatcher(None, normalized_excerpt, normalized_file).ratio()
    if ratio >= 0.8:
        return "maybe", f"Fuzzy similarity {ratio:.2f}"
    if ratio >= 0.6:
        return "manual", f"Fuzzy similarity {ratio:.2f}"
    return "absent", f"Fuzzy similarity {ratio:.2f}"
