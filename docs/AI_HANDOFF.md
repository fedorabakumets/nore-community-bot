# AI_HANDOFF — NORA

> Состояние на 02.11.2026. При расхождении доверять Git. Секреты и данные production-БД сюда не записывать.

## Работа и выпуск

- В начале сессии читать `AGENTS.md`, затем этот файл; проверять `git status`, ветку и `git fetch origin`.
- Railway отслеживает `cursor/nora-2-update-d133`; `main` отстаёт. Разработку вести в отдельной `chatgpt/*` от актуальной origin production, без upstream на production.
- Владелец разрешил commit/push/merge/deploy завершённых задач по умолчанию, если не попросил остановиться. Не запускать локально production poller; не читать/выводить секреты; не менять production-БД вручную, миграции или Railway env без отдельного разрешения. Для согласованного прямого изменения БД нужен backup.
- Git identity для NORA: Roman Kondrikov / romankondrikov044@gmail.com.
- Исходная копия `C:/Users/User/Projects/nore-community-bot` на `chatgpt/codex-dev-setup` содержит незавершённые правки `AGENTS.md` и `docs/AI_HANDOFF.md`; оставлена нетронутой.

## Архитектура и проверки

- `community_bot/main.py`: один asyncio-процесс Telegram polling и Mini App HTTP; общая SQLite в `database.py`. Статика Mini App — `community_bot/web/`, без сборки.
- Проверки Windows: задать `PYTHON_DOTENV_DISABLED=1`; использовать `.venv/Scripts/python.exe tools/check_local.py` и `-m pip check`. Тесты — только временная SQLite и fake Bot. В отдельном worktree использовался `.venv` исходной копии.
- В актуальной production-базе 14 существовавших Ruff E501; `check_local.py` останавливается до pytest. На Windows также известны четыре сбоя `fsync` файла `rb` и один symlink без привилегий. Не исправлять их заодно с продуктовой задачей.
- После выпуска: проверить `/healthz`, отличимый маркер статики, по возможности Railway deployment и Telegram polling. Один успешный HTTP-запрос не доказывает отправку сообщения ботом.

## Задача: поздравления и подарок (02.11.2026)

- Worktree `C:/Users/User/Projects/nore-community-bot-birthday`, ветка `chatgpt/birthday-gifts`, база `d19300a` после fetch совпала с origin production; upstream снят. Исходные изменения документации не переносились.
- Добавлен `birthday.py`: поздравление в чат с HTML-упоминанием, цитатой и иллюстрацией `assets/birthday/gift.png`; одноразовое предложение 500 🍪, общий атомарный claim через бота и Mini App. Кнопка есть в групповом посте, личке, уведомлениях бота и Mini App. Получение гостем в боте разрешено без анкеты.
- Даты будущих участников пока не собираются; задача анкетирования остаётся открытой. Подготовлен источник `bot_state` с ключом `birthday_date:<telegram_id>` и значением `MM-DD`. На 02.11.2026 добавлен разовый поиск `@Caramel_kka` по users.username и тестовый подарок владельцу. Если ID именинницы не найден, групповой пост идёт по @username, а подарок привязывается при её нажатии; личная доставка до её контакта с ботом невозможна.
- Новые тесты на временной SQLite проверяют единственность начисления при одновременном claim, разовую отправку, формат и получение именинницей без записи в users. Точечный Ruff, `node --check`, 18 целевых тестов, `pip check` прошли. Полный pytest: 654 passed, 5 прежних Windows failures, 39 warnings.
- До завершения: проверить diff/status, включить этот handoff в коммит с кодом, опубликовать в production по разрешению владельца, проверить `/healthz` и маркер Mini App. Фактическую доставку в Telegram и наличие записи `@Caramel_kka` подтвердить только по доступным production-сигналам; без них не заявлять успех.
