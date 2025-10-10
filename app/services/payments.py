from __future__ import annotations

import hmac
import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import LabeledPrice, Message

from app.config import settings
from app.db.session import compat_session, session_scope
from app.repo import orders as orders_repo, subscriptions as subscriptions_repo, users as users_repo
from app.storage import commit_safely


_HMAC_SECRET = settings.PREMIUM_HMAC_SECRET or settings.BOT_TOKEN


def _canonical_json(data: Dict[str, Any]) -> str:
    return json.dumps(data, separators=(",", ":"), sort_keys=True, ensure_ascii=False)


def sign_payload(data: Dict[str, Any]) -> str:
    secret = _HMAC_SECRET.encode("utf-8")
    return hmac.new(secret, _canonical_json(data).encode("utf-8"), "sha256").hexdigest()


def verify_signature(payload: Dict[str, Any]) -> str:
    signature = payload.get("signature")
    if not isinstance(signature, str):
        raise ValueError("signature missing")
    base = {k: v for k, v in payload.items() if k != "signature"}
    expected = sign_payload(base)
    if not hmac.compare_digest(signature, expected):
        raise ValueError("invalid signature")
    return signature


@dataclass
class PremiumPlan:
    code: str
    title: str
    description: str
    amount: int
    currency: str
    duration_days: int

    def expires_at(self, start: datetime) -> datetime:
        return start + timedelta(days=self.duration_days)


def premium_plans() -> dict[str, PremiumPlan]:
    currency = settings.PREMIUM_DEFAULT_CURRENCY
    return {
        "basic": PremiumPlan(
            code="basic",
            title="MITO Premium Basic",
            description="Доступ ко всем материалам на 30 дней",
            amount=settings.PREMIUM_BASIC_AMOUNT,
            currency=currency,
            duration_days=settings.PREMIUM_BASIC_DURATION_DAYS,
        ),
        "pro": PremiumPlan(
            code="pro",
            title="MITO Premium Pro",
            description="Расширенный доступ и еженедельные планы",
            amount=settings.PREMIUM_PRO_AMOUNT,
            currency=currency,
            duration_days=settings.PREMIUM_PRO_DURATION_DAYS,
        ),
    }


class TelegramPremiumGateway:
    provider_name = "telegram"

    def __init__(self, bot: Bot):
        self.bot = bot

    async def send_invoice(self, message: Message, plan_code: str = "basic") -> bool:
        plans = premium_plans()
        plan = plans.get(plan_code, plans["basic"])
        if not settings.TELEGRAM_PROVIDER_TOKEN:
            return False

        base_payload = {
            "user_id": message.from_user.id,
            "plan": plan.code,
            "amount": plan.amount,
            "currency": plan.currency,
            "nonce": secrets.token_hex(8),
        }
        signature = sign_payload(base_payload)

        async with compat_session(session_scope) as session:
            await users_repo.get_or_create_user(session, message.from_user.id, message.from_user.username)
            order = await orders_repo.create(
                session,
                user_id=message.from_user.id,
                amount=plan.amount,
                currency=plan.currency,
                product=plan.code,
                provider=self.provider_name,
                payload_json=base_payload,
                payload_hash=signature,
            )
            base_payload["order_id"] = order.id
            signature = sign_payload(base_payload)
            base_payload["signature"] = signature
            order.payload_hash = signature
            await orders_repo.attach_payload(session, order, base_payload)
            await commit_safely(session)

        prices = [LabeledPrice(label=plan.title, amount=plan.amount)]
        try:
            await message.answer_invoice(
                title=plan.title,
                description=plan.description,
                payload=_canonical_json(base_payload),
                provider_token=settings.TELEGRAM_PROVIDER_TOKEN,
                currency=plan.currency,
                prices=prices,
                start_parameter=f"premium_{plan.code}",
            )
        except TelegramBadRequest:
            return False
        return True


async def finalize_successful_payment(
    payload: Dict[str, Any],
    *,
    provider_charge_id: str,
) -> PremiumPlan:
    signature = verify_signature(payload)
    plans = premium_plans()
    plan = plans[payload.get("plan", "basic")]
    async with compat_session(session_scope) as session:
        order = await orders_repo.get_by_payload_hash(session, signature)
        if order is None:
            raise ValueError("order not found")
        await orders_repo.update_status(session, order, "paid")
        await users_repo.get_or_create_user(session, payload["user_id"], None)
        current = await subscriptions_repo.get(session, payload["user_id"])
        if current and current.txn_id == provider_charge_id:
            await commit_safely(session)
            return plan
        await subscriptions_repo.set_plan(
            session,
            user_id=payload["user_id"],
            plan=plan.code,
            days=plan.duration_days,
            status=subscriptions_repo.STATUS_ACTIVE,
            provider=TelegramPremiumGateway.provider_name,
            txn_id=provider_charge_id,
        )
        await commit_safely(session)
    return plan
