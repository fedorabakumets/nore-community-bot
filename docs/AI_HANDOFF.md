# AI_HANDOFF — NORA

> Обновлено 06.11.2026. При расхождении доверять Git; секреты не записывать.

## Текущая задача: виджеты сообщений

- Worktree: C:/Users/User/Projects/nora-message-widgets, chatgpt/message-widgets.
- База origin/cursor/nora-2-update-d133: 5d76418; fetch + ls-remote совпали.
- Исходная копия chatgpt/codex-dev-setup с локальными AGENTS.md/handoff не переносилась.
- TelegramMessenger/widget-sandbox: profile 1, sendWidget описан для Bot API 10.4 beta.
- Исправлен транспорт виджетов и getUpdates: официальный /beta для обычных чатов.
- При отказе возраст/сумму выбирают кнопками Rich Message или вводят вручную.
- Ветка продолжена от 1773669; Railway подтвердил SUCCESS для предыдущего выпуска.
- Сделано: возраст анкеты/профиля, произвольная сумма оплаты, карточка перевода.
- Неизвестный/неподдерживаемый sendWidget возвращает прежнее сообщение; cooldown 10 минут.
- Внешних runtime-зависимостей sandbox нет: один HTML profile 1, CSS/JS внутри.
- PrivateRich меняет тип панели через отправку новой/сохранение указателя/удаление старой.
- Виджет суммы готовит прежний wallet intent, подтверждение списания остаётся отдельным.
- widget_query входит в штатный access/FSM pipeline; проверка nonce, владельца,
  актуального сообщения, шага и диапазона выполняется под блокировкой панели.
- Перевод только визуализирован; прежние inline-кнопки/авторизация/атомарность сохранены.
- Фоновые уведомления не закрывают активный выбор; текстовый ввод и навигация сохранены.
- Описание/ограничения: docs/INLINE_STYLE.md. Файлы: message_widgets.py,
  widgets/number.html, private_rich.py, main.py, routers/group.py, test_private_rich.py.
- check_local.py: Ruff + 856 passed, 1 skipped (Windows symlink), 68 warnings.
  Есть прежние aiohttp warnings и warning фонового aiosqlite thread/закрытого loop.
- После небольших финальных правок и добавления проверки оплаты: 13 widget tests
  passed; Ruff, pip check и git diff --check прошли. Полный suite повторно не запускался.
- Sandbox v0.6.0/d6f39f3: QuickJS + validator + renderer; возраст +/сохранить,
  сумма 100 -> 150/ответ «Готово»; ширины 200/320/430/600, высоты <=434 px.
  Размеры 2133–2199 байт zlib; overflow/лимитов/unsupported diagnostics нет.
- Исходники sandbox/его инструменты только во временной папке вне Git.
- Превью: C:/Users/User/Projects/nora-message-widgets-preview/{age,transfer}.png.
- Проверенные изменения подготовлены к commit/push в feature и production;
  итоговый SHA — git log, статус push — результат отправки. Live deploy не проверен.
- Настоящий бот/production БД не запускались.

## Правила выпуска

- Завершённые проверенные задачи публиковать по умолчанию; Railway следит
  за cursor/nora-2-update-d133. Feature-ветка не отслеживает production для push.
- После публикации дополнительных проверок не выполнять, владелец проверяет сам.
- Git SHA production-ветки не доказывает успешный Railway deploy.
- Пользовательские AGENTS.md и docs/AI_HANDOFF.md в исходной копии не коммитить.
- Тесты — временная SQLite, fake Bot, PYTHON_DOTENV_DISABLED=1.
- Python окружения исходной копии: C:/Users/User/Projects/nore-community-bot/.venv/Scripts/python.exe.
- Базовые изменения lazy S3 уже в production-ветке; реальная экономия RAM здесь не проверяется.
- Исправление beta и запасных кнопок: полный check_local — 859 passed, 1 skipped. После финальной правки активной панели — 65 passed, Ruff и pip check прошли. Живой показ владельцу предстоит проверить после выпуска.
