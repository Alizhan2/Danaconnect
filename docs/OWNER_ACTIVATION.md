# Действия владельца для подключения входа

Рабочая Neon PostgreSQL и администратор созданы. Эти действия требуют доступа владельца к Google-аккаунту и authenticator. Секреты вводятся только в закрытые локальные файлы; в чат их отправлять нельзя.

## MFA администратора

Откройте локальный `deploy/admin.enrollment.png`. В Google Authenticator или Microsoft Authenticator выберите добавление аккаунта по QR и отсканируйте изображение. Приложение покажет шестизначный код; его нужно ввести в форму MFA на `/admin/login`.

Если сканирование недоступно, используйте `manual_entry_key` из `deploy/admin.enrollment.json` для добавления вручную, тип — по времени. После импорта сообщите «MFA добавлен». Импорт не является подтверждением успешного входа. После сохранения аккаунта в authenticator удалите enrollment JSON и PNG; оба содержат секрет и исключены из Git, Vercel upload и Docker context.

Повторный локальный экспорт существующего enrollment: `python deploy/enrollment_qr.py --enrollment deploy/admin.enrollment.json`. Нужны зависимости `deploy/requirements.operator.txt`. Экспорт использует существующий ключ, не обращается к БД и не меняет MFA credential. Существующее изображение не перезаписывается.

## Почта без собственного домена

Gmail app password уже сохранён в закрытой конфигурации и Production env; сайт опубликован и расписание QStash включено. Фактическая доставка письма ещё не подтверждена. Следующие шаги описывают настройку или будущую замену credential.

Для Gmail SMTP нужен пароль приложения Google. Это отдельный credential; обычный пароль аккаунта не используется. Google требует включённую двухэтапную проверку, а доступность app passwords зависит от настроек аккаунта. [Инструкция Google](https://support.google.com/mail/answer/185833?hl=ru).

1. Откройте [пароли приложений](https://myaccount.google.com/apppasswords), создайте пароль для DanaConnect.
2. Откройте закрытый локальный `deploy/.env.owner-input.local` и заполните `SMTP_PASSWORD`.
3. Сообщите «почта готова». Ключ будет перенесён в закрытую production-конфигурацию; scheduler и deployment подключаются отдельно.

Resend требует настройки собственного отправителя/домена. Пока домена нет, этот файл подготовлен для Gmail; владелец может выбрать другой провайдер.

## Вход через Google

В [Google Cloud Console](https://console.cloud.google.com/) создайте или выберите свой проект, настройте Google Auth Platform и OAuth client типа **Web application**. Клиент и consent screen создаются в аккаунте владельца. [Официальная настройка OAuth](https://developers.google.com/identity/protocols/oauth2/web-server).

- Origin: `https://danaconnect.vercel.app`.
- Authorized redirect URI: `https://danaconnect.vercel.app/api/v1/auth/google/callback`.
- Приложение запрашивает только `openid email profile`.
- В режиме Testing добавьте аккаунт владельца в test users. Такой режим не подтверждает доступ для всех участников; публикация и требования Google проверяются отдельно.
- Заполните `GOOGLE_CLIENT_ID` и `GOOGLE_CLIENT_SECRET` в закрытом `deploy/.env.owner-input.local`. URI будет выставлен в рабочей конфигурации одновременно с credentials.

2 октября 2026 года владелец создал OAuth client **DanaConnect Web** типа **Web application** и передал credentials. Они сохранены в закрытых owner-input/production файлах и трёх зашифрованных Production environment variables Vercel. Консоль Google подтверждает точный callback выше. Authorized JavaScript origins пусты; для используемого серверного OAuth redirect flow браузерный JS SDK не используется.

Google Auth Platform пока **External / Testing**. С разрешения владельца его аккаунт добавлен в Test users; консоль подтвердила один тестовый аккаунт. Публичная доступность входа не подтверждена; публикация OAuth app для всех потребует завершить Branding и требования Google. Полный вход через Google не проверялся.

## Дополнительные администраторы

В рабочей PostgreSQL создан первый дополнительный администратор по предоставленному владельцем имени/email. Для каждого администратора используется отдельный защищённый enrollment; контакты и ключи не публикуются в GitHub. Роль admin даёт полный доступ; ограниченная роль координатора пока не реализована. Порядок передачи доступа и набора менторов: [TEAM_LAUNCH.md](TEAM_LAUNCH.md).

Вход администратора выполняется на `/admin/login` по email-коду и Authenticator. Google-вход в текущей реализации предусмотрен для обычных участников и отклоняется для администратора.

## Облачная очередь писем

Условия Upstash приняты, QStash Free создан в Frankfurt и подключён к Production; платный Prod Pack отключён. Активировано одно расписание каждые две минуты к опубликованному защищённому endpoint; повторы QStash отключены, повторные попытки отправки выполняет transactional outbox. Настройки закрытого CRON_SECRET в URL не передаются; секретный Authorization скрывается через redaction. Сам факт расписания не подтверждает доставку писем.
