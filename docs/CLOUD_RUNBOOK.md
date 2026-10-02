# DanaConnect: запуск в облаке

## Статус

Подготовлены конфигурации и команды запуска. Публичный адрес не создан. Аккаунт Vercel пока не авторизован; домен, сервер, почтовый отправитель и приватное хранилище не подключены. Контейнеры не запускались: Docker daemon в текущем окружении недоступен. Этот документ не является свидетельством работающего облачного развёртывания.

Пользователь выбрал Vercel Services: приложения размещаются вместе с внешними PostgreSQL/S3 и отдельным механизмом минутного планирования. Подготовленные настройки, обновление внешней базы и архив исходников описаны в [подготовке выпуска](RELEASE_PREPARATION.md). Полный переносимый вариант на Linux с Docker Compose сохранён: сайт, отдельная админ-панель, FastAPI, постоянный worker, PostgreSQL и Caddy с TLS.

## Что должен подключить владелец

| Ресурс | Что требуется |
|---|---|
| Сервер | Linux, Docker Engine + Compose v2, диск для PostgreSQL, доступ оператора по SSH, открытые TCP 80/443 и при желании UDP 443; БД и приложения наружу не открываются |
| Домен | Управляемый DNS; A/AAAA должны указывать на выбранный сервер. Если сервер не обслуживает IPv6, удалить неподходящую AAAA |
| Почта | Проверенный домен отправителя и Resend API key либо SMTP с реальными параметрами и TLS; настроить записи проверки домена у провайдера |
| Файлы | Приватный S3-совместимый bucket, HTTPS, регион, запрет публичного доступа, шифрование, IAM-доступ только к `attachments/*` |
| Администратор | Реальный email владельца, отдельная настройка MFA через операторскую команду, приложение аутентификатора |
| Эксплуатация | Защищённое место для ключей, offsite backups, мониторинг worker/почты/диска, владелец восстановления |

Ресурсы и тарифы выбирает владелец. Подготовленные файлы не создают аккаунты, ресурсы или покупки. Регион размещения, договоры с провайдерами и окончательные тексты обязательных документов должны быть выбраны перед приёмом реальных пользователей.

## 1. Локальная разработка

В PowerShell из корня проекта:

```powershell
./scripts/setup.ps1
# Только если нужны демонстрационные данные:
./scripts/setup.ps1 -Demo
```

Отдельные терминалы:

```powershell
./scripts/dev.ps1 -Service api
./scripts/dev.ps1 -Service web
./scripts/dev.ps1 -Service admin
./scripts/dev.ps1 -Service worker
```

Сайт: `http://127.0.0.1:3000`, отдельная админ-панель: `http://127.0.0.1:3001`, API: `http://127.0.0.1:8000/api/v1`. `setup` устанавливает оба приложения и миграции; демонстрационный seed запускается только с `-Demo`. Локальные `.env` не переносить в production. `scripts/check.ps1` сохранён; этот запуск не требует выполнения тестов.

Для preview готовой standalone-сборки вызвать `npm run start` в каждом frontend приложении. `scripts/serve-next.mjs` копирует `.next/static` и существующий `public` в runtime и запускает `node .next/standalone/server.js` с loopback `127.0.0.1` и портом 3000/3001; build/install не выполняются. Dockerfiles самостоятельно упаковывают те же ресурсы и используют контейнерную сеть.

Итог локального объединения 1–2 октября: оба frontend build прошли компиляцию/TypeScript/генерацию страниц; API и worker стартовали, mail provider не настроен и писем обработано 0. Ограниченный preview админ-входа выполнен без отправки формы. Это не hosted deployment или функциональная проверка сценариев; текущая evidence подробно отражена в [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md).

## 2. Создать приватную конфигурацию

На Windows:

```powershell
./scripts/cloud/init.ps1
```

На Linux из корня проекта:

```bash
python3 deploy/generate_config.py --output deploy/.env.production
```

Генератор эксклюзивно создаёт файл с новыми случайными `POSTGRES_PASSWORD`, `AUTH_SECRET`, `OUTBOX_ENCRYPTION_KEY`, `CRON_SECRET`, ограничивает доступ и не печатает значения. Существующий файл не заменяет. Оператор редактирует файл локально в защищённом редакторе:

