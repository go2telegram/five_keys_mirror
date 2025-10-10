"""Lightweight smoke coverage for PDF plan rendering."""

from __future__ import annotations

from unittest.mock import MagicMock

from app import pdf_report


def _ensure_register_url(monkeypatch) -> None:
    monkeypatch.setattr(pdf_report.settings, "BASE_REGISTER_URL", "https://example.com/register", raising=False)


def test_build_pdf_minimal_plan(monkeypatch):
    _ensure_register_url(monkeypatch)
    monkeypatch.setattr(pdf_report, "prepare_cards", MagicMock(return_value=[]))
    monkeypatch.setattr(pdf_report, "render_product_text", MagicMock(return_value=("Header", [])))

    payload = pdf_report.build_pdf(
        title="План",
        subtitle="",
        actions=None,
        products=[],
        notes="",
        footer="",
        recommended_products=None,
        context=None,
    )

    assert isinstance(payload, bytes)
    assert len(payload) > 1000


def test_build_pdf_full_plan(monkeypatch):
    _ensure_register_url(monkeypatch)

    def fake_prepare(codes, context=None):  # noqa: D401 - test helper
        assert codes == ["OMEGA3"]
        assert context == "energy"
        return [
            {
                "code": "OMEGA3",
                "name": "Омега",
                "short": "",
                "props": ["баланс гормонов"],
                "images": [],
                "order_url": "https://example.com/product",
                "helps_text": "Помогает поддерживать тонус",
            }
        ]

    def fake_render(card, ctx):  # noqa: D401 - test helper
        assert card["code"] == "OMEGA3"
        assert ctx == "energy"
        return "<b>OMEGA3</b>", ["Линия 1", "Линия 2"]

    monkeypatch.setattr(pdf_report, "prepare_cards", fake_prepare)
    monkeypatch.setattr(pdf_report, "render_product_text", fake_render)

    payload = pdf_report.build_pdf(
        title="Персональный план",
        subtitle="Формула энергии",
        actions=["Шаг 1", "Шаг 2"],
        products=["<b>OMEGA3</b> — поддерживает сердце"],
        notes="Наблюдай за самочувствием.",
        footer="Five Keys",
        intake_rows=[{"name": "OMEGA3", "morning": True, "day": False, "evening": True, "note": "по инструкции"}],
        order_url="https://example.com/order",
        channel_note="Подключайся к сообществу",
        recommended_products=["OMEGA3"],
        context="energy",
    )

    assert isinstance(payload, bytes)
    assert len(payload) > 1000
