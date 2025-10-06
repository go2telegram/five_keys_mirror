"""Autonomous research engine that runs lightweight experiments daily.

This module keeps the state of currently active hypotheses, simulates AutoAB
experiments and provides a small API that can be used both by the scheduler and
admin interfaces.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import math
import random
from typing import Dict, List, Optional


@dataclasses.dataclass
class VariantResult:
    """Aggregated metrics for a single experiment variant."""

    name: str
    baseline_ctr: float
    sample_size: int = 0
    conversions: int = 0

    @property
    def conversion_rate(self) -> float:
        if self.sample_size == 0:
            return 0.0
        return self.conversions / self.sample_size

    def record(self, participants: int) -> None:
        """Simulate participants flowing through the variant."""
        self.sample_size += participants
        # Lightweight stochastic simulation around the baseline conversion.
        # We perturb the baseline a little so that experiments have variety.
        effective_ctr = max(0.0, min(1.0, random.gauss(self.baseline_ctr, 0.01)))
        self.conversions += sum(
            1 for _ in range(participants) if random.random() < effective_ctr
        )


@dataclasses.dataclass
class Hypothesis:
    """Description of a single autonomous experiment."""

    key: str
    description: str
    metric: str
    created_at: dt.datetime
    variants: Dict[str, VariantResult]
    status: str = "running"  # running | completed
    recommendation: Optional[str] = None
    finished_at: Optional[dt.datetime] = None
    total_runs: int = 0

    def best_variant(self) -> VariantResult | None:
        if not self.variants:
            return None
        return max(self.variants.values(), key=lambda v: v.conversion_rate)

    def total_sample(self) -> int:
        return sum(v.sample_size for v in self.variants.values())


class ResearchEngine:
    """Simple engine that generates hypotheses and runs AutoAB analysis."""

    MIN_SAMPLE_SIZE = 200
    MIN_ABSOLUTE_LIFT = 0.02  # 2pp uplift

    def __init__(self) -> None:
        self._hypotheses: Dict[str, Hypothesis] = {}
        self._history: List[Hypothesis] = []
        self._last_generated: Optional[dt.datetime] = None
        random.seed()

    # ---- Public API -----------------------------------------------------
    def ensure_daily_experiment(self) -> List[str]:
        """
        Run one research cycle.

        Returns a list of notifications (strings) that should be delivered to an
        operator/admin.
        """
        notifications: List[str] = []
        now = dt.datetime.utcnow()

        if self._need_new_hypothesis(now):
            hypo = self._generate_hypothesis(now)
            self._hypotheses[hypo.key] = hypo
            self._last_generated = now
            notifications.append(
                "🧪 Запущена новая гипотеза: "
                f"<b>{hypo.key}</b> — {hypo.description}"
            )

        for hypo in list(self._hypotheses.values()):
            if hypo.status != "running":
                continue

            self._run_autoab_iteration(hypo)
            hypo.total_runs += 1
            decision = self._analyze(hypo)
            if decision:
                hypo.status = "completed"
                hypo.finished_at = dt.datetime.utcnow()
                hypo.recommendation = decision
                self._history.append(hypo)
                del self._hypotheses[hypo.key]
                notifications.append(
                    "🏁 Гипотеза <b>{key}</b> завершена. {decision}".format(
                        key=hypo.key
                    )
                )

        return notifications

    def get_status(self) -> str:
        """Render current and historical experiments for admin UI."""
        now = dt.datetime.utcnow()
        lines: List[str] = []

        if not self._hypotheses:
            lines.append("Активных гипотез нет — ожидаем следующую волну экспериментов.")
        else:
            lines.append("🔬 Активные гипотезы:")
            for hypo in self._hypotheses.values():
                lines.extend(self._render_hypothesis_block(hypo, now))

        if self._history:
            lines.append("")
            lines.append("📚 История завершённых гипотез (последние 5):")
            for hypo in self._history[-5:][::-1]:
                lines.append(
                    f"• {hypo.key} — {hypo.recommendation or 'анализ'}"
                    f" (CR {hypo.best_variant().conversion_rate:.1%})"
                )

        return "\n".join(lines)

    # ---- Internal helpers ----------------------------------------------
    def _need_new_hypothesis(self, now: dt.datetime) -> bool:
        if not self._hypotheses:
            return True
        if not self._last_generated:
            return True
        delta = now.date() - self._last_generated.date()
        return delta.days >= 1

    def _generate_hypothesis(self, now: dt.datetime) -> Hypothesis:
        templates = [
            (
                "optimize_onboarding",
                "Проверяем влияние более короткого онбординга на регистрацию",
                "registration",
            ),
            (
                "vitamin_pitch",
                "Сравниваем tone of voice продаж витаминов", "conversion"
            ),
            (
                "content_format",
                "Тестируем формат контент-подборок", "engagement"
            ),
            (
                "paywall_copy",
                "А/B paywall: прогрев vs жёсткий call-to-action", "payment"
            ),
        ]
        base_key, description, metric = random.choice(templates)
        suffix = now.strftime("%Y%m%d%H%M")
        key = f"{base_key}_{suffix}"

        control_ctr = random.uniform(0.05, 0.18)
        uplift = random.uniform(-0.015, 0.04)
        test_ctr = max(0.01, control_ctr + uplift)

        variants = {
            "control": VariantResult("control", control_ctr),
            "treatment": VariantResult("treatment", test_ctr),
        }

        return Hypothesis(
            key=key,
            description=description,
            metric=metric,
            created_at=now,
            variants=variants,
        )

    def _run_autoab_iteration(self, hypo: Hypothesis) -> None:
        # Lightweight traffic simulation: 40–120 participants per iteration.
        traffic = random.randint(40, 120)
        split = ["control", "treatment"]
        # Keep slight imbalance for realism via random assignment.
        for _ in range(traffic):
            variant = random.choice(split)
            hypo.variants[variant].record(1)

    def _analyze(self, hypo: Hypothesis) -> Optional[str]:
        if hypo.total_sample() < self.MIN_SAMPLE_SIZE:
            return None

        results = list(hypo.variants.values())
        results.sort(key=lambda v: v.conversion_rate, reverse=True)
        winner, runner_up = results[0], results[1]

        lift = winner.conversion_rate - runner_up.conversion_rate
        if lift < self.MIN_ABSOLUTE_LIFT:
            # Not a strong enough lift — keep running but cap iterations.
            if hypo.total_runs >= 7:
                return (
                    "Разницы не нашли — рекомендуем оставить контроль."  # noqa: E501
                )
            return None

        significance = self._approximate_significance(winner, runner_up)
        if significance < 0.8:
            return None

        return (
            f"Победил вариант <b>{winner.name}</b>: CR {winner.conversion_rate:.1%}"
            f" (+{lift:.1%} к {runner_up.name}). Рекомендуем раскатать."
        )

    @staticmethod
    def _approximate_significance(a: VariantResult, b: VariantResult) -> float:
        # Quick z-test approximation between two proportions.
        if a.sample_size == 0 or b.sample_size == 0:
            return 0.0
        p1, p2 = a.conversion_rate, b.conversion_rate
        n1, n2 = a.sample_size, b.sample_size
        p_pool = (a.conversions + b.conversions) / (n1 + n2)
        if p_pool in (0, 1):
            return 1.0
        se = math.sqrt(p_pool * (1 - p_pool) * (1 / n1 + 1 / n2))
        if se == 0:
            return 1.0
        z = abs(p1 - p2) / se
        # Convert z-score to a rough probability (two-tailed).
        # Using error function approximation.
        prob = math.erf(z / math.sqrt(2))
        return min(max(prob, 0.0), 1.0)

    def _render_hypothesis_block(self, hypo: Hypothesis, now: dt.datetime) -> List[str]:
        age = now - hypo.created_at
        lines = [
            f"• <b>{hypo.key}</b> — {hypo.description}",
            f"  Метрика: {hypo.metric}, идёт {age.days} дн.",
        ]
        for variant in hypo.variants.values():
            lines.append(
                "  {name}: n={n}, CR={cr:.1%}".format(
                    name=variant.name,
                    n=variant.sample_size,
                    cr=variant.conversion_rate,
                )
            )
        return lines


engine = ResearchEngine()
