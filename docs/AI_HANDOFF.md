# AI_HANDOFF — состояние проекта NORA

> Обновлено 01.11.2026. Это контекст разработки, а не реестр production-версий.
> В начале каждой сессии читать AGENTS.md, затем этот файл; сверять с Git.
> Не хранить секреты, токены, initData, содержимое .env и рабочей БД.

## Правила сессий и публикации

- Одна сессия — одна конкретная задача; продолжение задачи сохраняет её ветку.
- Перед новой задачей: git status --short --branch, git branch --show-current,
  git fetch origin, git log -5 --oneline и проверка базы относительно
  origin/cursor/nora-2-update-d133. main содержит старую версию.
- Новую разработку вести в chatgpt/<название-задачи>, созданной от актуальной
  origin/cursor/nora-2-update-d133. Не переносить чужие изменения автоматически.
- С 01.11.2026 прежнее постоянное разрешение на выпуск отменено владельцем.
  Без явного разрешения не менять production-ветку, не коммитить, не выполнять
  push, merge в production или deploy. По умолчанию оставлять локальный diff.
- Перед завершением: доступные проверки, git diff, git diff --check, git status,
  обновление handoff и краткий отчёт о сделанном, проверках и оставшихся задачах.
- При приближении лимита контекста записать результаты, незавершённые изменения,
  ветку, решения и точный следующий шаг для следующей сессии.

## Фактическое состояние рабочей копии

- Репозиторий: C:/Users/User/Projects/nore-community-bot, origin — GitHub
  fedorabakumets/nore-community-bot; доступ к исходникам и чтение GitHub проверены.
- Задача: подготовка локальной разработки Codex; ветка chatgpt/codex-dev-setup.
- Создана от актуальной origin/cursor/nora-2-update-d133; fetch и сравнение
  показали 0 опережающих / 0 отстающих коммитов на момент подготовки.
- Upstream у feature-ветки снят, чтобы она не отслеживала production для push.
- До задачи рабочее дерево было чистым. Подготовлены только AGENTS.md и этот
  файл; бизнес-логика, зависимости pyproject.toml и production не изменялись.
- Коммиты и публикация не выполнялись. Перед следующей независимой задачей
  нужно решить судьбу этих локальных изменений; не смешивать их с новой задачей.

## Как проверять реальную production-версию

- Railway настроен на ветку cursor/nora-2-update-d133; её GitHub HEAD сам по себе
  не доказывает, что сборка уже развёрнута.
- Получить актуальный HEAD через git fetch origin / git ls-remote, затем сверить
  commit активного успешного deployment в Railway либо доступный GitHub
  deployment/status с соответствующей средой и доменом.
- Проверить https://nora-bot-production-2126.up.railway.app/healthz и отличимые
  маркеры/содержимое изменённой статики на этом же домене. /healthz подтверждает
  доступность, но не идентичность версии и не работу Telegram polling.
- После разрешённого выпуска отдельно проверить polling по доступным логам
  или согласованному сценарию. Не запускать для этого локальный main.
- Если статуса Railway или логов нет, честно указать границы проверки.
  В этой задаче deployment и polling не проверялись, выпуск не запускался.

## Архитектура и последние изменения кода

- Один asyncio-процесс community_bot/main.py: Telegram long polling (aiogram),
  Mini App HTTP-сервер (aiohttp), фоновые задачи; общая SQLite через aiosqlite.
- community_bot/routers/ — Telegram; miniapp.py, *_api.py, admin_web.py — HTTP API.
  Авторизация Mini App по Telegram initData; статика community_bot/web/ без сборки.
- database.py — схема/операции SQLite; экономика, питомцы, события и уведомления
  вынесены в прикладные модули. Railway хранит данные на томе /app/data.
- По последним Git-коммитам: исправлены лобби после принятия приглашения в
  Морской бой и приглашения в коммьюнити; перед этим добавлены подсветка
  непрочитанных уведомлений и автоматическая отметка при открытии.
