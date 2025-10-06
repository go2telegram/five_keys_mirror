"""External integration connectors.

This module implements a lightweight abstraction around external data sinks
such as Google Sheets, Notion databases and generic webhook sinks.  Each
connector is responsible for validating its configuration, exporting payloads
and reporting rich status objects that can later be surfaced in the bot's
administrative UI.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Iterable, Mapping, Optional

import httpx

try:  # Optional dependency — the module gracefully degrades without it.
    from google.oauth2.service_account import Credentials as ServiceAccountCredentials
    from google.auth.transport.requests import Request as GoogleAuthRequest
except Exception:  # pragma: no cover - fallback when google-auth is not installed
    ServiceAccountCredentials = None  # type: ignore[assignment]
    GoogleAuthRequest = None  # type: ignore[assignment]


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ExportResult:
    """Normalized result returned by connectors."""

    ok: bool
    message: str
    url: Optional[str] = None
    details: Optional[Mapping[str, Any]] = None


class ConnectorError(RuntimeError):
    """Raised when a connector fails to execute the request."""


class BaseConnector:
    """Base class for all integration connectors."""

    slug: str = "base"

    def __init__(self, enabled: bool = True):
        self.enabled = enabled

    async def export(self, dataset: str, payload: Iterable[Mapping[str, Any]], **kwargs: Any) -> ExportResult:
        raise NotImplementedError

    async def import_data(self, dataset: str, **kwargs: Any) -> Iterable[Mapping[str, Any]]:
        raise NotImplementedError


class GoogleSheetsConnector(BaseConnector):
    """Connector that exports payloads to Google Sheets using service accounts."""

    slug = "google_sheets"
    _scopes = ("https://www.googleapis.com/auth/spreadsheets",)

    def __init__(self, credentials_json: str | None):
        super().__init__(enabled=bool(credentials_json))
        self._credentials_raw = credentials_json
        self._credentials = None
        self._init_error: Optional[str] = None
        if credentials_json:
            try:
                self._credentials = self._load_credentials(credentials_json)
            except Exception as exc:  # pragma: no cover - defensive
                logger.exception('Failed to initialize Google Sheets connector')
                self._init_error = str(exc)
                self.enabled = False

    def _load_credentials(self, credentials_json: str):
        if ServiceAccountCredentials is None:
            raise ConnectorError("google-auth is required for Google Sheets integration")
        try:
            info = json.loads(credentials_json)
        except json.JSONDecodeError:
            # Treat the value as a path to a JSON file
            with open(credentials_json, "r", encoding="utf-8") as fp:
                info = json.load(fp)
        credentials = ServiceAccountCredentials.from_service_account_info(info, scopes=self._scopes)
        return credentials

    async def _get_access_token(self) -> str:
        if self._credentials is None:
            raise ConnectorError("Google Sheets connector is not configured")
        if GoogleAuthRequest is None:
            raise ConnectorError("google-auth is required for Google Sheets integration")

        def _refresh_token() -> str:
            credentials = self._credentials.with_scopes(self._scopes)
            request = GoogleAuthRequest()
            credentials.refresh(request)
            return credentials.token

        return await asyncio.to_thread(_refresh_token)

    async def export(self, dataset: str, payload: Iterable[Mapping[str, Any]], **kwargs: Any) -> ExportResult:
        if not self.enabled:
            if self._init_error:
                return ExportResult(False, f'Настройки Google Sheets некорректны: {self._init_error}')
            return ExportResult(False, "Google Sheets connector is disabled")

        if dataset != "leads":
            return ExportResult(False, f"Dataset '{dataset}' is not supported by Google Sheets connector")

        leads = list(payload)
        if not leads:
            return ExportResult(False, "Нет данных для экспорта")

        try:
            token = await self._get_access_token()
        except Exception as exc:  # pragma: no cover - network dependency
            logger.exception("Failed to obtain Google OAuth token")
            return ExportResult(False, f"Не удалось получить токен Google: {exc}")

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        spreadsheet_title = kwargs.get("title") or f"Leads export {datetime.utcnow():%Y-%m-%d %H:%M}"
        create_payload = {"properties": {"title": spreadsheet_title}}

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                resp = await client.post(
                    "https://sheets.googleapis.com/v4/spreadsheets",
                    json=create_payload,
                    headers=headers,
                )
                resp.raise_for_status()
                sheet_data = resp.json()
                spreadsheet_id = sheet_data.get("spreadsheetId")
                spreadsheet_url = sheet_data.get("spreadsheetUrl")
            except httpx.HTTPError as exc:
                logger.exception("Failed to create spreadsheet in Google Sheets")
                return ExportResult(False, f"Ошибка создания таблицы: {exc}")

            values = [
                ["timestamp", "name", "phone", "comment", "username", "user_id"],
            ]
            for lead in leads:
                values.append([
                    lead.get("ts", ""),
                    lead.get("name", ""),
                    lead.get("phone", ""),
                    lead.get("comment", ""),
                    lead.get("username", ""),
                    str(lead.get("user_id", "")),
                ])

            range_ref = f"Sheet1!A1:F{len(values)}"
            update_url = (
                f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}/values/{range_ref}"
                "?valueInputOption=RAW"
            )

            try:
                resp = await client.put(update_url, json={"values": values}, headers=headers)
                resp.raise_for_status()
            except httpx.HTTPError as exc:
                logger.exception("Failed to upload leads to Google Sheets")
                return ExportResult(False, f"Не удалось выгрузить данные: {exc}")

        return ExportResult(True, "Экспорт завершен", url=spreadsheet_url, details={"rows": len(values) - 1})


class NotionConnector(BaseConnector):
    """Connector for pushing content into a Notion database."""

    slug = "notion"

    def __init__(self, token: str | None):
        super().__init__(enabled=bool(token))
        self._token = token
        self._api_url = "https://api.notion.com/v1"
        self._version = "2022-06-28"

    async def export(
        self,
        dataset: str,
        payload: Iterable[Mapping[str, Any]],
        *,
        database_id: Optional[str] = None,
        **_: Any,
    ) -> ExportResult:
        if not self.enabled:
            return ExportResult(False, "Notion connector is disabled")
        if not database_id:
            return ExportResult(False, "Не указан идентификатор базы Notion")
        if dataset != "leads":
            return ExportResult(False, f"Dataset '{dataset}' is not supported by Notion connector")

        leads = list(payload)
        if not leads:
            return ExportResult(False, "Нет данных для экспорта")

        headers = {
            "Authorization": f"Bearer {self._token}",
            "Notion-Version": self._version,
            "Content-Type": "application/json",
        }

        created_pages = 0
        async with httpx.AsyncClient(timeout=30.0) as client:
            for lead in leads:
                notion_payload = {
                    "parent": {"database_id": database_id},
                    "properties": {
                        "Name": {
                            "title": [
                                {"text": {"content": lead.get("name") or lead.get("username") or "Без имени"}}
                            ]
                        },
                        "Phone": {
                            "rich_text": [{"text": {"content": lead.get("phone", "")}}]
                        },
                        "Comment": {
                            "rich_text": [{"text": {"content": lead.get("comment", "")}}]
                        },
                        "Telegram": {
                            "url": f"https://t.me/{lead.get('username')}" if lead.get("username") else None
                        },
                        "User ID": {
                            "rich_text": [{"text": {"content": str(lead.get("user_id", ""))}}]
                        },
                        "Timestamp": {
                            "date": {"start": lead.get("ts") or datetime.utcnow().isoformat()}
                        },
                    },
                }
                try:
                    resp = await client.post(
                        f"{self._api_url}/pages",
                        headers=headers,
                        json=notion_payload,
                    )
                    resp.raise_for_status()
                    created_pages += 1
                except httpx.HTTPError as exc:
                    logger.exception("Failed to export lead to Notion")
                    return ExportResult(False, f"Ошибка экспорта в Notion: {exc}")

        return ExportResult(True, "Экспорт завершен", details={"pages": created_pages})


class WebhookSinkConnector(BaseConnector):
    """Connector that dumps payload to an HTTP endpoint."""

    slug = "webhook_sink"

    def __init__(self, url: str | None):
        super().__init__(enabled=bool(url))
        self._url = url

    async def export(
        self,
        dataset: str,
        payload: Iterable[Mapping[str, Any]],
        *,
        url: Optional[str] = None,
        **_: Any,
    ) -> ExportResult:
        target_url = url or self._url
        if not target_url:
            return ExportResult(False, "Webhook URL не настроен")
        if not self.enabled and url is None:
            return ExportResult(False, "Webhook connector is disabled")

        data = {
            "dataset": dataset,
            "exported_at": datetime.utcnow().isoformat(),
            "items": list(payload),
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                resp = await client.post(target_url, json=data)
                resp.raise_for_status()
            except httpx.HTTPError as exc:
                logger.exception("Failed to send payload to webhook sink")
                return ExportResult(False, f"Ошибка отправки вебхука: {exc}")

        return ExportResult(True, "Данные отправлены", url=target_url, details={"items": len(data["items"])})


class IntegrationManager:
    """Factory and registry for integration connectors."""

    def __init__(self, connectors: Mapping[str, BaseConnector], enabled: bool = True):
        self._connectors = {name: connector for name, connector in connectors.items() if connector.enabled}
        self._all_connectors = dict(connectors)
        self.enabled = enabled

    @classmethod
    def from_settings(cls, settings: Any) -> "IntegrationManager":
        connectors: Dict[str, BaseConnector] = {}

        google_connector = GoogleSheetsConnector(getattr(settings, "GDRIVE_CREDENTIALS", None))
        connectors[google_connector.slug] = google_connector

        notion_connector = NotionConnector(getattr(settings, "NOTION_TOKEN", None))
        connectors[notion_connector.slug] = notion_connector

        webhook_connector = WebhookSinkConnector(getattr(settings, "WEBHOOK_SINK_URL", None))
        connectors[webhook_connector.slug] = webhook_connector

        enabled = bool(getattr(settings, "ENABLE_EXTERNAL_INTEGRATIONS", False))
        return cls(connectors, enabled=enabled)

    def get(self, slug: str) -> Optional[BaseConnector]:
        return self._all_connectors.get(slug)

    def list_enabled(self) -> Dict[str, BaseConnector]:
        return dict(self._connectors)

    async def export(self, slug: str, dataset: str, payload: Iterable[Mapping[str, Any]], **kwargs: Any) -> ExportResult:
        if not self.enabled:
            return ExportResult(False, "Внешние интеграции отключены")

        connector = self.get(slug)
        if connector is None:
            return ExportResult(False, f"Неизвестный коннектор '{slug}'")
        if not connector.enabled and slug not in {"webhook_sink"}:
            return ExportResult(False, f"Коннектор '{slug}' не настроен")

        try:
            return await connector.export(dataset, payload, **kwargs)
        except Exception as exc:  # pragma: no cover - network dependent
            logger.exception("Unhandled connector error")
            return ExportResult(False, f"Ошибка коннектора '{slug}': {exc}")


__all__ = [
    "ExportResult",
    "IntegrationManager",
    "GoogleSheetsConnector",
    "NotionConnector",
    "WebhookSinkConnector",
]