- `APP_DOMAIN` — настоящий домен без схемы и пути; `ACME_EMAIL` — адрес оператора TLS.
- `POSTGRES_USER`/`POSTGRES_DB` — простые идентификаторы; пароль — сгенерированная hex-строка. Compose формирует PostgreSQL URL сам. Для самостоятельной внешней БД использовать отдельный percent-encoded URL.
- `EMAIL_PROVIDER=resend` + проверенный `EMAIL_FROM` + `RESEND_API_KEY`, либо `smtp` + `SMTP_HOST`, порт, имя/пароль. Для STARTTLS обычно `SMTP_STARTTLS=true`, `SMTP_TLS=false`; для implicit TLS переключить наоборот. Оба режима одновременно запрещены.
- `S3_BUCKET`, `S3_REGION`, при нестандартном провайдере `S3_ENDPOINT_URL=https://…`. `S3_SSE=AES256` или `aws:kms` + `S3_KMS_KEY_ID`; для KMS добавить доступ к выбранному ключу.
- AWS стандартная цепочка credentials: предпочтительно роль среды выполнения; для обычного сервера — ограниченные `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` и, если требуется, `AWS_SESSION_TOKEN`. Не делать bucket публичным и не выдавать браузеру ключи.
- Необязательный Google: все client-настройки и `GOOGLE_REDIRECT_URI=https://<домен>/api/v1/auth/google/callback` после настройки OAuth-провайдера.

Compose фиксирует `ENVIRONMENT=production`, `DEMO_MODE=false`, `AUTH_DEBUG_CODE=false`, `STORAGE_PROVIDER=s3`, HTTPS origin/front URL. `CRON_SECRET` нужен только для cron; контейнерный worker работает без него. Не использовать дневной cron для OTP и напоминаний.

Пример минимального IAM-доступа приложения: `deploy/s3-policy.example.json`; заменить имя bucket до применения. Bucket versioning и отдельная резервная копия настраиваются у провайдера. Учётной записи приложения не нужен доступ к списку всех buckets. Для независимых backup-инструментов нужен отдельный доступ.

## 3. Подготовить и запустить контейнерный выпуск

Домен должен указывать на сервер; порты 80/443 должны быть доступны для TLS. Compose использует сеть `172.30.0.0/24`; при конфликте оператор меняет subnet и фиксированные IP одновременно с allowlist в API Dockerfile. Uvicorn доверяет forwarded headers только Caddy `.10`, web `.11`, admin `.12`. API/PostgreSQL не имеют опубликованных host ports. Нельзя публиковать API напрямую с доверенным `*`.

Windows на целевом Docker host:

```powershell
./scripts/cloud/readiness.ps1
./scripts/cloud/start.ps1
./scripts/cloud/start.ps1 -Launch
```

Linux на целевом сервере:

```bash
bash scripts/cloud/start.sh
bash scripts/cloud/start.sh --launch
```

Без `-Launch` / `--launch` проверяется только конфигурация. Скрипт не выводит полный `docker compose config`, который раскрывал бы секреты. При явном запуске собирает три образа, запускает PostgreSQL, отдельную одноразовую миграцию `alembic upgrade head`, API после успеха миграций, worker, сайт, админ и proxy. Миграции не выполняются внутри каждого API request и не используют `create_all`. Seed в production не запускается.

Схема маршрутизации:

| Путь | Получатель |
|---|---|
| `/api/*` | FastAPI, исходный путь сохранён |
| `/admin`, `/admin/*` | Отдельный Next admin, исходный `/admin` сохранён |
| Остальные | Next web |

`ADMIN_BASE_PATH=/admin` задаётся при сборке. `ADMIN_APP_URL=https://<домен>/admin`; admin-маршрут обрабатывается раньше web, чтобы избежать цикла редиректов. Встроенные Next static assets админ-панели приходят через `/admin/_next/*`. Runtime обслуживает standalone output от непривилегированного пользователя. Python-образ содержит DejaVu для русских/казахских PDF.

Worker запускает **реальную** команду `python -m app.jobs_calendar --interval 60`: обновляет будущие слоты, создаёт напоминания и отправляет зашифрованную outbox через настроенного провайдера. Однократный ручной запуск: `python -m app.jobs_calendar --once`. Не включать одновременно контейнерный scheduler и внешнее минутное расписание.

