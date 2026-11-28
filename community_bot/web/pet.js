'use strict';
window.NoraPet = (() => {
  let seenPet;
  let seenStage;
  const status = {locked: NoraI18n.t("Заблокировано"), open: NoraI18n.t("Открыто"), available: NoraI18n.t("Доступно"), received: NoraI18n.t("Получено")};
  const species = new Set(['cat', 'dog', 'dragon', 'fox', 'raccoon']);

  function handbook(p) {
    const d = p.development;
    const r = d.rules;
    return [
      [NoraI18n.t("Питомец и его характеристики"), [
        ['hunger', NoraI18n.t("Что означает сытость?"), NoraI18n.t("Сытость убывает на 4 за каждый полный час вне похода. При значении ниже 50 у сытости или воды возможности питомца отключаются до восстановления обоих показателей. При нуле питомец засыпает. Чтобы уйти в поход, сытость и вода должны быть не ниже 50. Сытость сама по себе не даёт XP.")],
        ['thirst', NoraI18n.t("Что означает вода?"), NoraI18n.t("Вода убывает на 6 за каждый полный час вне похода. При нуле питомец засыпает. Еду и воду можно восстановить припасами, через магазин или наградой.")],
        ['mood', NoraI18n.t("Как меняется настроение?"), NoraI18n.t("Вне похода настроение меняется до 1 за полный час в сторону среднего сытости и воды. Сон понижает это целевое значение на 20. Поглаживание прибавляет до 50, награда восьмого этапа поднимает настроение до 100. Высокое настроение улучшает шансы и размер находки в походе и шанс защиты от −реп.")],
        ['guard', NoraI18n.t("Когда питомец защищает от −реп?"), NoraI18n.t("Бодрствующий питомец с сытостью от 70 может перехватить −реп после проверок иммунитета и щита. Шанс от 5% до 30% зависит от настроения. После успешной защиты она недоступна до следующего дня сообщества.")],
      ]],
      [NoraI18n.t("Уход и взаимодействия"), [
        ['care', NoraI18n.t("Чем кормить и поить?"), NoraI18n.t("Порция из запасов даёт +20 к выбранному показателю. При включённых наградах за активность каждые 120 сообщений пополняют запас еды и воды. В магазине обед даёт +") + r.meal_gain + NoraI18n.t(", поилка +") + r.drink_gain + NoraI18n.t(". Цена с учётом скидки показывается перед покупкой. У порций нет отдельного таймера. При 100 порция или награда не расходуется.")],
        ['stroke', NoraI18n.t("Как погладить питомца?"), NoraI18n.t("Нажми «Погладить» в этой вкладке, чтобы попасть в Нору. В игре подойди к питомцу и погладь его. Поглаживание восстанавливает до 50 настроения раз в час. Во время похода и при настроении 100 действие недоступно. Только успешное поглаживание засчитывается в задании.")],
        ['expedition', NoraI18n.t("Что происходит в походе?"), NoraI18n.t("Поход длится ") + r.expedition_hours + NoraI18n.t(" ч. и начинается при сытости и воде от 50. При отправке расходуется 60 сытости, 60 воды и 40 настроения (не ниже нуля). В пути новый поход, поглаживание и Нора ИИ недоступны. Нажми «Вернуть из похода», чтобы досрочно вернуть питомца и восстановить доступ. Находки при этом нет, потраченный уход не возвращается. Возможный результат — 1–10 печенек или пустые лапы. Настроение при отправке влияет на результат. Находка начисляется при возвращении.")],
        ['name', NoraI18n.t("Где ещё можно увидеть питомца?"), NoraI18n.t("В Telegram есть карточка /pet, а в 3D-лобби питомец ходит рядом и прячется на время похода. Кнопка «Имя» меняет имя в боте и Mini App. Имя может содержать от 1 до 24 символов.")],
      ]],
      [NoraI18n.t("Развитие и опыт"), [
        ['stage', NoraI18n.t("Чем этап отличается от уровня?"), NoraI18n.t("Этап — одна из ") + d.stages.length + NoraI18n.t(" ступеней «Пути развития». Основной уровень открывает функции. Сейчас у тебя этап ") + d.stage + NoraI18n.t(" и уровень ") + d.level + NoraI18n.t(". Ступени открываются по порядку. Нажми номер на шкале, чтобы увидеть условия и награду.")],
        ['xp', NoraI18n.t("Как начисляется и переносится XP?"), NoraI18n.t("Завершённое задание даёт ") + r.quest_xp + NoraI18n.t(" XP в пределах ") + r.daily_xp + NoraI18n.t(" XP в сутки. Для следующего этапа нужно ") + r.stage_xp + NoraI18n.t(" XP. Повыситься можно один раз за сутки, поэтому путь занимает минимум ") + (d.stages.length - 1) + NoraI18n.t(" активных дней. Уже начисленный XP до следующего этапа сохраняется. Опыт сверх дневного лимита не переносится.")],
        ['max', NoraI18n.t("Что происходит после последнего этапа?"), NoraI18n.t("Все функции и неиспользованные награды остаются. Ежедневные задания исчезают. Уход за питомцем остаётся доступен.")],
      ]],
      [NoraI18n.t("Ежедневные задания"), [
        ['quests', NoraI18n.t("Почему достаточно двух заданий?"), NoraI18n.t("Каждый день доступны три задания: погладить питомца и два задания из игр, лайков и редкого текстового задания. Два выполненных задания дают полный дневной XP, третье можно выполнить для отметки.")],
        ['messages', NoraI18n.t("Какие сообщения засчитываются?"), NoraI18n.t("Только обычные текстовые сообщения в основном чате. Кружки, голосовые, медиа, команды и реакции не засчитываются. Текстовое задание выдаётся по одному разу на этапах 1, 4 и 7.")],
        ['social', NoraI18n.t("Как считаются игры и лайки?"), NoraI18n.t("Засчитываются три завершённые партии в Дурака или Баррикаду, победа не обязательна. Сдача, тайм-аут и отмена не считаются. Задание на лайки требует пяти успешных лайков другим участникам.")],
        ['reset', NoraI18n.t("Когда обновляется набор?"), NoraI18n.t("В ") + r.reset_hour + ' ' + r.timezone + NoraI18n.t(" начинается новый набор. Незавершённые вчерашние задания закрываются. Отметки за ") + d.milestones.join(NoraI18n.t(" и ")) + NoraI18n.t(" сообщений копятся несколько дней и не добавляют XP.")],
      ]],
      [NoraI18n.t("Уровни и награды"), [
        ['levels', NoraI18n.t("Какие функции открывает каждый уровень?"), NoraI18n.t("Компаньон доступен сразу: уход, походы и питомец в игре. На этапе ") + r.ai_stage + NoraI18n.t(" открывается Собеседник с Норой ИИ и переводом голосовых и кружков. На этапе ") + r.video_stage + NoraI18n.t(" — Помощник со скачиванием видео. Прежние функции остаются доступны.")],
        ['rewards', NoraI18n.t("Где получить награду?"), NoraI18n.t("Печеньки сразу поступают на общий баланс. Репутация начисляется автоматически с учётом потолка профиля. Результат операции виден в деталях этапа. Обед, поилка и восстановление настроения хранятся до применения. Их можно использовать прямо с карточки наград или из подробностей этапа.")],
      ]],
      [NoraI18n.t("ИИ Нора"), [
        ['ai', NoraI18n.t("Как поговорить с Норой?"), NoraI18n.t("Со 2-го уровня питомца напиши «Нора, …» в основном чате или в личке. В основном чате можно спросить о переписке за последние 48 часов. Ответь на сообщение Норы, чтобы продолжить разговор. Запросов в день по репутации: ") + r.ai_limits + NoraI18n.t(". Лимит обновляется в полночь по времени сообщества.")],
        ['speech', NoraI18n.t("Как перевести голосовое или кружок?"), NoraI18n.t("Ответь прямо на запись: «Нора, что здесь сказали?» или задай свой вопрос. Нора ответит под записью. Раскрой карточку, чтобы прочитать текст на русском. Карточку можно закрыть по ❌, через две минуты она исчезнет сама. Подходят записи до 3 минут и 12 МБ. Запрос входит в дневной лимит ИИ.")],
      ]],
      [NoraI18n.t("Загрузка видео"), [
        ['video', NoraI18n.t("Как получить ролик?"), NoraI18n.t("С 3-го уровня питомца отправь «Нора https://vm.tiktok.com/…», «Нора https://instagram.com/reel/…» или «Нора https://youtube.com/shorts/…». Бот пришлёт видео ответом в личке или в основном чате. Пока питомец в походе, скачивание недоступно. Доступно ") + r.video_daily_limit + NoraI18n.t(" успешных отправок за сутки по Москве, включая повторную отправку из кеша.")],
        ['video_limits', NoraI18n.t("Почему ролик может быть недоступен?"), NoraI18n.t("Подходят публичные ролики в доступном MP4 до ") + r.video_max_mb + NoraI18n.t(" МБ. Приватные и удалённые публикации, ограничения источника и отсутствие подходящего файла могут помешать. Если источник отдаёт ролик с водяным знаком, он сохраняется. Ошибки не расходуют дневной лимит.")],
      ]],
    ];
  }

  const question = (key, label) => '<button type="button" class="pet-question" data-pet-help="' + key
    + '" aria-label="' + esc(label) + '">?</button>';

  function section(title, key) {
    return '<h2>' + title + question(key, NoraI18n.t("Подробнее: ") + title) + '</h2>';
  }

  function meter(label, value, key) {
    return '<div class="pet2-meter"><div><span>' + label + '</span>' + question(key, label)
      + '<b>' + number(value) + '</b></div><progress max="100" value="' + value + '" aria-label="' + label
      + '"></progress></div>';
  }

  function action(code, label, detail, disabled) {
    return '<button class="secondary pet2-action" data-pet-action="' + code + '"' + (disabled ? ' disabled' : '')
      + '><b>' + label + '</b><small>' + detail + '</small></button>';
  }

  function rewardButton(s, p) {
    const values = {meal: p.hunger, drink: p.thirst, mood: p.mood};
    return '<button class="secondary" data-pet-action="reward:' + esc(s.kind) + '"'
      + (!p.enabled || values[s.kind] >= 100 ? ' disabled' : '') + '>'
      + (values[s.kind] >= 100 ? NoraI18n.t("Показатель уже на 100") : NoraI18n.t("Применить")) + '</button>';
  }

  function path(d) {
    return d.stages.map(s => {
      const major = s.stage === 1 || s.stage === d.rules.ai_stage || s.stage === d.rules.video_stage;
      const current = s.stage === d.stage;
      return '<li><button type="button" class="pet2-step' + (major ? ' major' : '') + '" data-pet-stage="' + s.stage
        + '" data-state="' + s.status + '"' + (current ? ' aria-current="step"' : '')
        + ' aria-label="' + esc(NoraI18n.t("Этап ") + s.stage + ' · ' + NoraI18n.t(s.label) + ' · ' + status[s.status]) + '">'
        + s.stage + '</button></li>';
    }).join('');
  }

  function petGameButton(label, disabled = false) {
    return '<button type="button" class="nora-pixel-button pet2-play" data-play-with-pet'
      + (disabled ? ' disabled' : '') + '><span>'
      + esc(label) + '</span><span aria-hidden="true">↗</span></button>';
  }

  function levelCards(d) {
    const levels = [
      [1, NoraI18n.t("Уход, походы и питомец в игре")],
      [d.rules.ai_stage, NoraI18n.t("Нора ИИ, перевод голосовых и кружков")],
      [d.rules.video_stage, NoraI18n.t("Скачивание видео по ссылке")],
    ];
    return ("<ul class=\"pet2-levels\" aria-label=\"" + NoraI18n.html("Уровни питомца") + "\">") + levels.map(([stage, benefit], index) => {
      const level = index + 1;
      const state = level === d.level ? NoraI18n.t("Твой уровень") : level < d.level ? NoraI18n.t("Открыт") : NoraI18n.t("С этапа ") + stage;
      return '<li><button type="button" class="pet2-level" data-pet-stage="' + stage + '"'
        + (level === d.level ? ' aria-current="true"' : '') + '>'
        + '<img src="/pet-art/level-' + level + '.webp" alt="" width="320" height="320" loading="lazy" decoding="async">'
        + ("<span class=\"pet2-level-copy\"><small>" + NoraI18n.html("Уровень") + " ") + level + ' · ' + state + '</small><strong>'
        + esc(NoraI18n.t(d.stages[stage - 1].level_name)) + '</strong><span>' + benefit + '</span></span>'
        + '<span class="pet2-level-arrow" aria-hidden="true">›</span></button></li>';
    }).join('') + '</ul>';
  }

  function quests(d) {
    return d.quests.map(q => {
      const complete = q.progress >= q.target;
      const xp = complete ? (q.xp ? '+' + q.xp + ' XP' : '✓')
        : d.stage === d.stages.length || d.daily_xp >= d.rules.daily_xp ? NoraI18n.t("Без XP") : '+' + d.rules.quest_xp + ' XP';
      const label = q.play_with_pet ? petGameButton(NoraI18n.t(q.label), !data.pet.enabled || data.pet.needs_care) : '<span>' + esc(NoraI18n.t(q.label)) + '</span>';
      return '<li><div>' + label + '<progress max="' + q.target + '" value="' + q.progress
        + '" aria-label="' + esc(NoraI18n.t(q.label)) + '"></progress></div><span class="pet2-quest-score"><b>'
        + q.progress + '/' + q.target + '</b><small>' + xp + '</small></span></li>';
    }).join('');
  }

  function trackStage(p) {
    const identity = p.created_at;
    const stage = p.development.stage;
    const key = 'nora-pet-stage:' + identity;
    let previous = seenPet === identity ? seenStage : undefined;
    try {
      previous = Math.max(previous || 0, Number(sessionStorage.getItem(key))) || undefined;
      sessionStorage.setItem(key, String(stage));
    } catch { /* Storage can be unavailable inside a WebView. */ }
    if (previous && previous < stage) {
      const reward = p.development.stages[stage - 1];
      queueMicrotask(() => toast(NoraI18n.t("Этап ") + stage + ' · ' + NoraI18n.t(reward.label)));
    }
    seenPet = identity;
    seenStage = stage;
  }

  function screen() {
    const p = data.pet;
    if (!p) return ("<h1>" + NoraI18n.html("Питомец") + "</h1><section class=\"card pet-empty\"><div class=\"pet-empty-icon\">")
      + NoraShop.svg('pets') + ("</div><h2>" + NoraI18n.html("Здесь будет жить твой питомец") + "</h2>")
      + ("<button class=\"primary\" data-open-pet-shop>" + NoraI18n.html("Выбрать питомца") + "</button></section>");
    const d = p.development;
    if (!d) return ("<h1>" + NoraI18n.html("Питомец") + "</h1><p class=\"sub\">" + NoraI18n.html("Обновляем данные питомца…") + "</p>");
    trackStage(p);
    queueMicrotask(clock);
    const away = !!p.expedition_until;
    const careLocked = !!p.needs_care;
    const next = d.stages[d.stage];
    const age = Math.max(0, Math.floor((Date.now() - Date.parse(p.created_at)) / 86400000));
    const products = Object.fromEntries((data.products || []).map(item => [item.sku, item]));
    const art = species.has(p.species)
      ? '<img width="82" height="82" src="/pet-art/' + p.species + '.webp" alt="">'
      : '<span>' + esc(p.emoji) + '</span>';
    const trip = away ? NoraI18n.t("До ") + esc(new Date(p.expedition_until).toLocaleString(NoraI18n.locale, {
      timeZone: 'Europe/Moscow', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit',
    })) + NoraI18n.t(" МСК") : d.rules.expedition_hours + NoraI18n.t(" ч · сытость и вода от 50");
    const saved = d.stages.filter(s => s.status === 'available');
    const milestones = d.milestones.map(n => Math.min(n, d.messages) + '/' + n).join(' · ');
    function supplyPrice(sku) {
      const item = products[sku];
      return item?.buyable && item.price ? number(item.price) + ' 🍪' : NoraI18n.t("Магазин");
    }
    return '<div class="pet2"><section class="card pet2-profile">'
      + '<div class="pet2-identity"><div class="pet2-art">' + art + '</div><div class="pet2-name">'
      + '<p>' + esc(NoraI18n.t(p.species_label)) + ' · ' + age + (" " + NoraI18n.html("дн. вместе") + "</p><h2>")
      + NoraPrefix(p.prefix) + esc(p.name) + '</h2><p>' + (away ? NoraI18n.t("В походе") : p.sleeping ? NoraI18n.t("Спит") : careLocked ? NoraI18n.t("Нужен уход") : NoraI18n.t("Бодрствует"))
      + '</p></div><button class="text-btn" id="rename-pet"' + (p.enabled && !careLocked ? '' : ' disabled')
      + (">" + NoraI18n.html("Имя") + "</button></div><div class=\"pet2-rank\"><strong>") + esc(NoraI18n.t(d.level_name)) + NoraI18n.t(" · ур. ") + d.level
      + '</strong>' + question('levels', NoraI18n.t("Основные уровни")) + ("<span>" + NoraI18n.html("Этап") + " ") + d.stage + ' / ' + d.stages.length
      + '</span></div><div class="pet2-meters">' + meter(NoraI18n.t("Сытость"), p.hunger, 'hunger') + meter(NoraI18n.t("Вода"), p.thirst, 'thirst')
      + meter(NoraI18n.t("Настроение"), p.mood, 'mood') + '</div></section>'
      + (!p.enabled ? ("<p class=\"sub\">" + NoraI18n.html("Функции питомца временно выключены администрацией.") + "</p>") : '')
      + (careLocked ? ("<p class=\"sub pet2-note\" role=\"status\">" + NoraI18n.html("🔒 Питомцу нужен уход: сытость и вода должны быть от") + " ")
        + number(p.min_needs || 50) + (NoraI18n.html(". Доступ к походам, поглаживанию, Норе ИИ и загрузкам восстановится после кормления.") + "</p>") : '')
      + '<section class="card pet2-panel"><div class="pet2-heading">' + section(NoraI18n.t("Уход"), 'care')
      + ("<button class=\"text-btn\" data-open-pet-shop>" + NoraI18n.html("Магазин") + "</button></div><div class=\"pet2-actions\">")
      + action('food', NoraI18n.t("Покормить"), NoraI18n.t("+20 · порций ") + number(p.food_units), !p.enabled || !p.food_units || p.hunger >= 100)
      + action('water', NoraI18n.t("Напоить"), NoraI18n.t("+20 · порций ") + number(p.water_units), !p.enabled || !p.water_units || p.thirst >= 100)
      + petGameButton(NoraI18n.t("Погладить"), !p.enabled || careLocked || away)
      + (away ? action('return', NoraI18n.t("Вернуть из похода"), NoraI18n.t("Без награды · ") + trip, false)
        : action('expedition', NoraI18n.t("В поход"), trip, !p.enabled || careLocked))
      + ("</div><div class=\"pet2-shop\"><button class=\"text-btn\" data-product=\"pet_meal\">" + NoraI18n.html("Обед ·") + " ") + supplyPrice('pet_meal')
      + ("</button><button class=\"text-btn\" data-product=\"pet_drink\">" + NoraI18n.html("Поилка ·") + " ") + supplyPrice('pet_drink') + '</button></div>'
      + (p.last_find ? ("<p class=\"sub pet2-note\">" + NoraI18n.html("Последняя находка ·") + " ") + esc(NoraI18n.server(p.last_find)) + '</p>' : '') + '</section>'
      + '<section class="card pet2-panel"><div class="pet2-heading">' + section(NoraI18n.t("Путь развития"), 'stage')
      + '<span>' + (next ? d.xp + '/' + d.rules.stage_xp + ' XP' : NoraI18n.t("Максимум")) + question('xp', NoraI18n.t("Опыт")) + '</span></div>'
      + ("<ol class=\"pet2-route\" aria-label=\"" + NoraI18n.html("Этапы развития") + "\">") + path(d) + '</ol><p class="sub pet2-note">'
      + (next ? NoraI18n.t("Следующая награда · ") + esc(NoraI18n.t(next.label)) : NoraI18n.t("Все уровни открыты")) + '</p>'
      + levelCards(d)
      + (saved.length ? '<div class="pet2-rewards">' + saved.map(s => '<div><span>' + esc(NoraI18n.t(s.label))
        + '</span>' + rewardButton(s, p) + '</div>').join('') + '</div>' : '') + '</section>'
      + (next ? '<section class="card pet2-panel"><div class="pet2-heading">' + section(NoraI18n.t("Задания на сегодня"), 'quests') + '</div>'
      + '<ul class="pet2-quests">' + quests(d) + '</ul><div class="pet2-daily"><strong>' + d.daily_xp + '/'
      + d.rules.daily_xp + ' XP</strong><span data-pet-reset="' + esc(d.reset_at) + '"></span></div>'
      + ("<details class=\"pet2-milestones\"><summary>" + NoraI18n.html("Многодневная активность") + "</summary><p>" + NoraI18n.html("Сообщения ·") + " ")
      + milestones + '</p></details></section>' : '') + '<button class="secondary pet2-guide" data-pet-help="all">'
      + (NoraI18n.html("Справка о питомце") + " <span aria-hidden=\"true\">?</span></button></div>");
  }

  function sheetHead(title) {
    return '<div class="pet2-heading"><h2 tabindex="-1" autofocus style="outline:none">' + esc(title) + '</h2></div>';
  }

  function showHelp(p, key) {
    const groups = handbook(p);
    if (key === 'all') {
      sheet('<div class="pet2-handbook">' + sheetHead(NoraI18n.t("Справка о питомце")) + groups.map(([title, topics]) =>
        '<h3>' + esc(title) + '</h3>' + topics.map(([, question, answer]) =>
          '<details><summary>' + esc(question) + '</summary><p>' + esc(answer) + '</p></details>').join('')
      ).join('') + '</div>');
      return;
    }
    const item = groups.flatMap(([, topics]) => topics).find(([id]) => id === key);
    if (item) sheet('<div class="pet2-handbook">' + sheetHead(item[1]) + '<p>' + esc(item[2])
      + ("</p><button class=\"secondary\" data-pet-help=\"all\">" + NoraI18n.html("Открыть справочник") + "</button></div>"));
  }

  function showStage(p, stage) {
    const d = p.development;
    const s = d.stages[stage - 1];
    if (!s) return;
    const detail = s.status === 'locked'
      ? NoraI18n.t("Откроется автоматически после предыдущего этапа. На каждый переход нужно ") + d.rules.stage_xp + ' XP.'
      : s.kind === 'reputation' ? NoraI18n.t("Начислено: ") + s.amount + NoraI18n.t(" репутации с учётом потолка профиля.")
      : s.kind === 'cookies' ? NoraI18n.t("В кошелёк начислено ") + s.amount + ' 🍪.'
      : s.status === 'available' ? NoraI18n.t("Награда сохранится, пока ты её не применишь.")
      : s.kind === 'unlock' ? NoraI18n.t("Возможность открыта.") : NoraI18n.t("Награда использована.");
    const topic = stage === d.rules.video_stage ? 'video' : stage === d.rules.ai_stage ? 'ai' : 'rewards';
    sheet('<div class="pet2-handbook">' + sheetHead(NoraI18n.t("Этап ") + stage) + '<p class="sub">'
      + esc(NoraI18n.t(s.level_name)) + NoraI18n.t(" · ур. ") + s.level + ' · ' + status[s.status] + '</p><h3>'
      + esc(NoraI18n.t(s.label)) + '</h3><p>' + esc(detail) + '</p>'
      + (s.status === 'available' ? rewardButton(s, p) : '') + '<button class="text-btn" data-pet-help="'
      + topic + (NoraI18n.html("\">Как это работает") + "</button>") + (stage === d.rules.ai_stage
        ? ("<button class=\"text-btn\" data-pet-help=\"speech\">" + NoraI18n.html("Перевод голосовых и кружков") + "</button>") : '') + '</div>');
  }

  function clock() {
    const el = document.querySelector('[data-pet-reset]');
    if (!el) return;
    const minutes = Math.max(0, Math.ceil((Date.parse(el.dataset.petReset) - Date.now()) / 60000));
    el.textContent = minutes ? NoraI18n.t("Новые через ") + Math.floor(minutes / 60) + ':' + String(minutes % 60).padStart(2, '0')
      : NoraI18n.t("Обновляем задания…");
  }

  document.addEventListener('click', event => {
    const button = event.target.closest('[data-pet-help],[data-pet-stage]');
    if (!button || !data?.pet?.development) return;
    if (button.dataset.petHelp) showHelp(data.pet, button.dataset.petHelp);
    if (button.dataset.petStage) showStage(data.pet, Number(button.dataset.petStage));
  });
  setInterval(clock, 10000);
  return {screen};
})();
