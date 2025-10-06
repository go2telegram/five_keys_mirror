# Five Keys Network Dashboard

Глобальная панель `/network_admin` агрегирует данные со всех инстансов Five Keys и предоставляет обзор в режиме близком к реальному времени.

## Конфигурация

1. Добавьте новые переменные окружения в `.env` сервиса-агрегатора:

   ```env
   ENABLE_NETWORK_DASHBOARD=true
   NETWORK_API_KEY="<секретный-ключ>"
   NETWORK_REFRESH_SECONDS=60
   NETWORK_NODE_TIMEOUT=5.0
   NETWORK_NODES='[
     {
       "name": "Москва",
       "base_url": "https://msk.five-keys.example",
       "latitude": 55.751244,
       "longitude": 37.618423,
       "region": "Москва, Россия"
     },
     {
       "name": "Алматы",
       "base_url": "https://ala.five-keys.example",
       "latitude": 43.2220,
       "longitude": 76.8512,
       "region": "Алматы, Казахстан"
     }
   ]'
   ```

   - `NETWORK_API_KEY` используется для авторизации всех HTTP-запросов к панели (заголовок `X-API-Key` или query `?api_key=`).
   - Список `NETWORK_NODES` должен содержать минимум `name` и `base_url`. Геопозиция и `metrics_path` опциональны.

2. При необходимости отключения панели выполните `ENABLE_NETWORK_DASHBOARD=false`. В этом режиме роут возвращает `404`, а фоновые задачи не запускаются.

## Запуск

Запустить сервис можно с помощью любого ASGI-сервера, например:

```bash
uvicorn network.dashboard:app --host 0.0.0.0 --port 9000
```

## Маршруты

| Метод | Путь                        | Описание                                                   |
|-------|-----------------------------|------------------------------------------------------------|
| GET   | `/network_admin`            | HTML-дашборд с картой узлов и сравнением метрик.           |
| GET   | `/network_admin/api/snapshot` | Последний снимок метрик в формате JSON.                   |
| POST  | `/network_admin/api/refresh`  | Форсирует мгновенное обновление данных.                   |

Все маршруты требуют валидного `NETWORK_API_KEY`.

## Обновление данных

- Фоновый сборщик обновляет данные раз в `NETWORK_REFRESH_SECONDS` (по умолчанию 60 секунд).
- Каждый запрос к `/network_admin/api/refresh` запускает внеочередной сбор.
- В случае ошибки сбора узел помечается как offline, описание ошибки возвращается в поле `error`.

## Интеграция Nginx

Для проксирования `/network_admin` на отдельный сервис добавьте в `deploy/nginx.conf`:

```nginx
location /network_admin/ {
    proxy_pass http://network-dashboard:9000/network_admin/;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

Не забудьте пробросить заголовок `X-API-Key` от клиента.

## Проверка

1. Запустите панель с тремя тестовыми инстансами.
2. Убедитесь, что все узлы отображаются на карте и в таблице.
3. Проверьте, что данные обновляются не реже одного раза в минуту.

## Откат

1. Установите `ENABLE_NETWORK_DASHBOARD=false`.
2. Остановите процесс ASGI-сервера.
3. (Опционально) Удалите модуль `network` и конфигурацию Nginx.