Просмотр состояния на сервере:

```bash
docker compose --env-file deploy/.env.production -f compose.prod.yml ps
docker compose --env-file deploy/.env.production -f compose.prod.yml logs --tail 100 api worker proxy
```

`/api/v1/health` подтверждает живой процесс и режим. `/api/v1/ready` проверяет соединение с БД; не подтверждает доставку почты/S3/MFA. Доступ к `/admin/operations` после административного входа показывает конфигурацию, очереди и свежесть последнего успешного worker-цикла.

```powershell
./scripts/cloud/readiness.ps1 -BaseUrl https://ваш-домен
```

Или `python3 deploy/readiness.py --env-file deploy/.env.production --base-url https://ваш-домен`. Без BaseUrl скрипт не делает сетевых запросов. Статическая готовность не является доказательством DNS, IAM, доставки писем, восстановления backup или работоспособности worker.

## 4. Создать администратора с MFA

На доверенном сервере, после миграций:

```bash
docker compose --env-file deploy/.env.production -f compose.prod.yml exec api python -m app.admin_bootstrap --email admin@ваш-домен --name 'Имя администратора' --secret-output /tmp/admin.enrollment.json
docker compose --env-file deploy/.env.production -f compose.prod.yml cp api:/tmp/admin.enrollment.json /защищённый/путь/admin.enrollment.json
```

Команда создаёт администратора и TOTP на сервере; публичного bootstrap API нет. Приватный файл с enrollment URI передать непосредственно владельцу аутентификатора. После импорта удалить обе копии конкретного файла; не сохранять его в Git, логах или backup-папке с открытым доступом. Для явно запрошенной ротации используется `--rotate-mfa`, что отзывает прежние сессии. API/worker имеют одного непривилегированного пользователя, `/tmp` доступен; enrollment создаётся с приватными разрешениями. После смены ключа outbox старый ключ нужен в `OUTBOX_PREVIOUS_ENCRYPTION_KEYS` до контролируемой перешифровки MFA и очереди.

В `/admin/login`: email OTP → TOTP. Производственный администратор без настроенной MFA не получает рабочую сессию. После входа подготовить утверждённые документы, переводы, направления и материалы; уведомления пользователям придут только при реально работающем worker и провайдере. Генерация документов не заменяет юридическое утверждение их текста.

## 5. Backup и восстановление

PostgreSQL хранится в `postgres_data`, TLS state — в `caddy_data`/`caddy_config`. Пересоздание контейнеров сохраняет volumes. Не выполнять `docker compose down -v` на работающем проекте.

Создать PostgreSQL custom archive + SHA256:

```powershell
./scripts/cloud/backup.ps1
```

```bash
bash scripts/cloud/backup.sh
```

Архив копируется как бинарный файл, а не через текстовое перенаправление PowerShell. SHA256 выявляет повреждение, но не заменяет доверенное происхождение/шифрование. Скрипт не удаляет старые backup. По умолчанию папка `deploy/backups` исключена из Git, Docker build context и Vercel upload.

Минимальная операторская политика: ежедневный зашифрованный offsite PostgreSQL backup, backup перед миграциями, доступ только операторам, согласованное хранение/удаление, ежемесячное восстановление в отдельную базу. Пример Linux cron после согласования расписания:

```cron
15 2 * * * /bin/bash /opt/danaconnect/scripts/cloud/backup.sh /защищённая/backup-папка >> /защищённая/backup-папка/job.log 2>&1
```

Это пример, расписание не устанавливалось. Offsite перенос и шифрование выбираются у оператора/провайдера; автоматически никуда данные не отправляются. S3 bucket должен иметь отдельный versioning/backup; PostgreSQL dump не содержит файлов. Отдельно защищённо сохраняются `AUTH_SECRET`, текущий и предыдущие ключи outbox/MFA, конфигурация провайдера и данные восстановления KMS. Потеря ключей делает часть зашифрованных данных нечитаемой. Удаление пользовательских данных должно учитывать backup и S3 версии; админ-форма не выполняет полный purge.

Восстановление по умолчанию проверяет checksum. Изменение БД требует явного флага и **нового** имени; существующая/live база не перезаписывается:

