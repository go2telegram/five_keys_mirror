"""Gamified referral bonuses with anti-fraud protection."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Mapping, Optional, Tuple

LEVELS: List[Tuple[str, int]] = [
    ("Seed", 0),
    ("Sprout", 50),
    ("Bud", 150),
    ("Bloom", 350),
    ("Forest", 700),
]
WEEKLY_CAP = 250  # maximum points a user may earn per rolling 7 days
FRAUD_FINGERPRINT_TOLERANCE = 1


@dataclass(slots=True)
class BonusAward:
    points: int
    reason: str
    ts: datetime
    metadata: Mapping[str, object] = field(default_factory=dict)
    referred_id: Optional[int] = None
    channel: Optional[str] = None


@dataclass(slots=True)
class BonusProfile:
    user_id: int
    points: int = 0
    lifetime_points: int = 0
    level: str = LEVELS[0][0]
    awards: List[BonusAward] = field(default_factory=list)
    flagged: bool = False


_LEDGER: Dict[int, BonusProfile] = {}
# track credited referrals to avoid double counting
_CREDITED_REFERRALS: Dict[int, set[int]] = {}
# fingerprint -> {referrer_ids}
_FINGERPRINT_REGISTRY: Dict[str, set[int]] = {}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _get_profile(user_id: int) -> BonusProfile:
    profile = _LEDGER.get(user_id)
    if profile is None:
        profile = BonusProfile(user_id=user_id)
        _LEDGER[user_id] = profile
    return profile


def _eligible_level(points: int) -> str:
    current = LEVELS[0][0]
    for name, threshold in LEVELS:
        if points >= threshold:
            current = name
        else:
            break
    return current


def _within_week(ts: datetime, now: datetime) -> bool:
    return ts >= now - timedelta(days=7)


def _weekly_points(profile: BonusProfile, now: datetime) -> int:
    return sum(award.points for award in profile.awards if _within_week(award.ts, now))


def _is_duplicate(referrer_id: int, referred_id: Optional[int]) -> bool:
    if referred_id is None:
        return False
    credited = _CREDITED_REFERRALS.setdefault(referrer_id, set())
    if referred_id in credited:
        return True
    credited.add(referred_id)
    return False


def _fingerprint_is_suspicious(referrer_id: int, metadata: Mapping[str, object]) -> bool:
    fingerprint = metadata.get("fingerprint") if metadata else None
    if not fingerprint:
        return False
    owners = _FINGERPRINT_REGISTRY.setdefault(str(fingerprint), set())
    owners.add(referrer_id)
    return len(owners) > FRAUD_FINGERPRINT_TOLERANCE


def _mark_flagged(profile: BonusProfile, reason: str) -> None:
    profile.flagged = True
    profile.awards.append(
        BonusAward(
            points=0,
            reason=f"flagged:{reason}",
            ts=_now(),
            metadata={},
        )
    )


def award_referral_bonus(
    *,
    referrer_id: int,
    referred_id: Optional[int],
    channel: Optional[str],
    base_points: int = 25,
    metadata: Optional[Mapping[str, object]] = None,
) -> tuple[bool, Optional[BonusAward], Optional[str]]:
    """Try to award points for a referral conversion.

    Returns a tuple ``(awarded, award, reason)`` where ``reason`` is provided
    whenever the award was skipped (cap reached, fraud, duplicate, ...).
    """

    profile = _get_profile(referrer_id)
    now = _now()

    if profile.flagged:
        return False, None, "profile_flagged"

    if metadata and metadata.get("fraud"):
        _mark_flagged(profile, "manual")
        return False, None, "manual_flag"

    if _fingerprint_is_suspicious(referrer_id, metadata or {}):
        _mark_flagged(profile, "fingerprint")
        return False, None, "fingerprint"

    if _is_duplicate(referrer_id, referred_id):
        return False, None, "duplicate"

    earned_this_week = _weekly_points(profile, now)
    if earned_this_week >= WEEKLY_CAP:
        return False, None, "weekly_cap"

    remaining_cap = WEEKLY_CAP - earned_this_week
    points = min(base_points, remaining_cap)
    award = BonusAward(
        points=points,
        reason="referral_conversion",
        ts=now,
        metadata=dict(metadata or {}),
        referred_id=referred_id,
        channel=channel,
    )
    profile.points += points
    profile.lifetime_points += points
    profile.awards.append(award)
    profile.level = _eligible_level(profile.lifetime_points)
    return True, award, None


def get_bonus_profile(user_id: int) -> BonusProfile:
    return _get_profile(user_id)


def get_leaderboard(top: int = 10) -> List[BonusProfile]:
    return sorted(_LEDGER.values(), key=lambda prof: prof.lifetime_points, reverse=True)[:top]


def get_digest_snapshot(*, window: timedelta) -> Dict[str, object]:
    now = _now()
    cutoff = now - window
    conversions = 0
    total_points = 0
    top_channels: Dict[str, int] = {}
    for profile in _LEDGER.values():
        for award in profile.awards:
            if award.ts < cutoff:
                continue
            if award.points:
                conversions += 1
                total_points += award.points
                if award.channel:
                    top_channels[award.channel] = top_channels.get(award.channel, 0) + 1
    return {
        "awards": conversions,
        "points": total_points,
        "channels": top_channels,
    }
