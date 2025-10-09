# GO-LIVE Runbook — Release 1.3.1 Dress Rehearsal

Этот документ описывает пошаговую репетицию прод-релиза с канареечным выкатом и возможностью мгновенного отката.

## 1. Code freeze
- ✅ Зафиксируйте ветку `main` — только релизные коммиты.
- ✅ Убедитесь, что фича-флаги включены на STAGE (`/ab_status`).
- ✅ Подготовьте `RELEASE_NOTES.md` и зафиксируйте версию.

## 2. Release build
- ✅ Запустите workflow `release.yml` (Push в `main`).
- ✅ Дождитесь сборки self-audit, тестов и публикации релизной заметки.

## 3. Stage health-check
- ✅ После деплоя STAGE зайдите на `/admin/dashboard?token=<STAGE_TOKEN>`.
- ✅ Проверьте `/health` и `/metrics` — все статусы «ok».
- ✅ Убедитесь, что `CANARY_PERCENT`=0 и все флаги включены (stage defaults).

## 4. Self-audit
- ✅ Пройдите чек-лист в `RELEASE_NOTES.md` (раздел STAGE).
- ✅ Подтвердите отсутствие ошибок в Sentry (релиз `vX.Y.Z+stage`).

## 5. Smoke-test
- ✅ Выполните `/start` и /quiz сценарии на STAGE.
- ✅ Проверьте новый онбординг, навигацию и медиапрокси.
- ✅ Прогоните платёж/лид (если применимо) на тестовых данных.

## 6. Canary rollout (PROD)
1. 🔄 Убедитесь, что `CANARY_PERCENT=10` в окружении.
2. ▶️ Выполните `/ab_status` — убедитесь, что `FF_NEW_ONBOARDING` и `FF_NAV_FOOTER`=OFF, но помечены как `canary 10%`.
3. 🔍 Протестируйте фичи на тестовом пользователе, попавшем в канареечную группу.
4. ⏱ Через 30 минут проверьте метрики `/metrics`, жалобы в поддержку.
5. ⬆️ Увеличьте `CANARY_PERCENT` до 50%. Повторите проверки.
6. ⬆️ Увеличьте `CANARY_PERCENT` до 100% — фактически включите фичу для всех.
7. ✅ После стабилизации зафиксируйте флаги командой `/toggle FF_NEW_ONBOARDING on`, `/toggle FF_NAV_FOOTER on`.

## 7. Rollback plan
- ↩️ Мгновенный откат: `/toggle <FLAG> off` (например, `/toggle FF_NEW_ONBOARDING off`).
- 🎯 Для полной деактивации канареек установите `CANARY_PERCENT=0` и выполните `/ab_status`.
- 🧹 После отката очистите overrides (`/toggle <FLAG> on`, если значение по умолчанию выключено).

## 8. Post-release
- 📝 Обновите `RELEASE_NOTES.md` (раздел PROD) и self-audit в GitHub Release.
- 📊 Проверьте Sentry (релиз `vX.Y.Z`).
- 📣 Сообщите команде о завершении выката.