```powershell
./scripts/cloud/restore.ps1 -BackupFile 'C:\защищённый\danaconnect-....dump' -TargetDatabase recovery_20261001
./scripts/cloud/restore.ps1 -BackupFile 'C:\защищённый\danaconnect-....dump' -TargetDatabase recovery_20261001 -Restore
```

```bash
bash scripts/cloud/restore.sh /защищённый/danaconnect-....dump recovery_20261001
bash scripts/cloud/restore.sh /защищённый/danaconnect-....dump recovery_20261001 --restore
```

`createdb` отказывает для уже существующего имени, `pg_restore --exit-on-error` останавливается при ошибке. Ошибка может оставить частично заполненную отдельную базу; скрипт не удаляет её автоматически. Перед переключением оператор сверяет миграцию, данные, приватные файлы, ключи и доступы. Promotion отдельной восстановленной базы — отдельное управляемое действие при остановке записей; скрипты не подменяют live DB.

## 6. Новый выпуск и откат

1. Создать backup до изменения конфигурации/БД. Сохранить release commit, старые images и версию схемы.
2. Установить новый `RELEASE_TAG` в приватной конфигурации и собрать новый выпуск на том же хосте. Не менять ключи без отдельного плана ротации.
3. Проверить миграции в отдельной копии данных перед утверждённым обновлением production. Не запускать web build параллельно с его dev server.
4. Выполнить `start … --launch`; наблюдать API readiness, worker, ошибки outbox и доступ администратора. Обновления схемы могут требовать окна обслуживания.
5. Для отката кода использовать сохранённые совместимые images и прежний release. Не делать автоматический Alembic downgrade: изменения схемы/данных могут быть необратимы. При несовместимости восстанавливать отдельную БД по процедуре выше и выполнять управляемое переключение.

У single-host Compose нет гарантии zero downtime или автоматического failover БД. Для такого требования нужен отдельный проект HA/managed database с PITR, мониторингом и согласованным бюджетом.

## 7. Vercel Services: выбранный вариант

