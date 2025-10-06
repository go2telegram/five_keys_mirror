"""Time-series forecasting utilities for the predictive planner."""
from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

import numpy as np
import pandas as pd
from statsmodels.tsa.holtwinters import ExponentialSmoothing, HoltWintersResultsWrapper

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

SUPPORTED_METRICS: dict[str, str] = {
    "rps": "Запросы в секунду",
    "revenue_total": "Выручка, ₽",
    "error_rate": "Доля ошибок, %",
}

DATA_PATH = Path(__file__).resolve().parent / "data" / "metrics.csv"


@dataclass(slots=True)
class ForecastResult:
    """Result of the forecast pipeline."""

    metric: str
    horizon_days: int
    history: pd.DataFrame
    forecast: pd.DataFrame
    mae_pct: float
    latest_actual: float
    horizon_mean: float
    recommendation: str
    chart_bytes: bytes

    @property
    def summary(self) -> str:
        direction = "+" if self.horizon_mean >= self.latest_actual else "−"
        delta_pct = _safe_pct_change(self.horizon_mean, self.latest_actual)
        return (
            f"📈 Прогноз по {format_metric_name(self.metric)} ({self.horizon_days} д.)\n"
            f"MAE: {self.mae_pct:.1f}%\n"
            f"Текущий уровень: {self.latest_actual:,.2f}\n"
            f"Ожидаемый средний уровень: {self.horizon_mean:,.2f} ({direction}{abs(delta_pct):.1f}%)\n\n"
            f"Рекомендации:\n{self.recommendation}"
        )


class ForecastError(Exception):
    """Raised when a forecast cannot be produced."""


def format_metric_name(metric: str) -> str:
    return SUPPORTED_METRICS.get(metric, metric)


def build_forecast(metric: str, days: int = 7, *, output_path: Optional[Path] = None) -> ForecastResult:
    metric = metric.strip().lower()
    if metric not in SUPPORTED_METRICS:
        raise ForecastError(
            f"Неизвестная метрика '{metric}'. Доступны: {', '.join(SUPPORTED_METRICS)}"
        )

    history = _load_history(metric)
    if len(history) < max(days * 2, 30):
        raise ForecastError("Недостаточно данных для прогноза — нужно хотя бы 30 точек.")

    model, mae_pct = _backtest(history["value"], horizon=min(7, days))
    forecast_df, latest_actual, horizon_mean = _forecast(model, history, days)

    chart_bytes = _render_plot(metric, history, forecast_df, output_path=output_path)
    recommendation = _generate_recommendation(metric, latest_actual, horizon_mean, mae_pct)
    return ForecastResult(
        metric=metric,
        horizon_days=days,
        history=history,
        forecast=forecast_df,
        mae_pct=mae_pct,
        latest_actual=latest_actual,
        horizon_mean=horizon_mean,
        recommendation=recommendation,
        chart_bytes=chart_bytes,
    )


def _load_history(metric: str) -> pd.DataFrame:
    if not DATA_PATH.exists():
        raise ForecastError(
            f"Не найден файл с метриками: {DATA_PATH}. Добавьте данные для обучения."
        )

    df = pd.read_csv(DATA_PATH, parse_dates=["date"])
    if metric not in df.columns:
        raise ForecastError(f"В файле {DATA_PATH.name} нет столбца '{metric}'.")

    series = df[["date", metric]].rename(columns={metric: "value"}).copy()
    series.dropna(inplace=True)
    series.sort_values("date", inplace=True)
    series = series.reset_index(drop=True)
    return series


def _backtest(series: pd.Series, horizon: int) -> tuple[HoltWintersResultsWrapper, float]:
    horizon = max(3, horizon)
    if len(series) <= horizon + 5:
        raise ForecastError("Слишком короткий ряд для оценки точности.")

    train = series.iloc[:-horizon]
    test = series.iloc[-horizon:]

    model = ExponentialSmoothing(
        train,
        trend="add",
        seasonal="add",
        seasonal_periods=7,
        initialization_method="estimated",
    )
    fitted = model.fit(optimized=True)
    pred = fitted.forecast(horizon)
    mae_pct = _mae_pct(test, pred)

    # retrain on full series for actual forecast
    final_model = ExponentialSmoothing(
        series,
        trend="add",
        seasonal="add",
        seasonal_periods=7,
        initialization_method="estimated",
    ).fit(optimized=True)

    return final_model, mae_pct


def _forecast(model: HoltWintersResultsWrapper, history: pd.DataFrame, days: int) -> tuple[pd.DataFrame, float, float]:
    forecast_index = pd.date_range(
        start=history["date"].iloc[-1] + pd.Timedelta(days=1), periods=days, freq="D"
    )
    preds = model.forecast(days)
    residuals = model.resid
    sigma = float(np.std(residuals, ddof=1)) if len(residuals) > 1 else 0.0
    interval = 1.96 * sigma

    forecast_df = pd.DataFrame(
        {
            "date": forecast_index,
            "prediction": preds.values,
            "lower": np.maximum(preds.values - interval, 0.0),
            "upper": preds.values + interval,
        }
    )

    latest_actual = float(history["value"].iloc[-1])
    horizon_mean = float(forecast_df["prediction"].mean())
    return forecast_df, latest_actual, horizon_mean


