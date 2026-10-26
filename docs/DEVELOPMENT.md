# Разработка и выпуск

## Доступ и рабочая копия

GitHub connector читает публичный fedorabakumets/nore-community-bot;
pull=true, push=false. Код находится в /workspace/nora-source.
chatgpt/onboarding-audit создана от развёрнутого SHA; HEAD Cursor-ветки совпал с ним.
Локально доступны редактирование, ветки, тесты и подготовка патчей.
Для отправки веток в исходный repo нужен Write и доступ GitHub-подключения.
Для PR без Write можно использовать fork в аккаунте пользователя, если
доступный credential разрешает создание fork и запись в него.

Railway API проверен Project Token: inventory, deployments, logs, backups и metrics.
Постоянного секрета среды нет. Токены не сохранены в файлах или git config.
Для следующих сессий нужен защищённый secret binding RAILWAY_TOKEN.

## Проверки

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python tools/check_local.py
.venv/bin/python -m pip check
```

check_local.py блокирует Python socket connections/DNS на время pytest.
Это защита существующих Python tests, не общий sandbox внешних CLI.
Не добавлять тесты, запускающие реальные сервисы или внешние сетевые команды.
Для интеграционных проверок использовать отдельные бот, чат и базу.

Проверено: 148 passed; Ruff 0; pip check без конфликтов.
Production DB integrity, restore test, Docker build и живые Telegram-сценарии
не проверялись. Пакеты установлены по диапазонам pyproject и могут отличаться
от зависимостей уже развёрнутого образа.

## Выпуск только после отдельного разрешения

1. Сверить SHA и настройки Railway, создать отдельную feature-ветку.
2. Подготовить патч, релевантные tests, diff/PR и план отката.
3. До push проверить branch/PR deployment triggers: Cursor-ветка запускает production.
4. При изменении БД согласовать консистентный backup и restore test с учётом WAL.
   Откат кода не откатывает данные.
5. Получить разрешение на конкретную публикацию; после deploy проверить updates,
   errors, фоновые задачи и сохранность данных.

Предлагаемый будущий процесс: protected release-ветка, обязательные CI checks,
отдельная staging-среда/бот и approval production. Настройки пока не менялись.

Не копировать работающий .db простым copy как гарантированно корректный backup:
использовать SQLite backup API либо согласованный snapshot с учётом WAL.
Checkout не содержит рабочей базы. initialize() создаёт новую пустую базу.
