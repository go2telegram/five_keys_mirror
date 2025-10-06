# Каталог продуктов

Каталог бота автоматически собирается из репозитория [`go2telegram/media`](https://github.com/go2telegram/media): описания продуктов хранятся в `media/descriptions/*.txt`, а изображения — в `media/products/`.

## Источник медиа и описаний

- Скрипт использует переменную `DESCRIPTIONS_URL` (по умолчанию файл «Полное описание продуктов vilavi (оформлено v3).txt» в репозитории `media`) и скачивает её в временную директорию `/tmp/catalog_build`.
- Список изображений берётся через GitHub Contents API (`MEDIA_PRODUCTS_API`, по умолчанию `https://api.github.com/repos/go2telegram/media/contents/media/products`).
- Финальные ссылки строятся как `MEDIA_BASE_URL/media/products/<файл>` (значение `MEDIA_BASE_URL` можно переопределить, по умолчанию `https://raw.githubusercontent.com/go2telegram/media/main`).
- В репозиторий бота не нужно добавлять бинарные файлы: `.gitignore` закрывает `media/`, `assets/`, `artifacts/` и служебные артефакты.

## Сборка каталога

1. Обновите описания и изображения в репозитории `go2telegram/media`.
2. Выполните сборку:
   ```bash
   make build-products
   ```
   При необходимости можно указать другой источник: `DESCRIPTIONS_URL="https://...txt" make build-products`.
   Для офлайн-сборки используйте локальные каталоги: `DESCRIPTIONS_URL="file:///abs/path/descriptions.txt" PRODUCTS_DIR=./media/products make build-products`.
3. Проверьте результат:
   ```bash
   make validate-products
   jq 'length' app/data/products.json
   ```

`tools/build_products.py` скачивает файл описаний во временную директорию, парсит блоки, проверяет обязательные поля и уникальность `id`, сопоставляет изображения по имени (с учётом расширений) и сохраняет `app/data/products.json`. После сборки файл валидируется по схеме `app/data/products.schema.json`.

## Как обновлять

- Все временные данные должны складываться в `/tmp` или каталоги, перечисленные в `.gitignore`.
- Для локального тестирования можно указать свои пути: `python tools/build_products.py --descriptions-dir ./local/descriptions --products-dir ./local/products` или передать переменные окружения `DESCRIPTIONS_DIR`/`PRODUCTS_DIR`.
- Поля `image` в `app/data/products.json` всегда должны содержать абсолютные URL на CDN `MEDIA_BASE_URL`.

## CI

Workflow `.github/workflows/ci.yml` выполняет следующие шаги при каждом пуше/PR:

1. Устанавливает Python 3.11.
2. Обновляет `pip`, опционально ставит зависимости из `requirements.txt`, затем устанавливает `jsonschema`, `python-slugify`, `beautifulsoup4`, `lxml`, `requests`.
3. Запускает `make build-products` и `make validate-products`.
4. Загружает собранный `app/data/products.json` в артефакт `products-json-<sha>`.

## Откат

- Верните `app/data/products.json` и `app/data/products.schema.json` из нужного коммита или удалите `products.json`, если нужно временно отключить каталог.
- Для отключения каталога в рантайме установите `ENABLE_CATALOG=false`.
