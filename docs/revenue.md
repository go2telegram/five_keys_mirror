# Revenue Engine

Монетизационный контур хранится в `data/revenue.sqlite3` (настраивается через
`REVENUE_DB_PATH`). В SQLite сохраняются офферы, клики, конверсии и выплаты.

## Структура

| Таблица      | Поля                                                                 |
| ------------ | --------------------------------------------------------------------- |
| offers       | external_id, name, campaign, default_payout                           |
| clicks       | external_id, offer_id → offers.external_id, campaign, occurred_at, cost |
| conversions  | external_id, click_id → clicks.external_id, occurred_at, revenue, status |
| payouts      | external_id, conversion_id → conversions.external_id, occurred_at, amount |

`revenue.models.init_db()` автоматически создаёт схему при первом обращении.

## Импорт данных

* CSV: `revenue.tracker.import_csv(path)`.
* Webhook: `revenue.tracker.handle_webhook(payload)`.

CSV ожидает столбцы `type,id,offer_id,click_id,conversion_id,campaign,name,cost,revenue,amount,timestamp`.
Типы: `offer`, `click`, `conversion`, `payout`.

Ошибки валидации возвращаются в поле `errors` результата импорта.

## Метрики

`revenue.get_revenue_summary()` возвращает словарь

```json
{
  "totals": {
    "revenue": 123.45,
    "spend": 67.89,
    "roi": 0.82,
    "epc": 1.23,
    "offers": 4,
    "clicks": 100,
    "conversions": 5,
    "payouts": 3
  },
  "roi_per_campaign": [
    {"campaign": "C1", "revenue": 42.0, "spend": 10.0, "roi": 3.2}
  ],
  "trends": [
    {"day": "2024-10-01", "clicks": 12, "conversions": 1, "revenue": 5.0,
     "payout_revenue": 5.0, "spend": 2.5}
  ]
}
```

`trends` пригоден для Grafana (поддержка графиков по кликам, конверсиям,
доходу и расходам).

## Админ-панель

Команда `/revenue` (только для `ADMIN_ID`) выводит основные KPI и ROI по
кампаниям. Импорт CSV из Телеграма: отправьте файл с подписью `#revenue` или
используйте `/revenue_import` для подсказки. После импорта `/revenue`
пересчитает показатели.
