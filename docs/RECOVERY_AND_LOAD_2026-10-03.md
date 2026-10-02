# DanaConnect: восстановление и конкурирующие запросы

**3 октября 2026, Asia/Oral.** Техническая проверка следующего этапа: отдельное восстановление рабочей PostgreSQL, файлы/ключи на изолированных данных и нагрузочный пилот. Пользователь разрешил самостоятельные тесты. 20 одновременных клиентов — выбранный сценарий разработки; облачная ёмкость и эксплуатационные RPO/RTO владельцем ещё не согласованы.

## 1. Восстановление PostgreSQL

Источник — текущий Neon PostgreSQL **18.6**, миграция `0e82eab8e5ef`. Экспортирующая транзакция **REPEATABLE READ, READ ONLY** держала `pg_export_snapshot()`; fingerprint и `pg_dump --snapshot` читали один снимок. Прямое TLS-подключение использовалось вместо pooler. Production данные, роли, документы и настройки не изменялись.

Portable PostgreSQL 18.6 запущен отдельно на **127.0.0.1:55432**, с SCRAM и случайным закрытым паролем. Dump зашифрован Fernet; ключ сохранён отдельно от архива. Для упражнения ciphertext расшифрован в новую private папку, SHA256/manifest повторно проверены, затем восстановление выполнено в **новую локальную БД**. Приложение, почта и scheduler на восстановленных реальных аккаунтах не запускались.

| Проверка | Результат |
|---|---|
| Снимок | 3 октября, **00:34:38 Asia/Oral** |
| PostgreSQL | Source и target **18.6**, `server_version_num=180006` |
| Данные | **48 таблиц, 38 строк**; число строк и SHA256 полного `row_to_json` каждой таблицы совпали |
| Столбцы | **375**, определения совпали без нормализации |
| Constraints / indexes | **514 / 163**; сравнение описано ниже |
| Миграция | Source и target `0e82eab8e5ef` |
| Sequence / private attachments | **0 / 0** записей соответствующих объектов/таблицы |
| Locale | **UTF8, builtin, C.UTF-8**; recorded и actual collation version обе **1**, совпали |
| Custom archive | **141003 bytes**, checksum и encrypted roundtrip прошли |
| Время dump / restore | **12.76 / 14.70 секунды**, включая соответствующие CLI preflights; это локальное измерение, не RTO |

