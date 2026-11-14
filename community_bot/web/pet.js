'use strict';
window.NoraPet = (() => {
  let seenPet;
  let seenStage;
  const status = {locked: 'Заблокировано', open: 'Открыто', available: 'Доступно', received: 'Получено'};
  const species = new Set(['cat', 'dog', 'dragon', 'fox', 'raccoon']);

  function handbook(p) {
    const d = p.development;
    const r = d.rules;
    return [
      ['Питомец и его характеристики', [
        ['hunger', 'Что означает сытость?', 'Сытость убывает на 2 за каждый полный час вне похода. При нуле питомец засыпает. Чтобы уйти в поход, сытость и вода должны быть не ниже 50. Сытость сама по себе не даёт XP.'],
        ['thirst', 'Что означает вода?', 'Вода убывает на 3 за каждый полный час вне похода. При нуле питомец засыпает. Еду и воду можно восстановить припасами, через магазин или наградой.'],
        ['mood', 'Как меняется настроение?', 'Вне похода настроение меняется до 1 за полный час в сторону среднего сытости и воды. Сон понижает это целевое значение на 20. Поглаживание прибавляет до 50, награда восьмого этапа поднимает настроение до 100. Высокое настроение улучшает шансы и размер находки в походе и шанс защиты от −реп.'],
        ['guard', 'Когда питомец защищает от −реп?', 'Бодрствующий питомец с сытостью от 70 может перехватить −реп после проверок иммунитета и щита. Шанс от 5% до 30% зависит от настроения. После успешной защиты она недоступна до следующего дня сообщества.'],
      ]],
      ['Уход и взаимодействия', [
        ['care', 'Чем кормить и поить?', 'Порция из запасов даёт +20 к выбранному показателю. При включённых наградах за активность каждые 120 сообщений пополняют запас еды и воды. В магазине обед даёт +' + r.meal_gain + ', поилка +' + r.drink_gain + '. Цена с учётом скидки показывается перед покупкой. У порций нет отдельного таймера. При 100 порция или награда не расходуется.'],
        ['stroke', 'Как погладить питомца?', 'В этой вкладке или рядом с питомцем в 3D-лобби. Поглаживание восстанавливает до 50 настроения раз в час. Во время похода и при настроении 100 действие недоступно. Только успешное поглаживание засчитывается в задании.'],
        ['expedition', 'Что происходит в походе?', 'Поход длится ' + r.expedition_hours + ' ч. и начинается при сытости и воде от 50. Пока питомец в пути, показатели не убывают, новый поход и поглаживание недоступны. Возможный результат — 1–10 печенек или пустые лапы. Настроение при отправке влияет на результат. Находка начисляется при возвращении, а задание засчитывается при успешной отправке.'],
        ['name', 'Где ещё можно увидеть питомца?', 'В Telegram есть карточка /pet, а в 3D-лобби питомец ходит рядом и прячется на время похода. Кнопка «Имя» меняет имя в боте и Mini App. Имя может содержать от 1 до 24 символов.'],
      ]],
      ['Развитие и опыт', [
        ['stage', 'Чем этап отличается от уровня?', 'Этап — одна из ' + d.stages.length + ' ступеней «Пути развития». Основной уровень открывает функции. Сейчас у тебя этап ' + d.stage + ' и уровень ' + d.level + '. Ступени открываются по порядку. Нажми номер на шкале, чтобы увидеть условия и награду.'],
        ['xp', 'Как начисляется и переносится XP?', 'Завершённое задание даёт ' + r.quest_xp + ' XP в пределах ' + r.daily_xp + ' XP в сутки. Для следующего этапа нужно ' + r.stage_xp + ' XP. Повыситься можно один раз за сутки, поэтому путь занимает минимум ' + (d.stages.length - 1) + ' активных дней. Уже начисленный XP до следующего этапа сохраняется. Опыт сверх дневного лимита не переносится.'],
        ['max', 'Что происходит после последнего этапа?', 'Все функции и неиспользованные награды остаются. Можно заботиться о питомце и отмечать задания, шкала достигнет максимума и XP больше не начисляется.'],
      ]],
      ['Ежедневные задания', [
        ['quests', 'Почему достаточно двух заданий?', 'Каждый день доступны три задания: общение, уход и дополнительный вариант. Сервер чередует форматы, учитывает запрет медиа и может дать альтернативу, если уход сейчас недоступен. Два выполненных задания дают полный дневной XP, третье можно выполнить для отметки.'],
        ['messages', 'Какие сообщения и медиа засчитываются?', 'В основном чате считаются обычные сообщения от ' + r.text_min_length + ' символов с интервалом от ' + r.text_interval + ' с. Повторы подряд, команды, пересылки, сообщения ботов и удалённые фильтрами Норы сообщения не учитываются. Фото, видео, голосовые, кружки, аудио, GIF и документы засчитываются по типу, указанному в задании. Один Telegram-пост учитывается один раз.'],
        ['social', 'Что считается поддержкой участника?', 'Успешный +реп или разрешённый −реп, который действительно изменил репутацию, либо завершённый перевод печенек другому участнику. Действуют ограничения твоего ранга, иммунитет и щиты получателя. Снижение репутации необязательно.'],
        ['reset', 'Когда обновляется набор?', 'В ' + r.reset_hour + ' ' + r.timezone + ' начинается новый набор. Незавершённые вчерашние задания закрываются. Отметки за ' + d.milestones.join(' и ') + ' текстовых сообщений копятся несколько дней и не добавляют XP.'],
      ]],
      ['Уровни и награды', [
        ['levels', 'Какие функции открывает каждый уровень?', 'Компаньон доступен сразу: уход, походы и питомец в игре. На этапе ' + r.ai_stage + ' открывается Собеседник с ИИ Норой, на этапе ' + r.video_stage + ' — Помощник с видео. Прежние функции остаются доступны.'],
        ['rewards', 'Где получить награду?', 'Печеньки сразу поступают на общий баланс. Репутация начисляется автоматически с учётом потолка профиля. Результат операции виден в деталях этапа. Обед, поилка и восстановление настроения хранятся до применения. Их можно использовать прямо с карточки наград или из подробностей этапа.'],
      ]],
      ['ИИ Нора', [
        ['ai', 'Как поговорить с Норой?', 'После этапа ' + r.ai_stage + ' напиши «Нора, …» в личном чате с ботом или в основном чате. Можно ответить на её сообщение и продолжить свой диалог. Используется действующая модель и история диалога. Архив сообщества остаётся доступен владельцам и модераторам, их доступ к ИИ сохраняется. Общий лимит — до ' + r.ai_daily_limit + ' запросов за 24 ч. с интервалом от ' + r.ai_interval + ' с.'],
      ]],
      ['Загрузка видео', [
        ['video', 'Как получить ролик?', 'После этапа ' + r.video_stage + ' отправь «Нора https://vm.tiktok.com/…», «Нора https://instagram.com/reel/…» или «Нора https://youtube.com/shorts/…». Бот пришлёт видео ответом в личке или в основном чате. Доступно ' + r.video_daily_limit + ' успешных отправок за сутки по Москве, включая повторную отправку из кеша.'],
        ['video_limits', 'Почему ролик может быть недоступен?', 'Подходят публичные ролики в доступном MP4 до ' + r.video_max_mb + ' МБ. Приватные и удалённые публикации, ограничения источника и отсутствие подходящего файла могут помешать. Если источник отдаёт ролик с водяным знаком, он сохраняется. Ошибки не расходуют дневной лимит.'],
      ]],
    ];
  }

  const question = (key, label) => '<button type="button" class="pet-question" data-pet-help="' + key
    + '" aria-label="' + esc(label) + '">?</button>';

  function section(title, key) {
    return '<h2>' + title + question(key, 'Подробнее: ' + title) + '</h2>';
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
      + (values[s.kind] >= 100 ? 'Показатель уже на 100' : 'Применить') + '</button>';
  }

  function path(d) {
    return d.stages.map(s => {
      const major = s.stage === 1 || s.stage === d.rules.ai_stage || s.stage === d.rules.video_stage;
      const current = s.stage === d.stage;
      return '<li><button type="button" class="pet2-step' + (major ? ' major' : '') + '" data-pet-stage="' + s.stage
        + '" data-state="' + s.status + '"' + (current ? ' aria-current="step"' : '')
        + ' aria-label="' + esc('Этап ' + s.stage + ' · ' + s.label + ' · ' + status[s.status]) + '">'
        + s.stage + '</button></li>';
    }).join('');
  }

  function quests(d) {
    return d.quests.map(q => {
      const complete = q.progress >= q.target;
      const xp = complete ? (q.xp ? '+' + q.xp + ' XP' : '✓')
        : d.stage === d.stages.length || d.daily_xp >= d.rules.daily_xp ? 'Без XP' : '+' + d.rules.quest_xp + ' XP';
      return '<li><div><span>' + esc(q.label) + '</span><progress max="' + q.target + '" value="' + q.progress
        + '" aria-label="' + esc(q.label) + '"></progress></div><span class="pet2-quest-score"><b>'
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
      queueMicrotask(() => toast('Этап ' + stage + ' · ' + reward.label));
    }
    seenPet = identity;
    seenStage = stage;
  }

  function screen() {
    const p = data.pet;
    if (!p) return '<h1>Питомец</h1><section class="card pet-empty"><div class="pet-empty-icon">'
      + NoraShop.svg('pets') + '</div><h2>Здесь будет жить твой питомец</h2>'
      + '<button class="primary" data-open-pet-shop>Выбрать питомца</button></section>';
    const d = p.development;
    if (!d) return '<h1>Питомец</h1><p class="sub">Обновляем данные питомца…</p>';
    trackStage(p);
    queueMicrotask(clock);
    const away = !!p.expedition_until;
    const ready = p.stroke_at && Date.parse(p.stroke_at) > Date.now();
    const next = d.stages[d.stage];
    const age = Math.max(0, Math.floor((Date.now() - Date.parse(p.created_at)) / 86400000));
    const products = Object.fromEntries((data.products || []).map(item => [item.sku, item]));
    const art = species.has(p.species)
      ? '<img width="82" height="82" src="/pet-art/' + p.species + '.webp" alt="">'
      : '<span>' + esc(p.emoji) + '</span>';
    const trip = away ? 'До ' + esc(new Date(p.expedition_until).toLocaleString('ru-RU', {
      timeZone: 'Europe/Moscow', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit',
    })) + ' МСК' : d.rules.expedition_hours + ' ч · сытость и вода от 50';
    const saved = d.stages.filter(s => s.status === 'available');
    const milestones = d.milestones.map(n => Math.min(n, d.messages) + '/' + n).join(' · ');
    function supplyPrice(sku) {
      const item = products[sku];
      return item?.buyable && item.price ? number(item.price) + ' 🍪' : 'Магазин';
    }
    return '<div class="pet2"><section class="card pet2-profile">'
      + '<div class="pet2-identity"><div class="pet2-art">' + art + '</div><div class="pet2-name">'
      + '<p>' + esc(p.species_label) + ' · ' + age + ' дн. вместе</p><h2>'
      + NoraPrefix(p.prefix) + esc(p.name) + '</h2><p>' + (away ? 'В походе' : p.sleeping ? 'Спит' : 'Бодрствует')
      + '</p></div><button class="text-btn" id="rename-pet"' + (p.enabled ? '' : ' disabled')
      + '>Имя</button></div><div class="pet2-rank"><strong>' + esc(d.level_name) + ' · ур. ' + d.level
      + '</strong>' + question('levels', 'Основные уровни') + '<span>Этап ' + d.stage + ' / ' + d.stages.length
      + '</span></div><div class="pet2-meters">' + meter('Сытость', p.hunger, 'hunger') + meter('Вода', p.thirst, 'thirst')
      + meter('Настроение', p.mood, 'mood') + '</div></section>'
      + (!p.enabled ? '<p class="sub">Функции питомца временно выключены администрацией.</p>' : '')
      + '<section class="card pet2-panel"><div class="pet2-heading">' + section('Уход', 'care')
      + '<button class="text-btn" data-open-pet-shop>Магазин</button></div><div class="pet2-actions">'
      + action('food', 'Покормить', '+20 · порций ' + number(p.food_units), !p.enabled || !p.food_units || p.hunger >= 100)
      + action('water', 'Напоить', '+20 · порций ' + number(p.water_units), !p.enabled || !p.water_units || p.thirst >= 100)
      + action('stroke', 'Погладить', ready ? 'Через ' + Math.ceil((Date.parse(p.stroke_at) - Date.now()) / 60000) + ' мин' : '+50 настроения',
        !p.enabled || away || ready || p.mood >= 100)
      + action('expedition', away ? 'В походе' : 'В поход', trip, !p.enabled || away || p.hunger < 50 || p.thirst < 50)
      + '</div><div class="pet2-shop"><button class="text-btn" data-product="pet_meal">Обед · ' + supplyPrice('pet_meal')
      + '</button><button class="text-btn" data-product="pet_drink">Поилка · ' + supplyPrice('pet_drink') + '</button></div>'
      + (p.last_find ? '<p class="sub pet2-note">Последняя находка · ' + esc(p.last_find) + '</p>' : '') + '</section>'
      + '<section class="card pet2-panel"><div class="pet2-heading">' + section('Путь развития', 'stage')
      + '<span>' + (next ? d.xp + '/' + d.rules.stage_xp + ' XP' : 'Максимум') + question('xp', 'Опыт') + '</span></div>'
      + '<ol class="pet2-route" aria-label="Этапы развития">' + path(d) + '</ol><p class="sub pet2-note">'
      + (next ? 'Следующая награда · ' + esc(next.label) : 'Все уровни открыты') + '</p>'
      + (saved.length ? '<div class="pet2-rewards">' + saved.map(s => '<div><span>' + esc(s.label)
        + '</span>' + rewardButton(s, p) + '</div>').join('') + '</div>' : '') + '</section>'
      + '<section class="card pet2-panel"><div class="pet2-heading">' + section('Задания на сегодня', 'quests') + '</div>'
      + '<ul class="pet2-quests">' + quests(d) + '</ul><div class="pet2-daily"><strong>' + d.daily_xp + '/'
      + d.rules.daily_xp + ' XP</strong><span data-pet-reset="' + esc(d.reset_at) + '"></span></div>'
      + '<details class="pet2-milestones"><summary>Многодневная активность</summary><p>Сообщения · '
      + milestones + '</p></details></section><button class="secondary pet2-guide" data-pet-help="all">'
      + 'Справка о питомце <span aria-hidden="true">?</span></button></div>';
  }

  function sheetHead(title) {
    return '<div class="pet2-heading"><h2>' + esc(title) + '</h2>'
      + '<button class="pet-question pet2-close" data-lk-close aria-label="Закрыть">×</button></div>';
  }

  function showHelp(p, key) {
    const groups = handbook(p);
    if (key === 'all') {
      sheet('<div class="pet2-handbook">' + sheetHead('Справка о питомце') + groups.map(([title, topics]) =>
        '<h3>' + esc(title) + '</h3>' + topics.map(([, question, answer]) =>
          '<details><summary>' + esc(question) + '</summary><p>' + esc(answer) + '</p></details>').join('')
      ).join('') + '</div>');
      return;
    }
    const item = groups.flatMap(([, topics]) => topics).find(([id]) => id === key);
    if (item) sheet('<div class="pet2-handbook">' + sheetHead(item[1]) + '<p>' + esc(item[2])
      + '</p><button class="secondary" data-pet-help="all">Открыть справочник</button></div>');
  }

  function showStage(p, stage) {
    const d = p.development;
    const s = d.stages[stage - 1];
    if (!s) return;
    const detail = s.status === 'locked'
      ? 'Откроется автоматически после предыдущего этапа. На каждый переход нужно ' + d.rules.stage_xp + ' XP.'
      : s.kind === 'reputation' ? 'Начислено: ' + s.amount + ' репутации с учётом потолка профиля.'
      : s.kind === 'cookies' ? 'В кошелёк начислено ' + s.amount + ' 🍪.'
      : s.status === 'available' ? 'Награда сохранится, пока ты её не применишь.'
      : s.kind === 'unlock' ? 'Возможность открыта.' : 'Награда использована.';
    const topic = stage === d.rules.video_stage ? 'video' : stage === d.rules.ai_stage ? 'ai' : 'rewards';
    sheet('<div class="pet2-handbook">' + sheetHead('Этап ' + stage) + '<p class="sub">'
      + esc(s.level_name) + ' · ур. ' + s.level + ' · ' + status[s.status] + '</p><h3>'
      + esc(s.label) + '</h3><p>' + esc(detail) + '</p>'
      + (s.status === 'available' ? rewardButton(s, p) : '') + '<button class="text-btn" data-pet-help="'
      + topic + '">Как это работает</button></div>');
  }

  function clock() {
    const el = document.querySelector('[data-pet-reset]');
    if (!el) return;
    const minutes = Math.max(0, Math.ceil((Date.parse(el.dataset.petReset) - Date.now()) / 60000));
    el.textContent = minutes ? 'Новые через ' + Math.floor(minutes / 60) + ':' + String(minutes % 60).padStart(2, '0')
      : 'Обновляем задания…';
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