def _mae_pct(actual: pd.Series, predicted: Iterable[float]) -> float:
    actual = actual.astype(float)
    predicted = np.array(list(predicted), dtype=float)
    mae = np.mean(np.abs(actual.values - predicted))
    baseline = np.mean(np.abs(actual.values)) or 1.0
    return float(mae / baseline * 100.0)


def _safe_pct_change(new: float, old: float) -> float:
    if old == 0:
        return 0.0
    return (new - old) / abs(old) * 100.0


def _generate_recommendation(metric: str, latest: float, expected: float, mae_pct: float) -> str:
    delta_pct = _safe_pct_change(expected, latest)
    delta_significant = abs(delta_pct) >= 3.0

    if metric == "revenue_total":
        if delta_significant and delta_pct > 0:
            advice = [
                "Запланируйте доп. активации рекламных каналов для закрепления роста.",
                "Синхронизируйте акции с пиковыми днями спроса из прогноза.",
            ]
        elif delta_significant and delta_pct < 0:
            advice = [
                "Усилите воронку продаж: прогрейте лиды и запустите допродажи.",
                "Проверьте промокоды и бонусы — актуализируйте офферы на ближайшую неделю.",
            ]
        else:
            advice = [
                "Сохраните текущий медиаплан и держите фокус на конверсии в оплату.",
                "Проверьте сквозную аналитику: отклонения >10% от прогноза — сигнал для корректировок.",
            ]
    elif metric == "rps":
        if delta_significant and delta_pct > 0:
            advice = [
                "Проведите нагрузочное тестирование перед пиками трафика.",
                "Заранее масштабируйте инфраструктуру (авто scaling или увеличение пула воркеров).",
            ]
        elif delta_significant and delta_pct < 0:
            advice = [
                "Используйте освободившуюся мощность для регрессионных тестов и оптимизаций.",
                "Сверьте расписание кампаний маркетинга — возможно, трафик уйдёт на новые каналы.",
            ]
        else:
            advice = [
                "Поддерживайте текущие параметры SLA и мониторинг latency.",
                "Проверьте тревоги на предмет ложных срабатываний во время стабильного периода.",
            ]
    else:  # error_rate
        if delta_significant and delta_pct > 0:
            advice = [
                "Проведите ретроспективу инцидентов и приоритизируйте багфиксы по критичности.",
                "Усилите алерты на рост ошибок >2σ от нормы и подготовьте on-call план.",
            ]
        elif delta_significant and delta_pct < 0:
            advice = [
                "Зафиксируйте улучшения в post-mortem и масштабируйте лучшие практики.",
                "Обновите runbooks, пока метрика в зелёной зоне.",
            ]
        else:
            advice = [
                "Продолжайте соблюдать регламенты деплоя и проверку фич перед релизом.",
                "Сверьте метрики приложения и инфраструктуры, чтобы удержать стабильность.",
            ]

    header = (
        f"Точность прогноза (MAE) — {mae_pct:.1f}%. "
        f"Изменение к текущему уровню: {delta_pct:+.1f}%."
    )
    bullet_list = "\n".join(f"• {line}" for line in advice)
    return f"{header}\n{bullet_list}"


def _render_plot(
    metric: str,
    history: pd.DataFrame,
    forecast: pd.DataFrame,
    *,
    output_path: Optional[Path] = None,
) -> bytes:
    fig, ax = plt.subplots(figsize=(8, 4.2))
    ax.plot(history["date"], history["value"], label="История", color="#1f77b4")
    ax.plot(forecast["date"], forecast["prediction"], label="Прогноз", color="#ff7f0e")
    ax.fill_between(
        forecast["date"],
        forecast["lower"],
        forecast["upper"],
        color="#ff7f0e",
        alpha=0.2,
        label="Доверительный интервал",
    )
    ax.set_title(f"{format_metric_name(metric)} — прогноз на {len(forecast)} дн.")
    ax.set_xlabel("Дата")
    ax.set_ylabel(format_metric_name(metric))
    ax.grid(True, alpha=0.3)
    ax.legend()
    fig.autofmt_xdate()

    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", bbox_inches="tight")
    plt.close(fig)
    buffer.seek(0)

    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "wb") as fh:
            fh.write(buffer.getbuffer())
        buffer.seek(0)

    return buffer.getvalue()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Forecast metrics using Holt-Winters.")
    parser.add_argument("--metric", required=True, help="Metric key (e.g. revenue_total)")
    parser.add_argument("--days", type=int, default=7, help="Forecast horizon in days")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional path for the plot image (PNG)",
    )
    args = parser.parse_args()

    try:
        result = build_forecast(args.metric, args.days, output_path=args.output)
    except ForecastError as exc:
        print(f"⚠️ {exc}")
    else:
        if args.output:
            print(f"График сохранён в {args.output}")
        print(result.summary)