- Ранее исправлены промахи/потопления на обеих досках, состав флота, нормализация
  JSON, игра с ботом и лишняя перерисовка. Есть tests/test_sea_miniapp.py.
- Последний коммит базовой ветки предназначен для повторного запуска сборки;
  его наличие не считать доказательством успешного deployment.
- README и часть docs/ описывают снимок от 25.10.2026 (например, прежнее отсутствие
  HTTP-сервера и старое число тестов). При расхождениях доверять коду и Git.

## Локальная среда Windows

- Найден рабочий Python 3.12.14:
  C:/Users/User/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe
- Команды python/python3 в PATH указывают на Windows Store; использовать явный
  .venv/Scripts/python.exe. Node.js и Git доступны. Менять системный PATH не нужно.
- Создана .venv; установлено pip install -e '.[dev]' tzdata. tzdata добавлена только
  локально для zoneinfo на Windows; pyproject.toml не менялся.
- .venv исключена из Git. Базовый Python принадлежит кешу Codex: при его удалении
  окружение придётся пересоздать от рабочего Python >=3.11 (предпочтительно 3.12).
- Обычные команды PowerShell (активация не требуется):
  ./.venv/Scripts/python.exe -m pip check
  ./.venv/Scripts/python.exe tools/check_local.py
- Перед проверками отключать чтение .env: $env:PYTHON_DOTENV_DISABLED = '1'.
  Никогда не запускать community_bot.main / nore-bot и второй poller.
- check_local.py сначала запускает Ruff; при ошибках прекращает работу до pytest.
  Для pytest он убирает BOT_TOKEN и блокирует Python socket connect/DNS.
- На Windows эта блокировка мешает внутреннему socketpair asyncio. Для локальной
  диагностики сохранён игнорируемый .venv/check_windows.py: использует GUARD из
  штатного runner, разрешает connect только внутри socketpair в текущем потоке
  на loopback, остальные подключения блокирует. Отключает .env, убирает BOT_TOKEN,
  задаёт временную DATABASE_PATH. Тесты используют tmp_path и fake/mocked Bot.
- Запуск: ./.venv/Scripts/python.exe .venv/check_windows.py
  либо добавить -q tests/test_sea_miniapp.py --tb=short для конкретных тестов.
  Это локальный helper: исчезнет при пересоздании .venv, не заменяет общий check_local.

## Проверки этой задачи

- pip check: No broken requirements found.
- node --check: все 12 JavaScript-файлов community_bot/web прошли.
- tools/check_local.py: остановился на 14 существующих E501 в database.py,
  sea_api.py и sea_notifications.py. Код не исправлялся в документационной задаче.
- Отдельный pytest с неизменённым GUARD: 120 passed, 1 failed, 508 errors;
  массовые ошибки setup вызваны заблокированным внутренним socketpair Windows.
- Полный диагностический pytest с исключением для socketpair: 624 passed,
  5 failed, 39 warnings (206.67 с). Четыре сбоя в profile_maintenance/release_backup:
  os.fsync на открытом для чтения файле в release_backup.py:34 даёт на Windows
  Bad file descriptor. Один в test_telegraph_images.py:49: symlink требует
  прав Windows (WinError 1314). Ошибок setup после исключения для socketpair нет.
- Локальный helper: проверка asyncio и запрета обычных внешних/loopback-соединений
  прошла; tests/test_sea_miniapp.py — 21 passed.

## Остаток и решения для владельца

- Отдельной задачей согласовать исправление замечаний Ruff и переносимость
  штатных проверок на Windows; не скрывать их исключениями в проектной конфигурации.
- Для полного зелёного прогона отдельно исправить переносимость backup и решить
  запуск symlink-теста (например, Linux/WSL либо согласованная настройка Windows).
  Права Windows, тестовые ожидания и backup-код в этой задаче не менялись.
- git diff проверен: изменены только два документа; git diff --check без замечаний.
- Решить, когда коммитить и публиковать подготовленную документацию.
- Production SQLite, её целостность, значения переменных Railway и backup/restore
  не исследованы; знание схемы по коду не является проверкой рабочей базы.
