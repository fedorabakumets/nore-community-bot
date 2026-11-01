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
- Задача: подготовка разработки и совместимость проверок Windows; ветка chatgpt/codex-dev-setup.
- Создана от актуальной origin/cursor/nora-2-update-d133; fetch и сравнение
  показали 0 опережающих / 0 отстающих коммитов на момент подготовки.
- Upstream у feature-ветки снят, чтобы она не отслеживала production для push.
- Документация закоммичена с разрешения владельца: c53b7ae; последующие
  исправления проверок и этот handoff подготовлены к локальному коммиту.
  Push/deploy не выполнялись. Фактические HEAD и status проверять через Git.

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
- На Windows runner допускает loopback только внутри создания socketpair asyncio;
  обычные подключения и DNS остаются заблокированы. Отдельный тест проверяет
  asyncio, запрет внешнего/локального соединения и DNS. Чтение .env отключено.
- Ранее созданный .venv/check_windows.py устарел; использовать штатный runner.

## Проверки и оставшиеся задачи (01.11.2026)

- Подготовлен локальный `.github/workflows/linux-ci.yml`: Ubuntu, Python 3.12,
  установка `.[dev]`, pip check и полный изолированный check_local.py, включая
  тесты symlink и Unix-прав. Linux CI ещё не запускался и не подтверждён.
- Владелец сообщил о проверке Railway API: prDeploys и botPrEnvironments выключены,
  единственный production-сервис привязан к cursor/nora-2-update-d133. Требуется
  завершить проверку diff, создать коммит, push feature-ветки и Draft PR, дождаться CI.
- Владелец подтвердил Git identity Roman Kondrikov для следующих коммитов NORA;
  полные настройки и ограничение на другие identity указаны в AGENTS.md.
- Workflow и правила закоммичены как 912e2be. Владелец принимает остаточный риск
  непроверенных сторонних GitHub-интеграций и разрешил push и Draft PR без merge.
- Запрос projectToken к официальному Railway API заблокирован Cloudflare HTTP 403
  (1010) до ответа GraphQL. Действительность токена и его права не установлены;
  настройки самостоятельно не проверены; позднее владелец сообщил результаты выше.

- Разрешённые исправления: backup открывает файл r+b перед fsync; Unix-права
  строго проверяются на не-Windows, тесты Windows проверяют остальное; 14 E501
  устранены. Сетевая блокировка адаптирована для socketpair Windows; отдельный
  тест подтверждает блокировку обычного loopback, внешнего адреса и DNS.
- Штатный tools/check_local.py: Ruff прошёл; pytest 629 passed, 1 failed,
  39 warnings. Единственный сбой test_telegraph_images.py:49: WinError 1314,
  не хватает права создания символической ссылки. Тест не отключён.
- pip check прошёл. Переносы строк в трёх файлах сверены по AST без изменений.
- Для полного зелёного прогона нужен Linux/WSL либо согласованная настройка
  прав Windows на символические ссылки. Проверки прав Unix на Linux не запускались.
- Следующая сессия: прочитать AGENTS.md и handoff, проверить status и log в
  chatgpt/codex-dev-setup; после fetch сравнить с origin/cursor/nora-2-update-d133.
- В Linux/WSL создать отдельное окружение и выполнить tools/check_local.py и
  pip check с временной SQLite и fake Bot, включая тест symlink и Unix-прав;
  не запускать production-бота. При отставании базы проверить diff и конфликты.
- Для переноса в production получить отдельное разрешение владельца на push,
  merge и deploy. После разрешённого выпуска проверить статус Railway, /healthz,
  версию и polling; не считать успешный push подтверждением деплоя.
- Production SQLite, значения переменных Railway и backup/restore не исследованы.