После перепарсинга 27 CHECK и 2 partial index имеют другую запись одного выражения: array-level `varchar[] → text[]` превращён в поэлементный `varchar → text`. Все **29** различий просмотрены отдельно; значения, порядок и весь остальной SQL совпали. Source и target `pg_cast` подтверждают binary-coercible varchar→text. Сравнение использовало только эту узкую замену; raw DDL hashes не объявляются одинаковыми. [PostgreSQL pg_cast](https://www.postgresql.org/docs/18/catalog-pg-cast.html).

Windows не принимает source OS LC_COLLATE/LC_CTYPE `C.UTF-8`; target хранит `C`. Применён явный `--allow-os-locale-difference` только на loopback: PostgreSQL builtin provider/datlocale/encoding/версии совпадают, версия не форсируется. [Параметры базы](https://www.postgresql.org/docs/18/catalog-pg-database.html), [builtin locale](https://www.postgresql.org/docs/18/locale.html). Эта проверка не подтверждает Production failover, роли/ACL провайдера или целиком одинаковые OS-настройки.

Архив, passfiles, исходные fingerprint и восстановленная база закрыты Windows ACL и исключены из Git/Vercel. В открытый отчёт не включены строки пользователей, ключи, токены или connection strings. Локальный сервер после проверки останавливается; private файлы сохраняются для повторной проверки. **Offsite copy, backup schedule и provider PITR этим этапом не настроены.** Текущих attachment records в рабочей БД нет, поэтому восстановление реальных Blob objects не проверялось.

Безопасное описание результата: [JSON summary](verification/postgres-restore-2026-10-03.json). Процедура: [CLOUD_RUNBOOK](CLOUD_RUNBOOK.md).

Дополнительно тот же расшифрованный архив восстановлен **во вторую новую локальную БД** через `--source-unavailable`. Wrapper запрещал каждую source PG-команду до исполнения: source attempts **0**, target commands **7**. Все строки 48 таблиц/38 записей, миграция и provider metadata совпали с сохранённым исходным fingerprint. Restore занял **7.70 sec**. Это имитация недоступного источника без обращения к нему, а не реальный сбой Neon. [Safe outage evidence](verification/postgres-outage-restore-2026-10-03.json).

## 2. Файлы, MFA и ключи

**6 recovery-тестов** используют отдельные synthetic SQLite snapshots, новые DB/storage paths и собственные ключи. Это дополнение к реальному PostgreSQL dump; рабочие MFA-ключи и Blob objects этими тестами не импортируются.

- Без объектов закрытый download возвращает 503; восстановленные bytes проходят проверку размера и SHA256. Повреждение или усечение возвращают 503.
- Anonymous получает 401, посторонний аккаунт — 404. Новый NDA требует нового согласия; удалённое membership закрывает доступ.
- Correct/missing/wrong/rotated outbox keyring проверены. Без правильного ключа MFA закрыт с 503, без выдачи cookie/сеанса/секрета; предыдущий ключ при ротации работает.
- Смена AUTH_SECRET делает восстановленный сеанс недействительным; тест не подменяет операционный отзыв сессий при настоящем переключении.

Backup сохраняет БД; local/S3/Blob objects и `AUTH_SECRET`/outbox-MFA keyring нужны отдельно. Откат может вернуть сессии, OTP/MFA challenges, TOTP replay state и leases; worker остаётся выключенным до сверки delivery и контролируемого отзыва старого состояния. At-least-once очередь может отправить письмо повторно.

## 3. Нагрузка и ограничения мест

Отдельная **пустая synthetic PostgreSQL 18.6** получила настоящие Alembic migrations до head. Параметры: UTF8/builtin/C.UTF-8, collation version 1. Runner стартовал собственный loopback API с обычной cookie authentication и persisted synthetic sessions. Почта, Google, файлы и AI отключены; реальных аккаунтов и запросов к Production нет.

**20 клиентов × 5 волн чтения**, конкурентные изменения и **4 calendar workers**: **280 HTTP-запросов**, **37/37 invariants**, **0 transport errors / HTTP 5xx**. Setup-запросы в это число не включены. Ожидаемые 409 при конкуренции считаются успешной защитой ограничения.

| Сценарий | Подтверждение |
|---|---|
| Один slot, 20 желающих | Один booking; 19 конфликтов |
| Повторное бронирование одним участником | Один и тот же booking ID, без второй записи |
| Создание одинакового slot | Один slot, 19 конфликтов |
| Пересечение встреч с разными менторами | Одна встреча у менти; проигравший slot остаётся свободным |
| Лимит ментора = 3 | 3 принятия, 17 конфликтов; число participation не превышено |
| Лимит проекта = 3 | 3 принятия, 17 конфликтов; число мест не превышено |
| Генерация расписания + 4 workers | Нет duplicate occurrences, generation errors и неожиданных записей outbox |

Локальное чтение: **p50 242.66 ms, p95 923.32 ms, max 1344.42 ms**. Весь workload: **p95 1344.42 ms, max 2165.84 ms**; percentile — nearest rank. Модули workers импортированы до измеряемой волны. Первый запрос/прогрев API остаётся в итоговых данных. Это один локальный Uvicorn, маленькая база и Windows; Vercel limits, SMTP/OAuth/MFA latency и большое число участников не измерялись. Из результатов не выводится production throughput/SLA.

Полный безопасный результат: [JSON load report](verification/postgres-load-2026-10-03.json). Повторение требует **новой пустой** локальной БД; runner отказывает для nonempty DB, remote endpoint, неправильного имени и query parameters, подменяющих host/service/options:

```powershell
.venv/Scripts/python.exe scripts/verification/postgres_load.py --database-url-file 'C:\защищённый\synthetic-db.url' --clients 20 --read-rounds 5 --report artifacts/verification/postgres-load.json
```

URL file хранит только подключение к буквальному loopback адресу и базе `dc_pilot_load_*` либо `danaconnect_load_*`. Runner запускается из нового temp directory с очищенным env; workspace dotenv не импортируется. GitHub Actions теперь отдельно повторяет этот пилот на PostgreSQL 18.6 service и сохраняет только safe JSON.

## 4. Найденные и исправленные ошибки

1. **Календарный worker:** после ожидания mentor FOR UPDATE мог вызвать generator для уже disabled rule или передать `None` для удалённого правила. Disabled rule не создавал slots благодаря внутренней защите, но ошибочно учитывался processed; deleted rule давал error. Добавлена post-lock проверка существования/active. Реальная PG-гонка до исправления: generation calls/processed 1; после: 0/0, created/errors 0. Две отдельные регрессии проверяют disable/delete. [Safe race evidence](verification/postgres-worker-race-2026-10-03.json).
2. **Новый backup CLI:** реальный restore выявил psql boolean `t/f`, где preflight ожидал JSON. Queries теперь сериализуют boolean через `to_json`; регрессия проходит настоящую цепочку `PgRunner.query → json.loads`. Restore повторён успешно.
3. **Locale нового target:** default template0 отличался от Neon. Manifest v2 теперь сохраняет locale metadata; CREATE и последующий check проверяют источник/target, а неподдерживаемые настройки отклоняются. Scoped loopback OS-исключение описано выше.

## 5. Проверки и выпуск

- Полный локальный API прогон: **192 passed**, 436.54 sec, 0 failed; один существующий Starlette TestClient/httpx deprecation warning. После добавления locale/outage cases отдельный полный набор backup CLI: **91 passed**; эти случаи также включены в CI.
- Frontend: **58 passed** (23 основные, 16 даты, 15 downloads, 4 navigation). Frontend source в этом этапе не менялся.
- Все 37 concurrency invariants повторены после изменения worker и на source-compatible builtin locale.
- Release commit, CI и результат публикации добавляются после выполнения выпуска.

## 6. Что ещё требуется для эксплуатации

Подтвердить допустимые потерю данных/время восстановления, retention, offsite storage и custody ключей; назначить ответственного. Когда появятся Blob objects, добавить отдельный verified object backup и recovery. Перед настоящим failover проверить роли/ACL, provider настройки, полную совместимость locale, отзыв auth-state и reconciliation очереди. Техническое восстановление и synthetic пилот не публикуют юридические документы и не снимают блокер регистрации: [оставшиеся этапы](LAUNCH_REMAINING.md).
