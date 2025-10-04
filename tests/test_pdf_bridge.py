from importlib.util import find_spec

import pytest

pytestmark = pytest.mark.skipif(find_spec("reportlab") is None, reason="reportlab not installed")


def test_build_pdf_handles_recommended_products(monkeypatch):
    pdf_report = pytest.importorskip("app.pdf_report")

    def fake_prepare(products, context=None):
        assert products == ["CODE"]
        assert context == "energy"
        return [
            {
                "name": "Test Product",
                "short": "Краткое описание",
                "props": ["Свойство"],
                "images": [],
                "order_url": "https://example.com",
                "helps_text": "Поддержка энергии",
            }
        ]

    def fake_render(card, ctx):
        return "<b>— Test Product</b>", ["Свойство", "<i>Как поможет сейчас:</i> Поддержка энергии"]

    monkeypatch.setattr(pdf_report, "prepare_cards", fake_prepare)
    monkeypatch.setattr(pdf_report, "render_product_text", fake_render)

    pdf_bytes = pdf_report.build_pdf(
        title="Тест",
        subtitle="",
        actions=None,
        products=[],
        notes="",
        footer="",
        recommended_products=["CODE"],
        context="energy",
    )

    assert isinstance(pdf_bytes, bytes)
    assert len(pdf_bytes) > 100
