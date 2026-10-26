# Нора — Telegram community bot

Один Python-процесс обслуживает личные чаты и группу: анкеты, тикеты,
профили, кабинет, модерацию, печеньки, магазин, игры и питомцев.
Кабинет находится внутри Telegram. Отдельного веб-приложения и собственного
HTTP API в проверенном исходном дереве нет.

## Документация

- [Архитектура](docs/ARCHITECTURE.md)
- [Разработка и выпуск](docs/DEVELOPMENT.md)
- [Аудит](docs/AUDIT.md)
- [Передача проекта](docs/MIGRATION.md)
- [Кабинет и экономика: изменения и проверки](docs/CABINET_ECONOMY.md)
- [Студия постов и запись на события](docs/STUDIO_RSVP.md)

Документация подготовлена 25 октября 2026 по исходникам развёрнутого коммита
`00d9e08621c527d827ffc258424eb047d0c3e19e` и диагностике Railway.
Ветка подготовки: `chatgpt/onboarding-audit`. Изменения предназначены для review.

## Ветки и безопасные проверки

`main` содержит старую версию. Railway production автоматически развёртывает
`cursor/nora-2-update-d133`; её HEAD совпал с production SHA при проверке.
Не отправляйте изменения в эту ветку без разрешения на публикацию.

Python >=3.11 (в среде разработки 3.12):

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python tools/check_local.py
.venv/bin/python -m pip check
```

`check_local.py` запускает Ruff и pytest, блокируя сетевые подключения Python
при выполнении tests. Тесты используют временную SQLite и fake Bot.
Не помещайте production секреты и рабочую базу в эту копию.
На исходном commit: 148 tests passed, Ruff без замечаний, pip check успешен.

## Настройки и запуск

Настройки перечислены в `.env.example` и `community_bot/config.py`.
Для интеграционной проверки нужны отдельные тестовые бот, чат и SQLite.
Обязательны BOT_TOKEN и ненулевой OWNER_ID. OWNER_IDS дополняет OWNER_ID;
COMMUNITY_CHAT_ID имеет приоритет перед GROUP_ID. Секреты храните вне Git.

До запуска явно настройте SBP_PAYMENT_URL и COMMUNITY_INVITE_URL: код содержит
прежние значения по умолчанию. Не используйте их для нового владельца без
проверки. Реквизиты и приватное приглашение здесь не повторяются.

```sh
# Только после настройки отдельного тестового окружения:
.venv/bin/python -m community_bot.main
```

Запуск main меняет SQLite, команды Telegram, webhook и может публиковать
объявления и Telegraph. Не используйте main как healthcheck. Не запускайте
второй poller с production BOT_TOKEN.

## Данные и контейнер

SQLite создаётся по DATABASE_PATH. В Railway том nora-data смонтирован в
/app/data; фактическое production значение DATABASE_PATH не извлекалось.
Dockerfile не копирует базу из репозитория. В проверенном Git-дереве базы нет,
хотя прежний README обещал вложенную копию. При пустом томе приложение создаёт
новую базу; это не перенос пользователей, ролей и балансов.

Изменения production, deploy, миграции, backup/restore и перенос аккаунтов
требуют отдельного согласования. Диагностика production не изменяла.
