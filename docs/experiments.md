# Автоэксперименты

Модуль `app/experiments` реализует простую in-memory «БД» для A/B-тестов с четырьмя таблицами:

- `experiments` — сущность эксперимента (ключ, гипотеза, статус, метрика, пороги);
- `variants` — варианты внутри эксперимента (код A/B, описание, payload);
- `assignments` — назначения пользователей на варианты;
- `metrics` — события метрик (conversion flag или другое числовое значение).

## Автоматический цикл

Планировщик (`app/jobs/experiments.py`) каждую 5 минут делает цикл:

1. Запускает следующий эксперимент с низкой базовой конверсией (`baseline_conversion < 0.2`).
2. Ждёт минимальный рантайм (30 минут) и накопление сэмпла (`min_sample` из шаблона, по умолчанию 80 на вариант).
3. Считает p-value двухдолейным Z-тестом и применяет поправку Бонферрони по числу активных тестов.
4. Отправляет админу результат в Telegram: `B +11 %(p = 0.03)` для победителя или «остановлен без победителя».

Тумблер `EXPERIMENTS_ENABLED` в `app/config.py` отключает всё.

## Рантайм API

- `assign_user(user_id, experiment_key)` — назначает вариант (A/B) и возвращает объект `Variant`.
- `track_metric(user_id, experiment_key, metric, value)` — записывает событие метрики.
- `get_active_experiments()` / `get_experiment_status()` — возвращают прогресс для админ-панели.

## Админская команда

Команда `/experiments` (файл `bot/admin_experiments.py`) выводит список активных тестов с числом назначений и конверсией по каждому варианту.

## Как протестировать

1. Поднимите бота локально и убедитесь, что `EXPERIMENTS_ENABLED=True`.
2. Создайте эксперимент «welcome text» (он есть в каталоге по умолчанию) и запустите трафик:

```python
from app.experiments.runtime import assign_user, track_metric

for user_id in range(1, 161):
    variant = assign_user(user_id, "welcome_text")
    # эмулируем конверсию — у варианта B она выше на 10 п.п.
    success = 1 if variant.code == "B" and user_id % 2 == 0 else 0
    track_metric(user_id, "welcome_text", "quiz_start", success)
```

3. Дождитесь выполнения `experiments_cycle` (через 5 минут или вызовите вручную) — админ получит отчёт вида `B +11 %(p = 0.03)`.
