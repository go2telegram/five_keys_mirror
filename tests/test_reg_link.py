from app.handlers import reg


def _flatten(markup):
    return [btn for row in markup.inline_keyboard for btn in row]


def test_registration_markup_contains_discount_button(monkeypatch):
    url = "https://velavie.example/offer"
    monkeypatch.setattr(reg.settings, "VELAVIE_URL", url)
    markup = reg._build_reg_markup(url)
    urls = [btn.url for btn in _flatten(markup) if btn.url]
    assert url in urls
    callbacks = [btn.callback_data for btn in _flatten(markup) if btn.callback_data]
    assert "home:main" in callbacks
