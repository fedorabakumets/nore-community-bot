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

- Ветка: `chatgpt/nav-icons` (локальные UI-изменения магазина, не опубликованы).
  Production-ветка Railway — `cursor/nora-2-update-d133`; upstream
  `origin/cursor/nora-2-update-d133`.
- Базовый коммит на 31.10.2026: `a671d92` — «feat: add smooth NORA app entrance
  animation»; затем `f88a240` (правила handoff), `84c7e63` (топ-5 фон).
- Перед `a671d92` — серия merge PR #48–#51 (community tiles, fullscreen nav/inset,
  live daily top five без бот-аккаунтов).
- Рабочее дерево на момент проверки: чистое (изменения handoff закоммичены).

## Последние изменения (по Git)

1. UI Mini App (31.10.2026, коммит `5e3902e`, опубликован в
   `cursor/nora-2-update-d133`):
   - Магазин: компактная кнопка репутации (уровень + скидка ранга) над категориями;
     открывает существующий sheet репутации (`data-reputation`). Цвета ранга — как в
     `metal-cookie` (золото/серебро/бронза). Файлы: `web/shop.js`, `web/style.css`.
   - Коммьюнити: строка «обновлено … назад · дата/время» вместо «обновление раз в
     минуту»; сервер отдаёт `updated_at` (Europe/Moscow) в `/api/community`
     (`community_api.py`), клиент пересчитывает относительное время локально в часовом
     поясе устройства. Файлы: `community_api.py`, `web/community.js`.
   - Навигация: убрана постоянная красная пульсация фото профиля; пульс и точка
     появляются только при `unread_notices>0`, для reduced-motion — статическая точка.
     Файлы: `web/app.js`, `web/style.css`.
2. Новые SVG-иконки нижнего бара Mini App (home/shop/community/events) в
   `community_bot/web/app.js` (`navTabShapes` + `navTabIcon`); вкладка «Профиль»
   оставлена с фото. Цвета серый/красный — уже в `style.css` (`nav button` →
   `#81818c`, `nav button.active` → `var(--red)`).
3. `f88a240` — правила handoff (`AGENTS.md` + этот файл).
4. `a671d92` — плавная анимация входа в Mini App (entrance animation).
5. PR #51 (`17a3198`) — живой ежедневный топ-5 в community, скрытие бот-аккаунтов.
6. PR #50 (`66fc9fe`) — fullscreen-контент не перекрывается Telegram-контролами.
7. PR #49 (`143553a`) — выравнивание плиток community и навигация профиля в fullscreen.
8. PR #48 — подписи/лейблы питомцев в community.

## Незавершённые задачи

- В работе (не закоммичено, ветка `chatgpt/nav-icons`): оптимизация нижней части
  магазина. Изменены `community_bot/web/shop.js` и `web/style.css`:
  - карточки категорий компактнее (padding/gap/radius, иконка по центру);
  - убрана подпись-заглушка «Открыть категорию» и техническая строка внизу
    магазина («Один магазин в миниапке и боте…»); описание категории чистится от
    хвостовой пунктуации и показывается только если задано, рядом число товаров;
  - карточка «Приватный профиль» (витрина) сохранила бейдж и скидочную цену,
    стала компактнее.
  Проверено: `node --check` ok, логика `catSub` прогнана в Node, мобильная
  вёрстка (390px) снята в Chromium — без горизонтального переполнения.
  Commit/push/deploy НЕ выполнялись по просьбе владельца.

## Исправление 31.10.2026 (топ-5 фон)

- Проблема: фон призовых мест («Топ 5 сегодня», места 1–3) не доходил до краёв
  карточки — `.community-place-*` применяется к `.community-person`, который
  зажат паддингом 14px у `.community-table-body` (style.css:135).
- Решение: в существующие правила `.community-place-1/2/3` (style.css:174)
  добавлены `margin:0 -14px; padding-left/right:14px` — фон тянется на всю
  ширину, текст остаётся на месте, радиус 12px сохранён. Цвета/логика не менялись.
- Проверено в Chromium (тестовая страница с реальными style.css/community.js):
  фон точно от границы до границы карточки на 320/360/393/430px, длинные имена
  переносятся без горизонтального overflow, сдвиг текста 0. `node --check` ok.
  tools/check_local.py не выполнялся — на машине нет Python/.venv (Store-заглушка).

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
