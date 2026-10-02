# Планировщик production: Upstash QStash

Один ресурс QStash Free подключён к production проекту. Само подключение ресурса **не создаёт расписание** и не подтверждает работу приложения. Расписание включается оператором после публикации рабочего production endpoint.

## Конфигурация

В защищённом operator dotenv-файле должны быть реальные `QSTASH_URL`, `QSTASH_TOKEN`, `CRON_SECRET`, `FRONTEND_URL`, `TRUSTED_ORIGINS` и `OPERATOR_SCHEDULER=qstash`. Использовать URL, выданный именно этому ресурсу; не подменять регион значением из примера. Ключи не отправлять в чат, не сохранять в Git, не добавлять в `NEXT_PUBLIC_*`.

Скрипт принимает только точные HTTPS адреса `qstash.upstash.io`, `qstash-eu-central-1.upstash.io`, `qstash-us-east-1.upstash.io`. Другой выданный провайдером адрес требует отдельной проверки и изменения allowlist в исходнике. Redirect, proxy из окружения, альтернативный порт, credentials в URL и query запрещены. Значения приложения не импортируются из локальной `.env` или из окружения процесса.

Production должен явно отключать `DEMO_MODE` и `AUTH_DEBUG_CODE`. `CRON_SECRET` — отдельный случайный ключ минимум 32 символа, отличный от auth/outbox/provider ключей. При смене ключа сначала синхронизировать конфигурацию production API, затем обновить расписание тем же стабильным ID.

## План и включение

По умолчанию скрипт ничего не читает и не подключается к сети:

```powershell
.\.venv\Scripts\python.exe deploy/configure_qstash.py
```

Явная проверка приватной конфигурации остаётся офлайн:

```powershell
.\.venv\Scripts\python.exe deploy/configure_qstash.py --env-file deploy/.env.vercel.local
```

После публикации оператор подтверждает, что production endpoint `FRONTEND_URL/api/v1/internal/jobs` готов выполнять задания. Приложение должно читать те же PostgreSQL, auth/outbox/mail/storage настройки. Перед активацией скрипт требует полную структурно корректную production-конфигурацию, включая email credentials. `--deployment-ready` является утверждением оператора; скрипт не проверяет endpoint и не отправляет письма самостоятельно.

```powershell
.\.venv\Scripts\python.exe deploy/configure_qstash.py --env-file deploy/.env.vercel.local --apply --deployment-ready
```

Команда создаёт либо обновляет **активное** расписание `danaconnect-production-jobs` с частотой `*/2 * * * *`, методом GET, пустым body и `retries=0`. Повторная команда обновляет тот же ID. Она не удаляет чужие расписания и не гарантирует, что другие операторские расписания отсутствуют.

QStash получает собственный `QSTASH_TOKEN`, а API получает `Authorization: Bearer CRON_SECRET` через `Upstash-Forward-Authorization`. `Upstash-Redact-Fields: header[Authorization]` скрывает именно секретный forwarded Authorization в сообщениях провайдера. После upsert скрипт читает запись по стабильному ID и сверяет только ID, адрес, метод, cron, retries, активность и отсутствие callbacks. Ответы, headers и исключения провайдера не выводятся. API требует незакодированную схему `https://` в части URL назначения; origin предварительно валидируется.

Успех команды подтверждает конфигурацию расписания у провайдера. Успешное выполнение заданий и принятие/доставка писем остаются отдельными наблюдениями. Через admin operations смотреть время heartbeat, очередь due, ошибки и stale worker. Отключить прежний worker/дублирующие cron оператором после перехода, чтобы не создавать лишние запуски.

## Квота и ошибки

Free: 1000 delivery attempts в сутки и 10 активных расписаний. Один GET каждые две минуты даёт 720 попыток в сутки. Запас 280 разделяется с любыми другими запросами этого ресурса. `retries=0` исключает автоматические повторы QStash; после пропущенного запуска следующий будет через две минуты. Внутренние повторы писем выполняет application outbox, а не QStash. Непрерывная работа и SLA этим тарифом не подтверждаются.

Если ответ после upsert потерян или readback не совпал, расписание **могло уже включиться**. Сначала проверить `danaconnect-production-jobs` в консоли провайдера. Не создавать второй ID. Для остановки использовать Pause/Delete именно этого ID в консоли; скрипт остановку не выполняет. Не выводить raw schedule response: оно может содержать headers с секретами.

## Источники

- [QStash Create Schedule API](https://upstash.com/docs/qstash/api-reference/schedules/create-a-schedule): стабильный ID/upsert, GET, retries, forwarded authorization, redaction.
- [QStash Get Schedule API](https://upstash.com/docs/qstash/api-reference/schedules/get-a-schedule): readback полей расписания.
- [QStash pricing](https://upstash.com/pricing/qstash): Free quota и учёт попыток доставки; Prod Pack является платным дополнением и не включён.

Исходник подготовлен без выполнения сетевых команд активации и без функциональных тестов.
