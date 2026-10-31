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

- Ветка работы `chatgpt/nav-icons` и production-ветка `cursor/nora-2-update-d133` —
  обе на коммите `84230d6` «feat: compact shop categories and clean footer notes».
- Базовый коммит на 31.10.2026: `a671d92` — «feat: add smooth NORA app entrance
  animation»; затем `f88a240` (правила handoff), `84c7e63` (топ-5 фон).
- Перед `a671d92` — серия merge PR #48–#51 (community tiles, fullscreen nav/inset,
  live daily top five без бот-аккаунтов).
- Рабочее дерево: чистое, кроме несохранённой правки этого файла (handoff).

## Последние изменения (по Git)

1. Оптимизация нижней части магазина (31.10.2026, коммит `84230d6`, опубликован в
   `cursor/nora-2-update-d133`): карточки категорий компактнее, единая структура
   (иконка/название/описание/стрелка), убрана заглушка «Открыть категорию» и
   техническая подпись внизу, карточка витрины «Приватный профиль» сохранила бейдж
   и скидочную цену. Файлы: `web/shop.js` (хелпер `catSub`), `web/style.css`.
2. UI Mini App (31.10.2026, коммит `5e3902e`, опубликован):
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
3. Новые SVG-иконки нижнего бара Mini App (home/shop/community/events) в
   `community_bot/web/app.js` (`navTabShapes` + `navTabIcon`); вкладка «Профиль»
   оставлена с фото. Цвета серый/красный — уже в `style.css` (`nav button` →
   `#81818c`, `nav button.active` → `var(--red)`).
4. `f88a240` — правила handoff (`AGENTS.md` + этот файл).
5. `a671d92` — плавная анимация входа в Mini App (entrance animation).
6. PR #51 (`17a3198`) — живой ежедневный топ-5 в community, скрытие бот-аккаунтов.
7. PR #50 (`66fc9fe`) — fullscreen-контент не перекрывается Telegram-контролами.
8. PR #49 (`143553a`) — выравнивание плиток community и навигация профиля в fullscreen.
9. PR #48 — подписи/лейблы питомцев в community.
10. Плавающая круглая кнопка-стрелка `#scroll-jump` поверх всех окон (z-index:50,
   над nav/toast, под интро): опускает в самый низ, меняет иконку на стрелку вверх
   и поднимает вверх; скрыта, когда страница не скроллится. Появляется на всех
   экранах Mini App. Файлы: `web/index.html` (кнопка+2 SVG), `web/style.css`
   (блок `#scroll-jump`), `web/app.js` (IIFE-обработчик в конце файла).
   Проверено `node --check`, баланс скобок и поведение в браузере (down→up→down,
   scrollY 0→1666→0). Commit/push НЕ выполнялись.

## Незавершённые задачи

- Открытых задач нет. Выпуск `84230d6` задеплоен и подтверждён: `/healthz` 200,
  маркеры `function catSub` в `/shop.js` и `padding:13px 14px` в `/style.css`
  отдаются с боевого домена. В рабочем дереве осталась только несохранённая
  правка этого файла (handoff) — не коммитить отдельным коммитом без запроса.

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
