# Product event schema

Все продуктовые события пишутся в `logs/events.log` в формате JSONL и одновременно попадают в Prometheus-метрики (`/metrics`). Каждая строка лога — объект следующей структуры:

```json
{
  "ts": "2024-06-30T12:34:56.789012+00:00",
  "event": "user_signup",
  "user_id": 123456789,
  "props": {
    "source": "ref_987654321"
  }
}
```

## Поля

| Поле      | Тип              | Описание                                                                 |
|-----------|------------------|--------------------------------------------------------------------------|
| `ts`      | `str`            | Время фиксации события в ISO 8601 (UTC).                                |
| `event`   | `str`            | Код события (см. ниже).                                                 |
| `user_id` | `int \| null`    | Telegram ID пользователя, если известен.                                |
| `props`   | `object`         | Дополнительные параметры события. Значения сериализуются в строки при необходимости. |

## События

| Событие              | Когда отправляется                                      | Дополнительные поля (`props`)                      |
|----------------------|---------------------------------------------------------|----------------------------------------------------|
| `user_signup`        | Первый `/start` пользователя                            | `source` — необязательный стартовый payload.       |
| `referral_join`      | Новый пользователь присоединяется по реферальной ссылке | `referrer` — ID пригласившего.                     |
| `lead_created`       | Пользователь оставил заявку на консультацию             | `has_comment` — `true`, если заполнено поле комментария. |
| `purchase_attempt`   | Пользователь открыл раздел оформления подписки          | —                                                  |
| `purchase_success`   | Tribute подтвердил подписку                             | `plan` — тариф (`basic`/`pro`), `source` — `"tribute"`. |
| `feature_use:<name>` | Пользователь пользуется функцией бота                   | Имя функции входит в `event`. Доп. поля — по ситуации. |

### Текущее покрытие `feature_use`

- `feature_use:calc_menu`, `feature_use:calc_msd`, `feature_use:calc_bmi`
- `feature_use:referral_menu`

## Метрики

- `product_event_total{event="…"}` — общий счётчик по типам событий.
- `product_user_signup_total`, `product_lead_created_total`, `product_purchase_attempt_total`, `product_purchase_success_total`, `product_referral_join_total` — счётчики ключевых этапов воронки.
- `product_feature_use_total{feature="…"}` — использование функций.
- `product_event_age_days{event="…"}` — гистограмма времени (в днях) от регистрации до события, используется в дашбордах D1/D7.

Все метрики доступны на эндпоинте `GET /metrics` (Prometheus format).
