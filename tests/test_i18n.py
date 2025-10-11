from __future__ import annotations

from app import i18n


def test_resolve_locale_with_region(tmp_path, monkeypatch):
    monkeypatch.setattr(i18n, "LOCALES_ROOT", tmp_path)
    (tmp_path / "ru.yaml").write_text("foo: bar", encoding="utf-8")
    (tmp_path / "en.yaml").write_text("foo: baz", encoding="utf-8")
    i18n.clear_cache()
    assert i18n.resolve_locale("en-US") == "en"
    assert i18n.resolve_locale(None) == i18n.DEFAULT_LOCALE
    i18n.clear_cache()


def test_gettext_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr(i18n, "LOCALES_ROOT", tmp_path)
    (tmp_path / "ru.yaml").write_text("greet: Привет", encoding="utf-8")
    (tmp_path / "en.yaml").write_text("greet: Hello", encoding="utf-8")
    i18n.clear_cache()
    assert i18n.gettext("greet", "de") == "Привет"
    assert i18n.gettext("missing", "de") == "missing"
    i18n.clear_cache()