Корневой `vercel.json` использует актуальный `services` с `root`, `framework`, bindings и top-level rewrites. Service bindings доступны **только во время выполнения**, поэтому созданный `API_SERVICE_URL` не используется как build-time rewrite target. Сейчас браузер вызывает тот же домен `/api/v1`; top-level router направляет запрос напрямую к API. Сервисы получают исходные пути, `/admin` не срезается. Источники: [Services configuration](https://vercel.com/docs/services/config-reference), [bindings](https://vercel.com/docs/services/bindings), [routing](https://vercel.com/docs/services/routing).

После подключения владельцем аккаунта/проекта в Vercel:

1. Связать репозиторий как один проект с корнем репозитория; не указывать apps/web как root всего проекта. Проверить доступность текущей Services beta для аккаунта.
2. Внести production env только в защищённые настройки окружения: `ENVIRONMENT=production`, external `DATABASE_URL=postgresql+psycopg://…` (TLS/pooler провайдера), `AUTH_SECRET`, `OUTBOX_ENCRYPTION_KEY`, `TRUSTED_ORIGINS=["https://<домен>"]`, `FRONTEND_URL=https://<домен>`, mail/S3 настройки. Frontend: `ADMIN_APP_URL=https://<домен>/admin`, `NEXT_PUBLIC_WEB_URL=https://<домен>`. Admin build command уже задаёт `/admin`.
3. Использовать внешнюю постоянную PostgreSQL, приватный S3; локальные SQLite и файлы serverless-диска запрещены. Выполнить миграции отдельно из защищённого операторского окружения с теми же production settings. Не запускать миграции в каждом request.
4. Сделать preview с отдельными preview DB/bucket, origin и секретами; не направлять preview к production данным. Настройки приложения требуют HTTPS, demo/debug отключены. Провайдеры и MFA нужны и для этого окружения.
5. Перед publication выбрать worker-вариант ниже. Пока нет реального планировщика, OTP в outbox и напоминания не работают своевременно.
6. Внести `UPLOAD_MAX_BYTES=3145728` для Vercel: функция имеет предел 4.5 MB на запрос **и ответ**; текущие приватные скачивания проходят через API, поэтому большие файлы нельзя обещать. Полные 10 MiB доступны в контейнерном варианте. [Ограничения Vercel Functions](https://vercel.com/docs/functions/limitations).
7. В API встроен неизменённый DejaVu Sans 2.37 с лицензией и зафиксированным SHA-256; выбор не зависит от системного шрифта. `services.api.functions["app/main.py"].includeFiles` включает `assets/fonts/**`. Таблица символов изучена, фактическая выдача PDF в облачной функции пока не подтверждена. [Источник и лицензия](../apps/api/assets/fonts/SOURCE.md), [FastAPI function configuration](https://vercel.com/docs/frameworks/backend/fastapi).

Отдельный Vercel шаблон создаётся через `deploy/vercel_config.py generate --output deploy/.env.vercel.local`, структурная проверка — `validate --env-file deploy/.env.vercel.local`. Значения не печатаются и не загружаются в сервис. `VERCEL=true` включает ограничения среды; `DATABASE_POOL_MODE=null` отключает локальный пул. `NEXT_PUBLIC_WEB_URL` содержит только публичный адрес сайта для переходов из админки. Для миграций подготовлен `deploy/migrate_external.py`: по умолчанию только локальный план, применение требует `--apply`, закрытого файла и ожидаемой текущей версии. [Порядок выпуска](RELEASE_PREPARATION.md).

**Worker-варианты:**

- Основной переносимый вариант — постоянно работающий контейнер worker на сервере с той же внешней PostgreSQL и env, без второй параллельной копии scheduler. Команда `python -m app.jobs_calendar --interval 60`.
- Opt-in Vercel minute cron — только тариф с поддержкой минуты и согласованный бюджет. В Hobby минимум один запуск в день и нет подходящей точности для почты/напоминаний; такой запуск не заменяет worker. [Cron usage and pricing](https://vercel.com/docs/cron-jobs/usage-and-pricing).

Для отдельного worker с Vercel API подготовлен `deploy/compose.worker.yml`: скопировать `deploy/.env.worker.example` в приватный `deploy/.env.worker`, внести **те же** DB/ключи/провайдеры, что у API, ограничить права файла. Миграции выполняются оператором до запуска:

```bash
docker compose --env-file deploy/.env.worker -f deploy/compose.worker.yml config -q
docker compose --env-file deploy/.env.worker -f deploy/compose.worker.yml up -d --build
```

Этот вариант не запускает локальную БД, proxy или API и не переопределяет внешний DATABASE_URL на контейнерный адрес. Резервные копии внешней БД/PITR настраиваются у выбранного провайдера; скрипты `backup/restore` выше работают с PostgreSQL сервиса полного Compose.

Чтобы добавить minute cron **локально**, после выбора подходящего тарифа:

```powershell
./scripts/cloud/enable-vercel-cron.ps1 -Enable
```

На Linux можно вручную добавить единственный блок из `deploy/vercel.cron.example.json` в корневой config. Не заменять им весь `vercel.json`. Default config не включает cron и не обещает его бесплатную работу. Секрет `CRON_SECRET` >=32 символов должен отличаться от `AUTH_SECRET`. Vercel передаёт его как Bearer Authorization к защищённому GET `/api/v1/internal/jobs`; этот endpoint вызывает один ограниченный batch `run_once` и обновляет heartbeat. [Защита Vercel Cron](https://vercel.com/docs/cron-jobs/manage-cron-jobs).

Постоянный daemon внутри serverless function не запускать. Один batch ограничен временем функции; после реального развёртывания оператор наблюдает длительность/heartbeat/очередь и, если функция не успевает, использует контейнерный worker. Внешний cron должен также передавать Bearer secret, не query-string. Secrets не писать в команды/историю shell или публичные URL.

Vercel config подготовлен по текущей документации; загрузка в аккаунт и acceptance самой платформой не выполнены из-за отсутствия авторизации. Владелец подключает аккаунт и подтверждает реальные ресурсы/тариф до публикации.

## Граница готовности

Реализовано: container build recipes, порядок миграций, routing/TLS, private storage settings, worker, scripts для закрытых secrets/config, backup/restore и альтернативный Services config. Статически проверены JSON/Python/PowerShell; приложения собираются отдельно. Не подтверждено в текущем окружении: Docker build/runtime, PostgreSQL server, S3 IAM, DNS/TLS, production email, облачная MFA и реальное восстановление. Эти пункты являются условиями фактического запуска; публичной deployment ссылки пока нет.
