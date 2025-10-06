# Самооптимизация конфигураций

Модуль `optimizer/config_tuner.py` отвечает за адаптивную настройку параметров
под текущую нагрузку. Он использует ленивый grid-search: перебирает
комбинации параметров (batch size, таймауты, лимиты памяти), собирает
метрики и выбирает конфигурацию, которая даёт прирост производительности
минимум на 10 %.

## Как это работает

1. **Сбор метрик.** `jobs/config_optimize.py` раз в `OPTIMIZER_INTERVAL_SECONDS`
   подтягивает `/metrics` (поддерживается Prometheus-формат и JSON).
2. **Обновление истории.** `ConfigTuner` ведёт историю результатов в файле
   `optimizer/config_tuner_state.json` и пишет подробный лог в
   `optimizer/config_tuner.log`.
3. **Применение настроек.** Лучшие параметры сохраняются в
   `optimizer/runtime_config.json`. Актуальные значения доступны через
   `app.config.get_runtime_config()`.
4. **Откат.** Переменная окружения `ENABLE_SELF_OPTIMIZATION=false` отключает
   задачу APScheduler, можно удалить `optimizer/runtime_config.json` для
   возврата к дефолтным значениям.

## Настройка

| Переменная | Назначение | По умолчанию |
|------------|------------|--------------|
| `ENABLE_SELF_OPTIMIZATION` | Включает задачу подбора конфигураций | `false` |
| `OPTIMIZER_INTERVAL_SECONDS` | Интервал запуска job (сек.) | `300` |
| `OPTIMIZER_REQUIRED_IMPROVEMENT` | Минимальный прирост, чтобы зафиксировать конфигурацию | `0.1` |
| `OPTIMIZER_MIN_SAMPLES` | Кол-во выборок метрик на конфигурацию | `3` |
| `OPTIMIZER_BATCH_CHOICES` | Список допустимых batch-size | `4,8,16` |
| `OPTIMIZER_TIMEOUT_CHOICES` | Список таймаутов (мс) | `8000,12000,16000` |
| `OPTIMIZER_MEMORY_CHOICES` | Допустимые лимиты памяти (МБ) | `512,768,1024` |
| `OPTIMIZER_TARGET_LATENCY_MS` | Целевая латентность для расчёта score | `1200` |
| `OPTIMIZER_MEMORY_BUDGET_MB` | Мягкий потолок потребления памяти | `1024` |
| `OPTIMIZER_METRICS_URL` | Endpoint для сбора метрик | `http://localhost:8000/metrics` |
| `OPTIMIZER_HTTP_TIMEOUT` | Таймаут HTTP-запроса метрик | `2.0` |

## Проверка и мониторинг

* Проверяйте `optimizer/config_tuner.log` — там видно, какую конфигурацию и
  почему применили.
* `/metrics` и `/version` должны оставаться доступными.
* Для тестирования под нагрузкой достаточно дергать `/metrics` в ответ на
  нагрузочный тест; ConfigTuner адаптирует BATCH_SIZE и TIMEOUT_MS.

## Rollback

Установите `ENABLE_SELF_OPTIMIZATION=false` и перезапустите приложение.
Файл `optimizer/runtime_config.json` можно удалить — при следующем запуске
возьмутся дефолтные значения.
