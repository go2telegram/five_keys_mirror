# Контентный конвейер: квизы → калькуляторы → рекомендации

Документ описывает минимальный набор шагов, чтобы за 15 минут подготовить новый
квиз, собрать теги и получить обновлённые рекомендации в боте.

## 1. Добавляем квиз

1. Создайте YAML-файл в `app/quiz/data`. Ближайший пример — `energy.yaml`.
2. Укажите `title`, список `questions` и результаты в блоке `result.thresholds`.
3. В каждом варианте ответа (`options`) и в итоговых порогах (`thresholds`) можно
   перечислять теги (`tags`). Они пополнят пользовательский профиль и будут
   использованы движком рекомендаций.
4. Если к квизу нужны иллюстрации:
   - положите локальные файлы в `app/static/images/quiz/<quiz-name>/`;
   - либо пропишите `cover`/`image` с удалённой ссылкой на CDN (по умолчанию
     используется репозиторий `go2telegram/media`).
5. Запустите быстрый валидатор ассетов:
   ```bash
   poetry run python tools/validate_quiz_assets.py --quiz <quiz-name>
   ```
6. Обновите `app/handlers/quiz_<quiz>.py` или создайте новый по шаблону — это
   всего несколько строк, см. уже существующие обработчики.

## 2. Настраиваем новые правила рекомендаций

1. Добавьте описание тегов в `app/reco/tag_ontology.yaml`. Для каждого тега укажите
   `title`, `description`, `group` и источники (`sources`).
2. Создайте/обновите правила в `app/reco/tag_product_map.yaml`:
   - `match.tags` — веса для совпадающих тегов; они нормируются автоматом.
   - `threshold` — минимальная доля совпадений (0…1).
   - `audience` — необязательные множители для конкретных аудиторий (`any`/`all`).
   - `freshness` — базовый коэффициент и полу-распад по дням (`decay_days`).
   - `exclude_tags`/`exclude_allergens` — когда продукт нужно скрыть.
3. Убедитесь, что каждая запись ссылается на существующий продукт из
   `app/catalog/products.json`.
4. Запустите валидатор карты:
   ```bash
   poetry run python tools/validate_reco_map.py
   ```
   Сообщение `✅ Recommendation map OK: 38 products covered.` означает успех.

## 3. Проверяем, что всё строится

1. **Каталог** — собрать карточки и сверить отчёт:
   ```bash
   poetry run python tools/build_products.py
   poetry run python tools/catalog_diff.py  # опционально, если нужно сравнение
   ```
2. **Рекомендации** — локально прогнать сценарии:
   ```bash
   poetry run python -m pytest tests/test_reco_engine.py
   poetry run python tools/validate_reco_map.py
   ```
   Дополнительно можно посмотреть живой топ по тегам:
   ```bash
   poetry run python - <<'PY'
   from app.reco import RecommendationEngine, RecommendationRequest

   engine = RecommendationEngine()
   req = RecommendationRequest(tags=["energy", "mitochondria", "tonus"], include_explain=True)
   result = engine.recommend(req)
   for card in result.cards:
       print(f"{card.product_id}: {card.score:.2f}")
   PY
   ```
3. **Отчёты по каталогу/калькуляторам** — убедиться, что боты видят актуальные
   данные:
   ```bash
   poetry run python -m pytest tests/test_catalog_report.py
   poetry run python -m pytest tests/test_calc_basic.py tests/test_calc_water_kcal_macros.py
   ```
4. **Полный прогон** — команда `poetry run python -m pytest` остаётся главным
   чекпоинтом перед деплоем.

## 4. Переменные окружения

| Переменная              | Назначение                                                     |
| ----------------------- | -------------------------------------------------------------- |
| `BOT_TOKEN`             | Токен бота; в offline-режиме можно оставить пустым.            |
| `DATABASE_URL`          | Подключение к БД; для локальных тестов можно использовать SQLite. |
| `QUIZ_IMAGE_MODE`       | `remote` (по умолчанию) или `local` для отладки картинок квизов. |
| `QUIZ_IMG_BASE`         | Базовый URL для удалённых изображений (когда `remote`).        |
| `VELAVIE_URL`           | Общая ссылка на витрину, используется в CTA-кнопках.          |
| `RUN_TRIBUTE_WEBHOOK`   | Включает внешний вебхук; выключайте для локального режима.    |
| `WEB_PORT` / `WEB_HOST` | Настройки встроенного aiohttp-сервера.                         |

### Offline-режим

Для офлайна достаточно:

1. Завести `.env` с фиктивным `BOT_TOKEN` и `DATABASE_URL=sqlite+aiosqlite:///./dev.db`.
2. Запустить `poetry install` и далее `poetry run python -m pytest`.
3. Если нужны ручные проверки — `poetry run python run.py` поднимет бота с
   отключенным вебхуком (используются значения `WEB_HOST`/`WEB_PORT`).

### Online-режим

1. Пропишите реальные креденшелы (`BOT_TOKEN`, `DATABASE_URL`, `REDIS_URL`).
2. Выставьте `RUN_TRIBUTE_WEBHOOK=1`, чтобы aiohttp-приложение слушало входящие
   запросы.
3. Сборка/деплой должны запускать `poetry run python tools/validate_reco_map.py`
   и `pytest` в CI, чтобы гарантировать корректность рекомендаций.

---

Готово! Теперь команда может быстро расширять квизы и добавлять новые продукты,
не рискуя поломать логику рекомендаций.
