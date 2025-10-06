# Каталог товаров

## Структура

Каталог хранится в директории `app/data/`. Основной файл данных будет называться `products.json` и должен соответствовать схеме `products.schema.json`.

## JSON-схема

Схема расположена в `app/data/products.schema.json` и описывает обязательные и опциональные поля каждого товара. Перед коммитом можно проверить корректность схемы командой:

```bash
jq '.' app/data/products.schema.json >/dev/null
```

## Удаление легаси-файлов

Для безопасной очистки старых файлов каталога предусмотрен скрипт:

```bash
./scripts/rm_legacy_products.sh
```

Скрипт удаляет `app/data/products.json`, `app/data/products_old.json`, `app/data/products.yml` и `app/data/products.csv`, если они существуют.

## Переменные окружения

Добавлен ключ `.env`:

```
MEDIA_BASE_URL=https://raw.githubusercontent.com/go2telegram/media/main
```

Значение можно переопределить при необходимости. Настройка используется для работы с медиа-ресурсами каталога.

## Откат

Для отката изменений восстановите нужный коммит:

```bash
git checkout <commit>
```

Либо отключите каталог, установив переменную окружения `ENABLE_CATALOG=false`.
