# Контракт выпуска 0.2

Пользователь поручил завершить продукт, выделить отдельную админ-панель и перенести в облако. 2 октября выбрана Vercel; пользователь создаёт и подключает аккаунт в Codex. Последний ответ подключения требует повторной авторизации. Домена и подтверждённых production ресурсов пока нет. Фактическая публикация и включение провайдеров требуют доступного аккаунта. Платные ресурсы не создаются автоматически.

## Дополнение фазы 3, 2 октября

Подключены личный центр уведомлений и следующие действия, выход обычного участника из команды и удаление с причиной, приватные обращения с ответами поддержки, счётчики непрочитанных и индивидуальные подтверждения прочтения сообщений, снимок собственных встреч в ICS и раздел подготовки пилота в админке. Объяснение административного решения по обращению теперь видно его автору. Сообщения и комментарии ограничены 20 отправками в минуту на пользователя.

Новая зафиксированная миграция `0e82eab8e5ef` добавляет `report_responses` и `message_reads`; применена к локальной SQLite после остановки API/worker и сохранения копии базы. Python компиляция, обе проверки типов и обе frontend сборки завершились успешно. Web содержит 22 маршрута, admin 19, включая страницы ошибки. API, worker и оба приложения снова запущены локально. Функциональные сценарии, новые тесты, реальные провайдеры и облачный выпуск этим этапом не подтверждены. ICS — ручной экспорт, без автоматической синхронизации с внешним календарём.

## Границы файлов

Фаза 5, 2 октября: защищённая сводка операций дополнена агрегатами очереди и worker с единым временем запроса. Возраст queue attempt измеряется от `next_attempt_at`; 24h failure cohort использует время создания, поскольку время отказа не хранится. Сигналы являются индикаторами оператора, не launch gates. JSON ограничен фиксированными полями. API Request ID и HTTP-журнал не содержат raw path/query/body/headers/exception; внешний access log требует отдельной политики. Модели и frozen revisions не изменены. [Инструкция](MONITORING_RUNBOOK.md).

Ниже сохранено распределение областей реализации. Итоговая интеграция описана в AGENT_WORK.md и IMPLEMENTATION_STATUS.md. В фазе расширения новые тесты не добавлялись и не запускались; использовались статический просмотр, проверки типов, компиляция, сборки и локальный запуск.

Root owns app/main.py, app/models.py, app/schema_registry.py, migrations, requirements, shared docs and deployment orchestration. Each backend feature registers additional SQLAlchemy classes in a separate app/models_<feature>.py importing Base from app.models. Do not independently alter existing models or migrations. Send new columns needed on existing models to root. Root imports all feature modules in schema_registry; frozen revisions 0001, a6a433a7debd and 1639a031a3c6 preserve schema history.

1. admin_console: all apps/admin files, separate Next app, port3001, standalone admin shell/login and pages. Do not modify apps/web or backend. Copy existing shared components/types if helpful; no API mock success. Guard data via authenticated admin API. All labels RU/KZ/EN. Existing admin endpoints plus additions from root below.
2. identity_delivery: config.py, auth.py, routers/identity.py, schemas/identity.py, delivery.py, models_delivery.py, admin_bootstrap.py. Real Resend/SMTP adapter, transactional encrypted outbox and bounded retries; dev console only explicitdev. Admin MFA/bootstrap and optional GoogleSSO if feasible. Preserve cookie/Origin/version guards. Production requires PostgreSQL and fresh secrets; do not require mail configuration to import test app. Missing provider must return clear unavailable. No external delivery calls in this phase.
3. localization: apps/web existing user pages/components/lib, excluding app/admin; full RU/KZ/EN labels, error states, dates, initial loading, html lang. Public API useLocale adds tr(ru:string):string while retaining locale,setLocale,t object for compatibility. API request carries Accept-Language. Support email locale and MFA response contract from task2. Do not alter backend or build while root is building.
4. collaboration: models_collaboration.py, routers/collaboration.py, schemas/collaboration.py, storage.py; project comments/reviews, team invitations (authenticated accept), secure attachments local/S3 private. New user components/routes for these features live only in new apps/web/src/components/collaboration and new dedicated routes; coordinate localization integration. No edits to original user pages until root merges.
5. calendar_jobs: models_calendar.py, routers/calendar_rules.py, schemas/calendar_rules.py, jobs_calendar.py; weekly recurring availability with IANA/DST/horizon bounds, future slots regeneration without touching bookedslots, reminder scheduler, manual meeting link input and no-show if required. Original bookings router changes allowed; notify root for imports. Coordinate mail enqueue contract with task2. New UI in components/calendar-rules; root merges existingcalendar.
6. growth_content: models_growth.py, routers/growth.py, schemas/growth.py, services/growth.py; curated learning materials by direction, explicit milestone points/badges with unique sourceevent, admin-managed nominations/certificates and consent-conscious leaderboard; optional explainable AI structuring/recommendations with administrator review, no fake AI when unconfigured. New frontend files components/growth and app/resources,app/achievements; root merges navigation. No real payment processing without provider/business decision.
7. integration_review: static integration, role/access and lifecycle review, frontend type checking and readiness reporting. No new tests or functional browser scenarios were executed. Live PostgreSQL and provider verification remain pending.
8. deployment_ops: Dockerfiles, compose.prod.yml, deploy/*, scripts cloud/backup/readiness, docs/CLOUD_RUNBOOK.md, root vercel.json cloudconfig. Prepare compatible Next+FastAPI+separateNextadmin/worker/Postgres/private files, TLS proxy, backups and restoration. Inspect existing authentication read-only; no actual deployment or account/resource/purchase creation without root orchestration. Coordinate appbasepaths/route prefixes before adding Vercel services. Container deployment remains portable fallback. Never publish local.env/demodb/source attachments.

## Админ API additions owned by root

GET /admin/me -> self_user via require_admin.
PATCH /admin/users/{id}/status {status:active|suspended,reason}; cannot alter admin/self; suspend revokes sessions, closesintake, cancelsfuturebookings, hides profile/case by status. Reactivation checks completedprofile/currentconsents, must not bypassmoderation for pending/draft.
GET /admin/operations -> operational readiness booleans/counts, no raw secrets.
PATCH /admin/documents/{id} {active?,title?} -> identity metadata; disabling required legal docs is audited, no historicalconsent deletion.
GET /me/data-export -> own account/consents/projects/participations/results/feedback/messages; no peers' privatecontacts.
GET/POST /me/privacy-requests -> export|deactivate|erase request, adminqueuehandling, no hard deletion by form; no pretendcomplete deletion without purging required records.
Document versions include content_kk/content_en; original content remains RU. Consent binds the displayed content hash and locale.
User preferred_locale is ru|kk|en (default ru); profile and notification delivery use it.

## Общее

Keep all original tests and behavior, migrationsfrozen. No create_all at productionstartup. Native deliverables onlyafter realdeploysuccess. All hosted environments use durable PostgreSQL and privateobjectstorage; SQLite onlylocal/testing. ScopebaseURLs configurable, sameorigin /api/v1 proxy, nevercommit secrets. UI uses neutral DanaConnect/mentorship workingname, brandcolors, suppliedlogo onlyifavailable. Demonstration labels disappear only when genuine demo-freeproductionconfiguration selected; no fakeinstitutionalimpact.

New user UI imports tr from useLocale and uses Russian sourcephrases consistently; root/localization agent will registertranslations for newfeatures. Do notrun nextbuild concurrently for sameapp or with its devserver.
