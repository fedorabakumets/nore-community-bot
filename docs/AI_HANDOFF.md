# AI_HANDOFF — состояние проекта NORA

> Компактная передача контекста между сессиями агентов. Держать до ~150 строк.
> Документ может устареть: фактическое состояние репозитория приоритетнее записей.
> Секреты, токены и содержимое .env сюда не записывать.

## Общее состояние

NORA — Telegram-бот сообщества + Mini App. Один asyncio-процесс
(`community_bot/main.py`): Telegram long polling (aiohttp/aiogram) и
HTTP-сервер Mini App (aiohttp), общая SQLite (том /app/data в Railway).

- Бот: `community_bot/routers/` (private, group, games, pets, wallet, admin, shop_admin).
- Mini App: `miniapp.py` + `*_api.py` (shop, events, cabinet, community, friends,
  mafia, rocket), `admin_web.py`, `social_profiles.py`, `seasonal.py`.
- Frontend: `community_bot/web/` без сборки (index.html, style.css, app.js,
  intro.js, home.js, shop.js, cabinet.js, admin.js, events.js и др.).
- Логика: economy, cookie_logic, reputation, event_manager, contest,
  pets_talk/expedition, notify, posting, morning, telegraph, stickers.
- Тесты: `tests/` (pytest, изолированная SQLite, fake/mocked Bot).
- Подробная карта — в `AGENTS.md`; тематические детали — в `docs/`.

## Текущая версия (проверено 31.10.2026)

- Ветка: `cursor/nora-2-update-d133` (её разворачивает Railway), upstream
  `origin/cursor/nora-2-update-d133`.
- Базовый коммит на 31.10.2026: `a671d92` — «feat: add smooth NORA app entrance
  animation»; локальный и удалённый HEAD совпадали.
- На нём — коммит с правилами handoff (`AGENTS.md` + этот файл), поэтому HEAD
  может быть на 1 коммит новее; сверять через `git log -3 --oneline`.
- Перед `a671d92` — серия merge PR #48–#51 (community tiles, fullscreen nav/inset,
  live daily top five без бот-аккаунтов).
- Рабочее дерево на момент проверки: чистое (изменения handoff закоммичены).

## Последние изменения (по Git)

1. `a671d92` — плавная анимация входа в Mini App (entrance animation).
2. PR #51 (`17a3198`) — живой ежедневный топ-5 в community, скрытие бот-аккаунтов.
3. PR #50 (`66fc9fe`) — fullscreen-контент не перекрывается Telegram-контролами.
4. PR #49 (`143553a`) — выравнивание плиток community и навигация профиля в fullscreen.
5. PR #48 — подписи/лейблы питомцев в community.

## Незавершённые задачи

- Открытых задач по документации нет. Реализация функций — по запросу владельца
  в ветке `chatgpt/<task>` с merge в `cursor/nora-2-update-d133`.

## Известные проблемы / техдолг

- `main` отстаёт от production-ветки; перед исправлениями сверять базовый SHA.
- Production SQLite и переменные Railway не исследованы; схема по коду не
  гарантирует целостность рабочей базы.
- Railway CLI / RAILWAY_TOKEN обычно недоступны — статус деплоя подтверждать
  через `/healthz` и маркеры в статике.

## Следующие шаги

- Закоммитить и (по разрешению) опубликовать изменения `AGENTS.md`/`AI_HANDOFF.md`.
- Далее работать по запросам владельца в ветке `chatgpt/<task>`, merge в
  `cursor/nora-2-update-d133` по действующему разрешению.

## Правила продолжения

1. В начале сессии: прочитать `AGENTS.md`, затем этот файл.
2. Сверить записи с фактом: `git branch --show-current`, `git status`, `git log -3 --oneline`.
3. После значимой задачи обновить разделы «Последние изменения» и
   «Незавершённые задачи»; в конце сессии — зафиксировать сделанное и решения.
4. Держать документ компактным: только состояние и решения, без логов и кода.
5. Если запись противоречит репозиторию — доверять репозиторию и обновить запись.
6. Не делать отдельный коммит ради обновления этого файла без явного разрешения.
