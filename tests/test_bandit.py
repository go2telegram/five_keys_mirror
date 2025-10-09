from __future__ import annotations

import random

from app.experiments.bandit import EpsilonGreedyBandit, BanditError


def test_bandit_select_prefers_best_arm():
    rng = random.Random(123)
    bandit = EpsilonGreedyBandit(epsilon=0.0, rng=rng)
    bandit.ensure_arm("a").shows = 10
    bandit.ensure_arm("a").clicks = 1
    bandit.ensure_arm("b").shows = 10
    bandit.ensure_arm("b").clicks = 5
    chosen = bandit.select()
    assert chosen.name == "b"


def test_bandit_record_updates_stats():
    rng = random.Random(1)
    bandit = EpsilonGreedyBandit(epsilon=0.5, rng=rng)
    bandit.ensure_arm("x")
    bandit.record("x", click=True)
    arm = bandit.arms["x"]
    assert arm.shows == 1
    assert arm.clicks == 1
    data = bandit.to_dict()
    assert data["x"]["shows"] == 1
    assert data["x"]["clicks"] == 1


def test_bandit_without_arms_raises():
    bandit = EpsilonGreedyBandit(epsilon=0.0)
    try:
        bandit.select()
    except BanditError:
        pass
    else:
        raise AssertionError("BanditError expected")
