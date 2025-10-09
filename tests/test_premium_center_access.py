from types import SimpleNamespace

import pytest

from app.handlers import premium_center


class DummyMessage:
    def __init__(self, user_id: int):
        self.from_user = SimpleNamespace(id=user_id)
        self.sent: list[tuple[str, object]] = []

    async def answer(self, text: str, reply_markup=None):  # noqa: ANN001 - test stub
        self.sent.append((text, reply_markup))


@pytest.mark.asyncio
async def test_deny_if_not_premium_prompts_upgrade(monkeypatch):
    async def fake_ensure(_user_id: int) -> bool:
        return False

    monkeypatch.setattr(premium_center, "_ensure_premium", fake_ensure)

    message = DummyMessage(user_id=101)
    denied = await premium_center._deny_if_not_premium(message)

    assert denied is True
    assert message.sent
    text, markup = message.sent[0]
    assert "/premium" in text
    assert getattr(markup, "inline_keyboard", None)
    button = markup.inline_keyboard[0][0]
    assert button.callback_data == "premium:info"
