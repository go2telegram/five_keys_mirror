"""Utilities for validating partner order links and their UTM parameters."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Iterable, Sequence
from urllib.parse import parse_qs, urlparse

import aiohttp

from app.catalog.loader import load_catalog


@dataclass(slots=True)
class PartnerLink:
    """Descriptor of a partner order URL coming from the catalog."""

    product_id: str
    title: str
    url: str
    utm: dict[str, str]


@dataclass(slots=True)
class PartnerLinkCheckResult:
    """Result of validating a partner link."""

    link: PartnerLink
    status: int
    final_url: str | None
    error: str | None
    utm_issues: list[str]

    @property
    def ok(self) -> bool:
        """Return ``True`` when the link passed the checks without issues."""

        return (
            self.error is None
            and 200 <= self.status < 400
            and not self.utm_issues
        )


def collect_partner_links() -> list[PartnerLink]:
    """Load catalog products and return partner order links."""

    catalog = load_catalog()
    products = catalog.get("products", {}) if isinstance(catalog, dict) else {}
    links: list[PartnerLink] = []
    for pid, meta in products.items():
        if not isinstance(meta, dict):
            continue
        order = meta.get("order") or {}
        url_raw = order.get("velavie_link") or order.get("url")
        if not isinstance(url_raw, str) or not url_raw.strip():
            continue
        title = (
            meta.get("title")
            or meta.get("name")
            or meta.get("id")
            or str(pid)
        )
        utm_meta = order.get("utm") if isinstance(order.get("utm"), dict) else {}
        utm = {str(k): str(v) for k, v in utm_meta.items() if v is not None}
        links.append(
            PartnerLink(
                product_id=str(pid),
                title=title,
                url=url_raw.strip(),
                utm=utm,
            )
        )
    return links


def _parse_query(url: str | None) -> dict[str, str]:
    if not url:
        return {}
    try:
        parsed = urlparse(url)
    except Exception:
        return {}
    params: dict[str, str] = {}
    query_map = parse_qs(parsed.query, keep_blank_values=True)
    for key, values in query_map.items():
        if not values:
            continue
        value = values[0]
        if value is None:
            continue
        params[str(key)] = str(value)
    return params


def _validate_utms(link: PartnerLink, final_url: str | None) -> list[str]:
    expected = {k: v for k, v in link.utm.items() if v not in (None, "")}
    original = _parse_query(link.url)
    final = _parse_query(final_url)
    issues: list[str] = []

    if expected:
        for key, expected_value in expected.items():
            orig_value = original.get(key)
            final_value = final.get(key)
            if final_value:
                value = final_value
                present_after_redirect = True
            else:
                value = orig_value
                present_after_redirect = False
            if not value:
                issues.append(f"utm {key} отсутствует")
                continue
            if value != expected_value:
                issues.append(
                    f"utm {key}={value} (ожидали {expected_value})"
                )
            elif final_url and not present_after_redirect:
                issues.append(f"utm {key} потерян после редиректа")
    else:
        present_keys = {
            key
            for key in (*original.keys(), *final.keys())
            if key.startswith("utm_")
        }
        if not present_keys:
            issues.append("utm-параметры отсутствуют")

    return sorted(dict.fromkeys(issues))


async def _head_with_fallback(session: aiohttp.ClientSession, url: str) -> tuple[int, str | None]:
    async with session.head(url, allow_redirects=True) as response:
        status = response.status
        final_url = str(response.url)
    if status == 405:
        async with session.get(url, allow_redirects=True) as response:
            status = response.status
            final_url = str(response.url)
    return status, final_url


async def verify_partner_link(
    link: PartnerLink,
    *,
    session: aiohttp.ClientSession | None = None,
    timeout: aiohttp.ClientTimeout | None = None,
) -> PartnerLinkCheckResult:
    own_session = False
    if session is None:
        session = aiohttp.ClientSession(timeout=timeout or aiohttp.ClientTimeout(total=8))
        own_session = True

    status = -1
    final_url: str | None = None
    error: str | None = None
    try:
        status, final_url = await _head_with_fallback(session, link.url)
    except Exception as exc:  # pragma: no cover - network/environment errors
        error = str(exc)
    finally:
        if own_session:
            await session.close()

    utm_issues = [] if error else _validate_utms(link, final_url)

    return PartnerLinkCheckResult(
        link=link,
        status=status,
        final_url=final_url,
        error=error,
        utm_issues=utm_issues,
    )


async def check_partner_links(links: Iterable[PartnerLink] | None = None) -> list[PartnerLinkCheckResult]:
    items = list(links) if links is not None else collect_partner_links()
    if not items:
        return []

    timeout = aiohttp.ClientTimeout(total=8)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        tasks = [verify_partner_link(link, session=session) for link in items]
        results = await asyncio.gather(*tasks)
    return list(results)


def filter_partner_issues(results: Sequence[PartnerLinkCheckResult]) -> list[PartnerLinkCheckResult]:
    """Return only the problematic partner link results."""

    return [result for result in results if not result.ok]


__all__ = [
    "PartnerLink",
    "PartnerLinkCheckResult",
    "check_partner_links",
    "collect_partner_links",
    "filter_partner_issues",
    "verify_partner_link",
]
