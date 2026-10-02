# Подключение рабочего окружения

2 октября 2026 года. Пользователь поручил настроить PostgreSQL, почту, Google, HTTPS, MFA и отключить учебный режим/коды разработки.

## Выполнено в этой попытке

- Создан закрытый `deploy/.env.vercel.local` с новыми AUTH_SECRET, OUTBOX_ENCRYPTION_KEY и CRON_SECRET. Секреты не выводились; Windows ACL разрешает доступ только текущему владельцу.
- В закрытом файле установлены `ENVIRONMENT=production`, `VERCEL=true`, `DATABASE_POOL_MODE=null`, `DEMO_MODE=false`, `AUTH_DEBUG_CODE=false`.
- Первоначальный структурный валидатор отверг неполную конфигурацию. После подключения ресурсов и передачи Gmail app password последняя структурная проверка успешно прошла. Это не подтверждает доставку писем, файловые операции или Google.
- Владелец подтвердил вход Vercel; CLI проверил аккаунт. Создан и связан проект `danaconnect` на действующем Hobby, preset `services`. Production deployment `dpl_97q1BC7xQgFCX9BrLoyqFaefjosE` сообщил READY, production alias `danaconnect.vercel.app` назначен. [Сайт](https://danaconnect.vercel.app), [админка](https://danaconnect.vercel.app/admin), [проект Vercel](https://vercel.com/alizhan695-7132/danaconnect).
- Операционный сигнал опубликованного API `https://danaconnect.vercel.app/api/v1/ready` вернул HTTP 200 и `{"status":"ready"}`. Этот endpoint подтверждает запрос `SELECT 1` к БД; не проверяет email, MFA, Blob, Google и всю бизнес-логику.
- В рабочей PostgreSQL наблюдён успешный цикл облачного worker: `started_at=2026-10-02T11:34:02.119286Z`, `finished_at=2026-10-02T11:34:05.721780Z`, `status=success`. Время указано в UTC (16:34 Asia/Oral). Это подтверждает выполнение очередного задания QStash/API, но не отправку или получение письма.
- В закрытой конфигурации сохранён email администратора из подтверждённого аккаунта и HTTPS origin `https://danaconnect.vercel.app` с админкой `/admin`.
- После подтверждения условий создана бесплатная Neon PostgreSQL `danaconnect-postgres` в Frankfurt (`fra1`, `free_v3`) и подключена только к Production проекта. Provider env получен в закрытый `deploy/.env.neon.production.local`; URL нормализован под psycopg в основной закрытой конфигурации.
- Оператор `deploy/migrate_external.py --apply --expected-current empty` применил миграции к новой выделенной PostgreSQL и подтвердил head `0e82eab8e5ef`. Учебный seed не запускался. Миграция добавляет служебную запись heartbeat, а не учебных участников.
- Через offline bootstrap создан настоящий активный администратор с зашифрованным MFA credential. Закрытый `deploy/admin.enrollment.json` содержит URI и `manual_entry_key` для authenticator; импорт и рабочий вход владельцем ещё не подтверждены. ACL enrollment и файлов подключения защищены от наследования и содержат одно разрешение владельцу.
- Для миграции/bootstrap использован отдельный `deploy/.env.database-operator.local` с теми же рабочими ключами и отключёнными mail/storage. Этот файл предназначен только для offline оператора и не является конфигурацией выпуска.
- Создан закрытый `deploy/.env.owner-input.local` для локального ввода Gmail app password и Google OAuth credentials. Пустые поля не означают подключение почты/Google.
- В Vercel записаны 22 зашифрованные основные настройки только для Production; последующий metadata read подтвердил все 22. Managed Neon credentials не изменялись. `DEMO_MODE=false`, `AUTH_DEBUG_CODE=false` и общие auth/outbox/cron ключи вошли в production deployment.
- Создан private Vercel Blob `danaconnect-private`, `store_HRhWuA1QjaMGCM4d`, Frankfurt `fra1`. `get-store` подтвердил private access и регион; токен подключён только к Production. В API добавлен адаптер закрытых upload/download/delete с ограниченным чтением, фиксированными адресами и проверкой принадлежности token своему store. Новых зависимостей и миграций для Blob нет. Файловые операции пока не проверялись.
- Записаны девять дополнительных Production-настроек Blob и Gmail SMTP, затем отдельно закрытый `SMTP_PASSWORD`. Credential сохранён в owner-protected файлах и зашифрованном Production env; значения не повторялись в выводе. Серверный Blob token получен в закрытый provider snapshot; обычные Neon URL автоматически нормализуются Settings под установленный psycopg. Тестовые письма не отправлялись.
- Исправлен Windows offline bootstrap: ACL enrollment привязывается к SID текущего процесса и не зависит от отсутствующих USERNAME/USER в изолированном окружении. Повторный bootstrap успешно создал администратора; MFA не ротировался.
- Docker CLI установлен, но Linux engine сейчас недоступен. Локальная PostgreSQL этой попыткой не создана.

## Подключение Google OAuth

2 октября 2026 года владелец создал **DanaConnect Web**, OAuth client типа **Web application**. Client ID/secret сохранены в существующих закрытых `deploy/.env.owner-input.local` и `deploy/.env.vercel.local`; значения не включены в исходники. Структурная production validation прошла. Metadata Vercel подтвердила `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI`: все три encrypted и только Production.

Консоль Google подтверждает `https://danaconnect.vercel.app/api/v1/auth/google/callback` в Authorized redirect URIs. Audience — **External / Testing**. После отдельного подтверждения владельца его аккаунт добавлен в Test users; консоль подтвердила один тестовый аккаунт. Publish app заблокирован до завершения Branding; публикация OAuth app для всех не выполнялась. Локальное подтверждение сохранено в игнорируемом `artifacts/oauth-activation/google-test-user.jpg`.

Production deployment `dpl_ECG8WSv6JG2q4uQwZw9DDS3eA7PB` собран с новыми настройками, сообщил **READY**, alias `https://danaconnect.vercel.app` назначен. Предыдущий deployment `dpl_97q1BC7xQgFCX9BrLoyqFaefjosE` остаётся исторической записью. Полный вход и выдача cookie через Google не проверялись; Google account consent не подтверждался агентом.

## GitHub и автоматическая публикация

2 октября 2026 года исходники отправлены в предоставленный владельцем публичный репозиторий [Alizhan2/Danaconnect](https://github.com/Alizhan2/Danaconnect), первоначальная и основная ветка `codex/initial-platform`, коммит `404721b`. В первоначальный коммит включены 245 файлов. Закрытые конфигурации, локальные базы, enrollment MFA и локальные снимки экранов исключены; проверка содержимого staged files не обнаружила значения действующих секретов.

[GitHub Actions первого коммита](https://github.com/Alizhan2/Danaconnect/actions/runs/37002419498) завершился `success`: компиляция API, TypeScript и сборки web/admin. API-тесты не запускались; в workflow они оставлены только для явно выбранного ручного запуска.

Команда `vercel git connect` для существующего проекта `danaconnect` получила HTTP 400: **You need to add a Login Connection to your GitHub account first**. Поэтому автоматическая публикация из GitHub пока не подключена. Владельцу требуется подключить GitHub `Alizhan2` в Authentication своего рабочего аккаунта Vercel; затем повторить привязку репозитория и подтвердить production branch. Новый проект/провайдеры не создавались, прежний production deployment сохраняется. [Правила публикации](GIT_DEPLOYMENT.md).

## Подключение команды администраторов

2 октября 2026 года по поручению владельца создан первый дополнительный администратор в рабочей PostgreSQL. Отдельный metadata read подтвердил наличие аккаунта, роль `admin`, статус `active` и активный MFA credential. Имя/email и секрет не включены в публичные исходники. Enrollment находится в игнорируемом `deploy/enrollments/*.enrollment.json`; Windows ACL защищён от наследования и содержит одно правило доступа владельцу. Импорт MFA и рабочий вход нового администратора ещё не подтверждены; письмо-приглашение не отправлялось.

Подготовлен `deploy/provision_admin.py`: явная production-конфигурация, изолированное окружение, создание одного администратора с новым enrollment, безопасные сообщения результата. Он использует существующий offline bootstrap, не повышает зарегистрированных участников и не заменяет действующие MFA credentials. В общей роли `admin` сейчас полный административный доступ. Ограниченные координаторские роли и приглашения через интерфейс пока не реализованы. [Инструкция команде и ближайшие задачи](TEAM_LAUNCH.md).

По запросу владельца существующие enrollment владельца и дополнительного администратора преобразованы в отдельные локальные QR PNG. `deploy/enrollment_qr.py` использует существующий otpauth URI, не обращается к БД/внешним сервисам и не ротирует credential. PNG записывается только после ограничения Windows ACL; изображения исключены из Git, Vercel upload, Docker context и source packaging. Новые вызовы оператора создания администратора по умолчанию также формируют QR, после установки локальных operator dependencies. QR-сканирование и успешный вход пользователем ещё не подтверждены.

## Что требуется для каждого показателя

| Показатель | Реальное действие | Текущее состояние |
|---|---|---|
| PostgreSQL | Создать выделенную базу, получить TLS подключение, применить миграции к известной версии | Neon: новая база, TLS, head `0e82eab8e5ef`; опубликованный API сообщил DB ready |
| Почтовый провайдер | Подключить отправителя и ключ SMTP/Resend, передать настройки API и worker | Gmail SMTP credentials вошли в production, расписание QStash активно; фактическая доставка ещё не подтверждена |
| Google | Создать OAuth client приложения и настроить точный HTTPS callback | DanaConnect Web создан владельцем; callback совпадает, три настройки зашифрованы в Production. Google External / Testing; аккаунт владельца добавлен в Test users по его подтверждению. Полный вход не проверялся |
| Доверенные адреса HTTPS | Получить адрес настоящего выпуска, настроить FRONTEND_URL/TRUSTED_ORIGINS и прокси | Production alias опубликован, API доступен по HTTPS; same-origin настройки заданы |
| MFA всех администраторов | Создать администратора операторским bootstrap в рабочей БД, передать закрытое enrollment, подключить authenticator | Рабочий администратор с MFA credential создан; импорт authenticator и вход ожидают владельца |
| Учебные данные отключены | Подключить отдельную чистую рабочую БД, не запускать seed, активировать DEMO_MODE=false | Новая PostgreSQL создана без учебного seed; рабочий конфиг `DEMO_MODE=false`; локальная демоверсия остаётся отдельной средой |
| Коды разработки отключены | Настроить email credentials и активировать AUTH_DEBUG_CODE=false | Production настроен с `AUTH_DEBUG_CODE=false`; локальная демоверсия остаётся отдельной средой |

Private storage: ресурс Blob создан и его настройки записаны. Квоты Hobby и настройки адаптера: [BLOB_STORAGE.md](BLOB_STORAGE.md). Создание ресурса не является доказательством успешного upload/download/delete из приложения.

Обработка очереди: Vercel Hobby daily Cron не подходит для OTP. После подтверждения условий владельцем создан и подключён к Production QStash Free `danaconnect-jobs`, `primaryRegion=fra1`, `prodPack=false`. Получены закрытые `QSTASH_URL`, `QSTASH_TOKEN`, current/next signing keys; API hostname — `qstash-eu-central-1.upstash.io`. После публикации явно включено расписание `danaconnect-production-jobs`: GET к `/api/v1/internal/jobs`, `*/2 * * * *`, retries 0, Authorization redaction. Provider readback подтвердил ID, cron, метод, destination, нулевые повторы, `isPaused=false` и отсутствие callbacks. [Официальные квоты QStash](https://upstash.com/pricing/qstash). Во время активации исправлены формат destination URL и redaction: API требует обычную схему `https://` и принял `header[Authorization]` вместо отклонённого `headers`.

MFA readiness проверяет наличие активных credentials у всех активных администраторов; это не подтверждает, что владелец импортировал ключ и успешно вошёл. Почта, Google и storage readiness показывают наличие настройки, а не функциональную приёмку.

## Порядок активации

1. Вход, проект и бесплатная Neon выполнены. Платные операции и условия других провайдеров остаются отдельным действием владельца.
2. Заполнить закрытые подключения, используя существующие сгенерированные ключи. У API и worker одинаковые DB/auth/outbox/provider настройки.
3. Чистая рабочая БД и миграции выполнены; учебная база не переносилась.
4. Настроить email и владельца MFA. Импорт authenticator выполняет владелец; enrollment и коды не пересылаются в чат.
5. Выпуск и расписание QStash подключены. Google OAuth credentials получены и записаны в Production; доступ зависит от Google Audience/Branding и отдельного прохождения входа. Закрытая подготовка/явное включение расписания: [QSTASH_RUNBOOK.md](QSTASH_RUNBOOK.md).
6. Пройти структурную проверку и согласованную проверку рабочих входов/доставки/доступа. Обновить сводку операций из реально запущенной рабочей среды.

Текущие локальные приложения работают с прежними настройками. Переключение только AUTH_DEBUG_CODE без доставки почты блокирует новый вход; переключение DEMO_MODE не удаляет учебные записи. Поэтому подготовка и активация фиксируются отдельно.

Инструменты и команды: [RELEASE_PREPARATION.md](RELEASE_PREPARATION.md). Наблюдение: [MONITORING_RUNBOOK.md](MONITORING_RUNBOOK.md).

## Смена рабочего отправителя — 2 октября 2026

По запросу владельца рабочий Gmail стал отдельным SMTP-отправителем. Новый пароль приложения сохранён только в закрытых локальных файлах и зашифрованном Production env; обычный пароль Google не сохранялся. Обновлены EMAIL_FROM, SMTP_USERNAME и SMTP_PASSWORD; настройки OAuth и учетные записи администраторов не изменялись. Deployment с новыми env публикуется отдельно. Фактическая доставка нового письма ещё не подтверждена; тестовое письмо не отправлялось.

Опубликован Production deployment `dpl_3SmRzb34STVk471AaM8Mzdji8KJU`, статус READY, alias `https://danaconnect.vercel.app`. Сборки сайта, админки и API завершились успешно. Доставка письма с нового отправителя и повторный вход владельца пока не подтверждены.

## Направления программы и форма анкеты — 2 октября 2026

Владелец утвердил IT, Психологию и Образование. Все три активированы в Production PostgreSQL отдельной транзакцией с operator audit; публичный GET /api/v1/directions вернул три направления с названиями RU/KK/EN. Оператор deploy/activate_directions.py использует публичный manifest deploy/pilot_directions.json, не меняет существующие названия и не создаёт учебные данные, аккаунты или документы.

Для анкеты подготовлены сообщение о пустом списке, обновление направлений и проверка ссылок до отправки профиля. Вместимость поясняется как число менти одновременно. Обязательные документы и фактическая отправка анкеты требуют отдельных действий; новые юридические тексты не публиковались.

Форма опубликована в Production deployment `dpl_4UHY9jMns94hzfQ1ktG4ix4e2EoA`, READY, alias `https://danaconnect.vercel.app`. Сборки и TypeScript сайта/админки завершились успешно. Автоматические тесты и вход от имени пользователя не выполнялись.

## Готовность обязательных документов — 2 октября 2026

Запрос 553ac0cf-319a-42ce-ac27-aa78a3b43353 был POST /me/submit-registration, HTTP 409. Read-only проверка Production показала отсутствие активных документов и согласий. Это отсутствие публикации документов, а не пропуск пользовательского чекбокса.

Подготовлен GET /me/registration-requirements и общая серверная проверка готовности обязательных документов. При отсутствии публикации отправка возвращает понятное сообщение HTTP 503; интерфейс показывает состояние и отключает отправку. При наличии документов отдельно проверяются личные подтверждения конкретных версий. Проверки согласий не отключаются.

По запросу владельца подготовлены три локальных черновика в docs/legal-drafts/ (правила участия, политика данных, согласие). Каталог исключён из Git, Docker и Vercel; тексты и персональные реквизиты оператора не публикуются. Документы в Production не создавались, согласия за пользователей не подтверждались. Требуют утверждения фактические реквизиты, условия пилота и схема хранения/передачи данных; пакет содержит ссылки на официальный закон РК.

Исправление опубликовано: Production deployment `dpl_9wA7QwAi4gmEtu3XiD6diK5GPrzc`, READY, alias `https://danaconnect.vercel.app`. Сборки сайта, админки и API завершились успешно. Черновики остались локальными и не являются опубликованными документами; регистрация участников требует их утверждения, публикации и личных подтверждений. Тесты и подтверждения за пользователя не выполнялись.
