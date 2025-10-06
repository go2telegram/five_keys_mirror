# Адаптивный автоскейлинг

Скрипт `tools/autoscale.py` регулирует количество реплик в Docker Compose или Kubernetes в
зависимости от текущего RPS. Он считывает метрики по HTTP (формат Prometheus), вычисляет
необходимое количество экземпляров и применяет изменения.

## Подготовка

1. Убедитесь, что сервис отдаёт метрику с текущим значением RPS на `/metrics`.
   По умолчанию ожидается метрика `http_requests_per_second`. Имя можно переопределить
   через флаг `--rps-metric`.
2. Настройте параметры `--min`, `--max`, `--rps-target` и `--cooldown` под свой сервис.
3. Для Docker Compose обновления записываются в `deploy/compose.override.yml`.
   Для Kubernetes формируется манифест `k8s/hpa.yaml` и при наличии `kubectl`
   выполняется `kubectl apply`.

## Пример запуска (Docker Compose)

```bash
python tools/autoscale.py \
  --provider=compose \
  --min=1 \
  --max=5 \
  --rps-target=40 \
  --cooldown=120 \
  --metrics-url=http://localhost:8000/metrics \
  --service=app
```

Скрипт:

- читает `deploy/compose.override.yml`, изменяя `deploy.replicas` для сервиса `app`;
- запускает `docker compose up -d --scale app=<n>` если бинарник `docker` доступен;
- хранит служебное состояние в `tools/.autoscale_state.json`, чтобы корректно
  отрабатывать `cooldown` при понижении нагрузки.

## Пример запуска (Kubernetes)

```bash
python tools/autoscale.py \
  --provider=k8s \
  --min=2 \
  --max=10 \
  --rps-target=50 \
  --cpu-target=70 \
  --cooldown=180 \
  --metrics-url=http://metrics.local/metrics \
  --service=app \
  --namespace=prod
```

При работе в режиме `k8s`:

- формируется HPA манифест `k8s/hpa.yaml` с метриками по RPS и CPU;
- выполняется `kubectl apply -f k8s/hpa.yaml` (если `kubectl` доступен);
- при необходимости скрипт дополнительно делает `kubectl scale deployment` до рассчитанного
  числа реплик, чтобы стартовое состояние соответствовало текущей нагрузке.

## Имитация нагрузки

Для локальной проверки добавлен утилита `tools/stress_test.py`. Пример использования:

```bash
python tools/stress_test.py --url http://localhost:8000/ --workers 8 --duration 120
```

Поднимая или снижая количество воркеров, можно видеть как меняется RPS и реакция
автоскейлера.

## Запуск по расписанию

### Cron

Добавьте задание в cron (например, каждые 2 минуты):

```cron
*/2 * * * * cd /srv/bot && /usr/bin/python3 tools/autoscale.py --provider=compose --min=1 --max=5 --rps-target=40 --cooldown=180 >> /var/log/five-keys-autoscale.log 2>&1
```

### systemd timer

Пример `autoscale.service`:

```ini
[Unit]
Description=Five Keys autoscaler

[Service]
Type=oneshot
WorkingDirectory=/srv/bot
ExecStart=/usr/bin/python3 tools/autoscale.py --provider=compose --min=1 --max=5 --rps-target=40 --cooldown=180
```

И таймер `autoscale.timer`:

```ini
[Unit]
Description=Run autoscaler every 2 minutes

[Timer]
OnBootSec=2m
OnUnitActiveSec=2m
Unit=autoscale.service

[Install]
WantedBy=timers.target
```

Активируйте таймер командой `systemctl enable --now autoscale.timer`.

## Откат изменений

1. Удалите задания cron/systemd, которые запускают `tools/autoscale.py`.
2. Верните значение `deploy.services.app.deploy.replicas` в `deploy/compose.override.yml`
   к `1`.
3. Удалите HPA из Kubernetes (`kubectl delete -f k8s/hpa.yaml`) и сам файл манифеста при
   необходимости.
