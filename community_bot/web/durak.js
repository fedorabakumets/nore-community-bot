const labels = {
  players: [2,3,4,5,6], deck: [24,36,52], speed: {normal:'Обычная',fast:'Быстрая'},
  variant: {throw:'Подкидной',transfer:'Переводной'}, scope: {neighbours:'Соседи',all:'Все'},
  honesty: {cheats:'С шулерами',fair:'Честная игра'}, ending: {classic:'Классика',draw:'Ничья'},
};
const initial = {players:2,deck:36,stake:100,speed:'normal',variant:'throw',scope:'neighbours',honesty:'fair',ending:'classic',private:false};
const ranks = ['2','3','4','5','6','7','8','9','T','J','Q','K','A'];
const suits = ['♣','♦','♥','♠'];
// Equal distances on the slider span the same ratio. Both decades use the same convenient stops.
const firstDecade=[100,125,150,175,200,250,300,350,400,450,500,550,600,650,700,750,800,850,900,950];
const values=[5,10,25,50,75,...firstDecade,...firstDecade.map(n=>n*10),10000];
const face = c => '/durak-cards/'+ranks[c>>2]+'CDHS'[c%4]+'.svg';
const faceName = c => (ranks[c>>2]==='T'?'10':ranks[c>>2])+suits[c%4];
const chips = n => number(n)+' 🍪';
const seconds = c => c.speed==='fast'?20:60;
const key = 'nora-durak-'+(tg?.initDataUnsafe?.user?.id||'session');
let host, mode='open', list, room, config={...initial}, target, friends, inviteCode='', selected=null;
let challenge=false, batch=null, pending=false, message='', watch, refreshTimer, timer, generation=0, drag;
let clockDeadline=0, undoDeadline=0, menuRequest=0, activeParam='', lastTap, handledPointer;
let reactionCursor='', reactionReady=0, reactionPending=false, sortRank, hints, showReactions;
let lobbyEntry=false;
let itemsPending=false;
const landing=new Map(), receivedReactions=new Map();
let reactionsPreloaded=false;
const store = (name,value) => { try { if(value===null)sessionStorage.removeItem(key+name);else sessionStorage.setItem(key+name,value); } catch {} };
const stored = name => {try{return sessionStorage.getItem(key+name)}catch{return null}};
const nameAt = seat => room?.members.find(m=>m.seat===seat)?.name||'Участник';
const actionButton = (action,text,cls='dk-secondary',extra='') => `<button type="button" class="${cls}" data-dk="${action}" ${extra}>${text}</button>`;
const why = c => list?.restriction || (list?.active ? 'У тебя уже есть незавершённая партия' :
  list && list.balance<c.stake ? 'Не хватает печенек для этой ставки' : '');
const cardImg = c => `<img draggable="false" alt="${faceName(c)}" src="${face(c)}">`;
const portrait = m => `<span class="dk-avatar" data-person-avatar="${m.id}" ${m.avatar?'':'data-avatar-unavailable'}>${esc(Array.from(m.name)[0]||'•')}</span>`;
const blurb = c => `${labels.variant[c.variant]} · ${c.deck} карты · ${seconds(c)} с`;
function rulesInfo(c){
  return `<details class="dk-info"><summary>Правила и выигрыш</summary>
    <p>Каждому по шесть карт. Открывает младший козырь. До первого отбоя можно подкинуть до пяти карт, затем до шести, в пределах руки защищающегося.</p>
    <p>${c.variant==='transfer'?'До первого покрытия можно перевести атаку картой того же достоинства.':'Карты бьют старшей той же масти или козырем.'} Подкидывают ${c.scope==='all'?'все по очереди':'два соседа защищающегося'}.</p>
    <p>${c.honesty==='cheats'?'Можно подкинуть или отбить любой картой. Оспорь чужую карту до конца проверки. Ошибка в обвинении или пойманное шулерство лишают права жульничать до конца партии.':'Сервер проверяет масть и достоинство каждой карты.'} ${c.ending==='draw'?'Последний игрок может отбить последние карты и свести партию вничью.':'Последний игрок с картами проигрывает.'}</p>
    <p>До старта резерв возвращается при выходе. После старта сдача и тайм-аут (${seconds(c)} с) означают поражение. Карты прерванного захода возвращаются владельцам, остальные продолжают.</p>
    <p>Победители поровну делят весь банк. Остаток по одной печеньке получают раньше вышедшие, при равенстве — по месту за столом. При ничьей ставки возвращаются, доли сдавшихся делятся между остальными. Техническая отмена возвращает все резервы.</p></details>`;
}
function header(title,backText=lobbyEntry?'Игры':'Дурак'){
  const back = backText==='Игры'?'<button type="button" class="dk-back" data-tab="games">← Игры</button>':
    actionButton('back','← '+backText,'dk-back');
  return `<header class="dk-heading">${back}<h1>${title}</h1></header>`;
}
function row(r,kind){
  const c=r.config, own=list?.mine?.some(m=>m.id===r.id), denied=own?'':why(c);
  const timeLabel = r.status==='playing'?'Идёт партия':r.status==='waiting'?`${r.count} из ${c.players} мест`:
    r.status==='finished'?'Завершена':'Закрыта';
  return `<button type="button" class="dk-room" data-dk="${own?'resume':'preview'}" data-id="${r.id}" data-kind="${kind}">
    <span class="dk-room-icon" aria-hidden="true">${c.private?'♠':'♦'}</span>
    <span><strong>Стол ${esc(r.host_name)}</strong><small>${esc(blurb(c))}</small><small>${timeLabel}${denied?' · '+esc(denied):''}</small></span>
    <span class="dk-price">${chips(c.stake)}<small>${own?'Открыть':c.private?'Приватный':'Войти'} ›</small></span></button>`;
}
function playerHeader(){
  const u=data.user,name=u.profile_name||u.telegram_name||'Участник';
  return `<div class="dk-player-strip">${portrait({id:u.user_id,name,avatar:data.has_avatar&&!data.avatar_video})}
    <strong>${esc(name)}</strong><span>${chips(list?.balance??u.cookies)}</span>
    ${actionButton('topup','+','dk-topup','aria-label="Пополнить печеньки"')}</div>`;
}
function menuScreen(){
  return `${header('Дурак','Игры')}${playerHeader()}<div class="dk-main-menu">
    ${actionButton('quick','<span aria-hidden="true">▷</span>Быстрая игра','dk-main-quick')}
    <button type="button" data-tab="friends"><span aria-hidden="true">♧</span>Друзья</button>
    ${actionButton('items','<span aria-hidden="true">♢</span>Предметы','')}
    ${actionButton('create-form','<span aria-hidden="true">＋</span>Создать комнату','dk-main-create')}</div>`;
}
function quickScreen(){
  const open=list?.open||[];
  const quick=open.filter(r=>!why(r.config)).sort((a,b)=>
    a.config.stake-b.config.stake||(a.config.players-a.count)-(b.config.players-b.count))[0];
  return `${header('Быстрая игра','Дурак')}
    ${quick?actionButton('preview',`Подобрать стол · ${chips(quick.config.stake)}`,'dk-primary dk-wide',`data-id="${quick.id}"`):''}
    <div class="dk-tools">${actionButton('code-form','Войти по коду')}${actionButton('mine','Мои игры')}</div>
    ${open.map(r=>row(r,'open')).join('')||`<p class="dk-empty">${list?'Свободных столов пока нет.':'Ищем столы…'}</p>`}
    ${list?.next?actionButton('more','Ещё столы'):''}`;
}
const itemParts=[
  ['felt','Фон стола','night-felt.webp'],
  ['back','Рубашка карт','night-back.webp'],
  ['witch','Эмоции ведьмы','witch-1.webp'],
];
function itemsScreen(){
  const items=list?.items;
  return `${header('Предметы','Дурак')}${playerHeader()}${!items?'<p class="dk-empty">Загружаем предметы…</p>':`
    <section class="dk-pack">
      <img class="dk-pack-banner" src="/durak-cards/night-felt.webp" alt="">
      <div class="dk-pack-title"><h2>Ночной комплект</h2><strong>${items.owned?'Куплен':chips(items.price)}</strong></div>
      ${itemParts.map(([key,label,art])=>`<label class="dk-pack-part">
        <img src="/durak-cards/${art}" alt=""><strong>${label}</strong>
        ${items.owned?`<input type="checkbox" data-item="${key}" ${items.equipped[key]?'checked':''} ${itemsPending?'disabled':''}>`:''}</label>`).join('')}
      <div class="dk-tools">
        ${items.owned?'':actionButton('buy-night','Купить за '+chips(items.price),'dk-primary',itemsPending?'disabled':'')}
        ${actionButton('gift-night','Подарить','dk-secondary',itemsPending?'disabled':'')}
      </div>
    </section>`}`;
}
function giftScreen(){
  return `${header('Подарить комплект','Предметы')}<div class="dk-panel">
    ${friends?.map(m=>`<div class="dk-friend">${portrait(m)}<strong>${esc(m.name)}</strong>
      ${actionButton('gift-friend',chips(list.items.price),'dk-small',`data-id="${m.id}" ${itemsPending?'disabled':''}`)}</div>`).join('')
      ||`<p class="dk-muted">${friends?'Пока нет друзей, которым можно подарить комплект.':'Загружаем друзей…'}</p>`}</div>`;
}
async function saveItems(fields){
  if(itemsPending)return;
  const gen=generation;
  menuRequest++;itemsPending=true;paint();
  try{
    const {balance,...items}=await api('durak/items',fields);
    if(gen!==generation||!host)return;
    list={...list,balance,items};data.user.cookies=balance;
    if(fields.action==='buy'){
      if(fields.recipient){change('items');toast('Комплект подарен')}
      else toast('Ночной комплект включён');
    }
  }catch(err){if(gen===generation){message=err.message;toast(message)}}
  finally{
    itemsPending=false;
    if(host&&['items','gift'].includes(mode))paint();
  }
}
function confirmPack(friend){
  const price=chips(list.items.price);
  sheet(`<h2>${friend?'Подарить комплект':'Купить комплект'}</h2>
    <p>«Ночной комплект» ${friend?'для '+esc(friend.name)+' ':''}за <b>${price}</b></p>
    <button type="button" class="primary" id="dk-confirm-pack">Подтвердить</button>`);
  document.getElementById('dk-confirm-pack').onclick=()=>{
    document.getElementById('sheet').close();
    saveItems({action:'buy',...(friend?{recipient:friend.id}:{})});
  };
}
function group(name,title){
  const options = Array.isArray(labels[name])?labels[name].map(v=>[v,v]):Object.entries(labels[name]);
  const glyph={throw:'↗',transfer:'↻',neighbours:'⇥⇤',all:'✣',cheats:'♣',fair:'◇',classic:'♠',draw:'＝'};
  return `<fieldset class="dk-group"><legend>${title}</legend><div class="dk-segments">${options.map(([value,text])=>{
    const disabled = name==='players' ? value*6>config.deck : name==='deck' ? value<config.players*6 : false;
    const visual=glyph[value]?`<i aria-hidden="true">${glyph[value]}</i>`:'';
    return `<button type="button" data-option="${name}" data-value="${value}" aria-pressed="${config[name]===value}" ${disabled?'disabled title="Нужно шесть карт каждому"':''}>${visual}<span>${text}</span></button>`;
  }).join('')}</div></fieldset>`;
}
function createScreen(){
  const range=Math.max(0,values.findIndex(n=>n>=config.stake));
  return `${header('Создание игры')}<div class="dk-panel"><div class="dk-stake"><label for="dk-stake">Твоя ставка</label><span>${chips(config.stake)}</span></div>
    <input id="dk-stake" type="range" min="0" max="${values.length-1}" step="1" value="${range}" aria-valuetext="${config.stake} печенек">
    <div class="dk-ends"><small>5</small><small>1 000</small><small>10 000 🍪</small></div>
    <small class="dk-muted">Баланс ${chips(list?.balance||0)}</small></div>
    <div class="dk-panel dk-setup">${group('players','Игроки')}<div class="dk-deck-speed">${group('deck','Колода')}${group('speed','Скорость')}</div>
    ${config.deck===24||config.players>4?'<small class="dk-muted">Колода на 24 карты вмещает до четырёх игроков.</small>':''}
    <small class="dk-muted">На ход ${seconds(config)} секунд</small></div>
    <div class="dk-panel dk-rules-panel"><h2>Режимы игры</h2><div class="dk-rule-grid">${group('variant','Игра')}${group('scope','Подкидывают')}${group('honesty','Проверка карт')}${group('ending','Концовка')}</div></div>
    <div class="dk-create-row"><label class="dk-private"><input type="checkbox" id="dk-private" ${config.private?'checked':''}><span>Приватная игра</span></label>
    ${actionButton('create',`Создать за ${chips(config.stake)}`,'dk-primary',why(config)||!list?'disabled':'')}</div>
    <p class="dk-hint" id="dk-eligibility">${esc(why(config))}</p>${rulesInfo(config)}`;
}
function settingsLine(c){
  return `<div class="dk-spec"><span>${labels.variant[c.variant]}</span><span>${c.deck} карты</span><span>${seconds(c)} с на ход</span><span>${labels.scope[c.scope]}</span><span>${labels.honesty[c.honesty]}</span><span>${labels.ending[c.ending]}</span></div>`;
}
function confirmJoin(){
  const c=target.config;
  return `${header('Вход за стол')}<div class="dk-panel"><h2>Стол ${esc(target.host_name)}</h2>
    <p>${target.count} из ${c.players} мест · ${c.private?'Приватная':'Открытая'} игра</p>${settingsLine(c)}
    <div class="dk-stake"><span>Твой резерв</span><strong>${chips(c.stake)}</strong></div></div>
    ${rulesInfo(c)}<p class="dk-hint">${esc(why(c))}</p>
    ${actionButton('join','Сесть за '+chips(c.stake),'dk-primary dk-wide',why(c)||!list?'disabled':'')}`;
}
function privateScreen(){
  const mine=(list?.mine||[]).filter(r=>r.config.private&&['waiting','playing'].includes(r.status));
  return `${header('Приватные игры')}<form id="dk-code-form" class="dk-panel"><label for="dk-code">Код или ссылка приглашения</label>
    <input id="dk-code" autocomplete="off" autocapitalize="off" spellcheck="false" required maxlength="240" value="${esc(inviteCode)}">
    <button class="dk-primary dk-wide">Найти стол</button></form>${actionButton('new-private','Создать приватный стол','dk-secondary dk-wide')}
    ${list?.invites.length?`<h2>Приглашения</h2>${list.invites.map(r=>row(r,'invite')).join('')}`:''}
    ${mine.length?`<h2>Мои столы</h2>${mine.map(r=>row(r,'mine')).join('')}`:''}`;
}
function waiting(){
  const c=room.config, own=room.members.find(m=>m.seat===room.own);
  return `${header('Ждём игроков')}<div class="dk-panel"><div class="dk-stake"><h2>${c.private?'Приватный':'Открытый'} стол</h2><strong>${chips(c.stake)}</strong></div>
    <p class="dk-muted">Партия начнётся, когда займут все ${c.players} места.</p>${settingsLine(c)}
    <div class="dk-seats">${Array.from({length:c.players},(_,i)=>{
      const m=room.members.find(p=>p.seat===i);
      return m?`<div>${portrait(m)}<span><strong>${esc(m.name)}</strong><small>${m.id===room.host?'Создатель':m.seat===room.own?'Твоё место':'За столом'}</small></span><b>${chips(m.reserved)}</b></div>`:
        `<div class="dk-vacant"><i>+</i><span>Свободное место</span></div>`;
    }).join('')}</div></div>
    ${actionButton('friends','Пригласить друзей','dk-primary dk-wide')}<div class="dk-tools">${actionButton('share','В Telegram')}${actionButton('copy','Ссылка')}</div>
    ${actionButton('copy-code','Скопировать код','dk-text')}${rulesInfo(c)}
    ${actionButton('leave-confirm',own.id===room.host?'Отменить стол':'Выйти с возвратом','dk-text dk-danger')}`;
}
function friendScreen(){
  return `${header('Пригласить друзей','К столу')}<div class="dk-panel">${friends?friends.length?friends.map(m=>{
    const here=room.members.some(p=>p.id===m.id), sent=room.invited.includes(m.id);
    return `<div class="dk-friend">${portrait({...m,avatar:m.has_avatar})}<strong>${esc(m.name)}</strong>${actionButton('invite',here?'За столом':sent?'Отправлено':'Позвать','dk-small',`data-id="${m.id}" ${here||sent||!m.available?'disabled':''}`)}</div>`;
  }).join(''):'<p>Пока нет друзей. Можно пригласить игрока по ссылке.</p>':'Загружаем список друзей…'}</div>`;
}
const emotions = ['Привет рукой','Безразличие','Громкий смех','Насмешка с картами','Закатывание глаз',
  'Улыбка','Подмигивание','Радостное приветствие','Одобрение','Цветы',
  'Дразнит','В очках','Воздушный поцелуй','Удивление','Неловкость',
  'Грусть','Вызов картой','Нейтральное выражение','Скепсис','Озадаченность',
  'Хитрая улыбка','Злость','Злорадство','Фейспалм','Задумчивость'];
const witchEmotions=['Подмигнула','Хохочет','Удивилась','Надулась','Ухмыляется','Воздушный поцелуй',
  'Смутилась','Разозлилась','Аплодирует'];
const reactionImage = id => '/durak-cards/'+(id>25?'witch-'+(id-25):'reaction-'+id)+'.webp';
const reducedMotion = () => matchMedia('(prefers-reduced-motion: reduce)').matches;
const randomNonce = () => Array.from(crypto.getRandomValues(new Uint8Array(16)), n=>n.toString(16).padStart(2,'0')).join('');
const storedPreference = name => {try{return localStorage.getItem(key+name)}catch{return null}};
function savePreference(name,value){
  try{localStorage.setItem(key+name,value)}catch{}
}

function seatLabel(g,seat){
  if(g.forfeit.includes(seat))return 'Сдался';
  if(g.out.includes(seat))return 'Вышел';
  if(seat===g.defender)return 'Защита';
  if(seat===g.attacker)return 'Атака';
  return '';
}
function turnText(g){
  if(g.phase==='review')return 'Проверка карт';
  if(g.turn===room.own)return {attack:'Твой ход',defend:'Отбивайся',throw:g.taking?'Подкинь или спасуй':'Подкинь или заверши'}[g.phase];
  return `${g.taking?'Забирает':g.phase==='defend'?'Отбивается':'Ходит'} · ${nameAt(g.turn)}`;
}
function movesFor(g,card){
  return g.moves.filter(m=>m.card===card&&['attack','defend','transfer'].includes(m.kind));
}
function groupCandidates(g,first){
  if(!g.moves.some(m=>m.kind==='attack'&&m.card===first)||g.capacity-g.table.length<2)return [];
  return g.moves.filter(m=>m.kind==='attack'&&(m.card>>2)===(first>>2)).map(m=>m.card);
}
function controls(g){
  if(challenge)return `<div class="dk-checks" aria-label="Выбери карту для проверки">${g.challenge.map(c=>
    actionButton('report',faceName(c),'dk-secondary',`data-card="${c}" aria-label="Оспорить ${faceName(c)}"`)).join('')}</div>`+
    actionButton('challenge-mode','Закрыть');
  if(batch)return actionButton('attack-group',`Сыграть ×${batch.length}`,'dk-primary',batch.length<2?'disabled':'')+
    actionButton('batch-cancel','Отмена');
  const picked=movesFor(g,selected), buttons=[];
  if(picked.some(m=>m.kind==='attack'))buttons.push(actionButton('attack',g.table.length?'Подкинуть':'Походить','dk-secondary'));
  if(groupCandidates(g,selected).length>1)buttons.push(actionButton('batch','Несколько карт'));
  if(picked.some(m=>m.kind==='transfer'))buttons.push(actionButton('transfer','Перевести'));
  const cover=picked.filter(m=>m.kind==='defend');
  if(cover.length===1)buttons.push(actionButton('defend','Отбить','dk-secondary',`data-slot="${cover[0].slot}"`));
  if(cover.length>1)buttons.push('<span class="dk-muted">Выбери карту на столе</span>');
  if(g.moves.some(m=>m.kind==='take'))buttons.push(actionButton('take','Беру','dk-primary'));
  if(g.moves.some(m=>m.kind==='pass'))buttons.push(actionButton('pass',g.taking?'Пас':'Бито','dk-primary'));
  if(g.challenge.length)buttons.push(actionButton('challenge-mode','Оспорить'));
  if(g.moves.some(m=>m.kind==='undo'))buttons.push(actionButton('undo','Вернуть ход','dk-secondary','data-undo'));
  if(!buttons.length)buttons.push(`<span class="dk-muted">${g.moves.some(m=>m.card!==undefined)?'Перетащи карту на стол':'Ожидаем ход'}</span>`);
  return buttons.join('');
}
function chair(m,g){
  const own=m.seat===room.own,role=seatLabel(g,m.seat),count=g.counts[m.seat];
  const backs=own||!count?'':`<span class="dk-backs" aria-hidden="true">${'<i></i>'.repeat(Math.min(3,count))}</span>`;
  const avatar=own?actionButton('reactions',portrait(m),'dk-avatar-button',
    'aria-label="Эмоции" aria-controls="dk-reaction-panel" aria-expanded="false"'):portrait(m);
  return `<div class="dk-chair ${own?'dk-own':''} ${g.turn===m.seat?'is-turn':''} ${role==='Защита'?'is-defender':''}"
    data-seat="${m.seat}" data-player="${m.id}">
    <span class="dk-seat-emblem">${avatar}<svg class="dk-seat-ring" viewBox="0 0 44 44" aria-hidden="true">
      <circle cx="22" cy="22" r="20"/><circle cx="22" cy="22" r="20" pathLength="100"/></svg>
      <i class="dk-direction" aria-label="Защищается">▸</i><span class="dk-bubble" aria-hidden="true"></span>
      <span class="dk-say" role="status"></span></span>
    <span class="dk-seat-detail"><strong>${own?'Ты':esc(m.name)}</strong><small>${backs}${own?'':count}${role?`<span>${role}</span>`:''}${g.marked.includes(m.seat)?'<b title="Уличён в шулерстве">!</b>':''}</small></span>
  </div>`;
}
function gameScreen(){
  const g=room.game,c=room.config;
  const others=Array.from({length:room.members.length-1},(_,i)=>room.members[(room.own+i+1)%room.members.length]);
  const bySuit=(a,b)=>((a%4===g.trump)-(b%4===g.trump))||a%4-b%4||a-b;
  const ownHand=[...g.hand].sort(sortRank?(a,b)=>a-b:bySuit);
  const rows=Math.ceil(ownHand.length/12)||1,columns=Math.ceil(ownHand.length/rows)||1;
  const cardMoves=new Set(batch?groupCandidates(g,batch[0]):g.moves.map(m=>m.card));
  const exit=lobbyEntry?'<button type="button" class="dk-back" data-tab="games">← Столы</button>':
    actionButton('back','← Столы','dk-back');
  return `<header class="dk-gamehead">${exit}<strong>${labels.variant[c.variant]}</strong><span>${chips(c.stake)}</span>
    ${actionButton('game-info','⋯','dk-back','aria-label="Настройки и правила стола"')}</header>
    <div class="dk-felt" data-players="${room.members.length}">
      <div class="dk-opponents">${others.map(m=>chair(m,g)).join('')}</div>
      <div class="dk-stock" data-origin="deck" aria-label="В колоде ${g.stock}, козырь ${suits[g.trump]}">
        ${g.bottom!==null?`<img class="dk-trump" src="${face(g.bottom)}" alt="Козырь ${faceName(g.bottom)}">`:''}
        <span class="dk-backcard" ${g.stock?'':'data-empty'}>${g.stock}</span></div>
      <div class="dk-pairs" data-origin="table" data-slots="${g.table.length}">
        ${g.table.map(([a,d],i)=>`<div class="dk-pair" data-pair="${a}" data-slot="${i}">
          ${[a,d].map((card,j)=>card===null?'':`<button type="button" class="dk-tablecard ${j?'cover':''} ${challenge&&g.challenge.includes(card)?'can-check':''}"
            data-on-table="${card}" aria-label="${j?'Защита':'Атака'} ${faceName(card)}">${cardImg(card)}</button>`).join('')}</div>`).join('')}
        ${g.table.length<6?`<button type="button" class="dk-drop" data-drop tabindex="-1" aria-hidden="true" disabled><span></span></button>`:''}
      </div>
      ${actionButton('discard',`Отбой <b>${g.discard}</b>`,'dk-discard',`data-origin="discard" ${g.last_discard?.length?'':'disabled'}`)}
    </div>
    <div class="dk-turn">${chair(room.members[room.own],g)}
      <span class="dk-turn-text" aria-live="polite"><small>Заход ${g.round} · козырь ${suits[g.trump]}</small><strong>${esc(turnText(g))}</strong></span>
      <time id="dk-clock" aria-live="off"></time>
      ${actionButton('sort',sortRank?'Ранг':'Масть','dk-sort',`aria-label="Сортировка по ${sortRank?'достоинству':'масти'}. Переключить"`)}
    </div>
    <div class="dk-hand" data-origin="hand" aria-label="Твои карты" style="--rows:${rows};--columns:${columns}">${ownHand.map((card,i)=>{
      const row=Math.floor(i/columns),col=i%columns,count=Math.min(columns,ownHand.length-row*columns);
      const fan=rows===1?Math.max(-5,Math.min(5,(col-(count-1)/2)*1.6)):0;
      return `<button type="button" data-hand="${card}" class="dk-handcard ${hints&&cardMoves.has(card)?'legal':''}"
        style="--row:${row};--col:${col};--row-cards:${count};--fan:${fan}deg"
        aria-pressed="${batch?batch.includes(card):selected===card}" aria-label="${faceName(card)}">${cardImg(card)}</button>`;
    }).join('')}</div>
    <div class="dk-actions">${controls(g)}</div>
    <div id="dk-reaction-panel" class="dk-reaction-panel" role="region" aria-label="Эмоции" hidden></div>
    <p class="dk-error" role="status">${esc(message)}</p>`;
}
function syncAttributes(node,fresh){
  for(const attr of [...node.attributes])if(!fresh.hasAttribute(attr.name))node.removeAttribute(attr.name);
  for(const {name,value} of fresh.attributes)if(node.getAttribute(name)!==value)node.setAttribute(name,value);
}
function syncList(node,fresh,key,patch){
  const byKey=new Map([...node.children].map(child=>[key(child),child]));
  let next=node.firstElementChild;
  for(const incoming of [...fresh.children]){
    const id=key(incoming),current=byKey.get(id);
    byKey.delete(id);
    if(current)patch(current,incoming);
    const item=current||incoming;
    if(item!==next)node.insertBefore(item,next);
    next=item.nextElementSibling;
  }
  byKey.forEach(child=>child.remove());
}
function syncContents(node,fresh){
  if(node.innerHTML!==fresh.innerHTML)node.replaceChildren(...fresh.childNodes);
}
function syncChair(node,fresh){
  syncAttributes(node,fresh);
  syncContents(node.querySelector('.dk-seat-detail'),fresh.querySelector('.dk-seat-detail'));
}
function syncScene(html){
  const template=document.createElement('template');template.innerHTML=html;
  const fresh=template.content, node=selector=>host.querySelector(selector), incoming=selector=>fresh.querySelector(selector);
  const felt=node('.dk-felt');
  syncAttributes(felt,incoming('.dk-felt'));
  syncList(node('.dk-opponents'),incoming('.dk-opponents'),e=>e.dataset.player,syncChair);
  syncChair(node('.dk-own'),incoming('.dk-own'));
  for(const selector of ['.dk-stock','.dk-discard','.dk-turn-text','.dk-sort','.dk-actions','.dk-error']){
    const current=node(selector),replacement=incoming(selector);
    syncAttributes(current,replacement);syncContents(current,replacement);
  }
  const pairs=node('.dk-pairs'), newPairs=incoming('.dk-pairs');
  syncAttributes(pairs,newPairs);
  syncList(pairs,newPairs,e=>e.dataset.pair,(pair,next)=>{
    syncAttributes(pair,next);
    if(pair.matches('[data-pair]'))syncList(pair,next,e=>e.dataset.onTable,syncAttributes);
  });
  const hand=node('.dk-hand'),newHand=incoming('.dk-hand');
  syncAttributes(hand,newHand);
  syncList(hand,newHand,e=>e.dataset.hand,(card,next)=>{
    syncAttributes(card,next);
    card.classList.toggle('is-held',drag?.card===Number(card.dataset.hand)||landing.has(Number(card.dataset.hand)));
  });
}
function paint(){
  if(!host?.isConnected)return;
  const playing=mode==='room'&&room?.status==='playing';
  document.body.classList.toggle('dk-playing',playing);
  host.className='dk-root'+(playing?' dk-game':'');
  host.setAttribute('aria-live',playing?'off':'polite');
  host.dataset.revision=room?String(room.rev):'';
  host.dataset.mode=mode;
  host.toggleAttribute('data-night-felt',playing&&Boolean(room.cosmetics?.felt));
  host.toggleAttribute('data-night-back',playing&&Boolean(room.cosmetics?.back));
  if(playing){
    const html=gameScreen();
    if(host.querySelector('.dk-felt'))syncScene(html);
    else {
      host.innerHTML=html;
      if(!reactionsPreloaded){
        reactionsPreloaded=true;
        const preload=()=>emotions.forEach((_,i)=>{
          const img=new Image();img.fetchPriority='low';img.src=reactionImage(i+1);
        });
        if(window.requestIdleCallback)window.requestIdleCallback(preload,{timeout:1000});
        else setTimeout(preload,200);
      }
    }
    updateTargets();
    lockActions();
    clockTick();
    return;
  }
  let html;
  if(mode==='open')html=menuScreen();
  if(mode==='quick')html=quickScreen();
  if(mode==='mine')html=`${header('Мои игры','Дурак')}${list?.invites.map(r=>row(r,'invite')).join('')||''}
    ${list?.mine.map(r=>row(r,'mine')).join('')||'<p class="dk-empty">Здесь появятся твои партии.</p>'}`;
  if(mode==='items')html=itemsScreen();
  if(mode==='gift')html=giftScreen();
  if(mode==='create')html=createScreen();
  if(mode==='code')html=privateScreen();
  if(mode==='preview'&&target)html=confirmJoin();
  if(mode==='friends'&&room)html=friendScreen();
  if(mode==='room'&&room)html=room.status==='waiting'?waiting():resultScreen();
  host.innerHTML=(html||`${header('Карточный стол')}<p class="dk-muted">Загружаем стол…</p>`)+
    `<p class="dk-error" role="status">${esc(message)}</p>`;
}

function resultScreen(){
  const r=room.result,own=room.members.find(p=>p.seat===room.own),cancel=room.status==='cancelled';
  const title=cancel?'Стол закрыт':r.forfeit.includes(own.seat)?'Поражение':r.reason==='draw'?'Ничья':own.payout?'Победа':'Поражение';
  const stopped=r.forfeit.length?nameAt(r.forfeit[r.forfeit.length-1]):'Игрок';
  const reason={technical:'Партия закрыта по технической причине. Все резервы возвращены.',
    account_reset:'Аккаунт участника сброшен. Все резервы возвращены.',
    maintenance:'Стол закрыт на обслуживание. Все резервы возвращены.',cancelled:'Создатель отменил стол. Резервы возвращены.',
    expired:'За час стол не заполнился. Резервы возвращены.',surrender:stopped+' покинул стол.',timeout:'Время на ход истекло у '+stopped+'.',
    draw:'Последние карты отбиты.',played:r.loser!==null?`Дурак за столом — ${nameAt(r.loser)}.`:''};
  return `${header('Результат')}<div class="dk-result"><span aria-hidden="true">${cancel?'♧':r.reason==='draw'?'♦':own.payout?'♥':'♠'}</span>
    <h2>${title}</h2><p>${esc(reason[r.reason]||'')}</p><strong>${chips(own.payout||0)}</strong><small>${cancel?'Возвращено в кошелёк':'Зачислено в кошелёк'}</small></div>
    <div class="dk-panel">${room.members.map(m=>`<div class="dk-friend">${portrait(m)}<strong>${esc(m.name)}</strong><span>${chips(m.payout||0)}</span></div>`).join('')}</div>
    ${actionButton('again','Сыграть ещё','dk-primary dk-wide')}`;
}
function clockTick(){
  const el=host?.querySelector('#dk-clock');
  if(!el)return;
  const remaining=Math.max(0,clockDeadline-performance.now()/1000);
  const left=Math.ceil(remaining);
  const portion=Math.min(1,remaining/seconds(room.config));
  host.style.setProperty('--dk-time',String(portion*100));
  host.style.setProperty('--dk-time-color',`hsl(${portion*130} 85% ${portion>0.45?57:62}%)`);
  if(el.textContent!==left+' с')el.textContent=left+' с';
  el.classList.toggle('urgent',left<=5);
  const undo=host.querySelector('[data-undo]');
  if(undo)undo.disabled=pending||performance.now()/1000>=undoDeadline;
  if(left<=0&&drag)cancelDrag();
}
function lockActions(){
  host?.querySelectorAll('.dk-actions button:not([data-undo])').forEach(button=>{
    if(pending&&!button.disabled){
      button.disabled=true;
      button.dataset.awaitingMove='';
    }else if(!pending&&button.hasAttribute('data-awaiting-move')){
      button.disabled=false;
      delete button.dataset.awaitingMove;
    }
  });
}
function stopNetwork(){
  generation++;watch?.abort();watch=null;clearTimeout(refreshTimer);clearInterval(timer);menuRequest++;
}
function change(next){
  cancelDrag();landing.forEach(el=>el.remove());landing.clear();
  stopNetwork();mode=next;message='';selected=null;challenge=false;batch=null;lastTap=null;
  if(next!=='room'&&next!=='friends')store('room',null);
  paint();window.scrollTo(0,0);
}
function errorText(err){
  message=err.message||'Соединение прервалось';
  const el=host?.querySelector('.dk-error');
  if(el)el.textContent=message;
}
async function readMenu(append=false){
  const gen=generation,seq=++menuRequest;
  try{
    const fresh=await api('durak'+(append&&list?.next?'?before='+encodeURIComponent(list.next):''));
    if(gen!==generation||seq!==menuRequest||!host)return;
    if(append)fresh.open=[...list.open,...fresh.open.filter(r=>!list.open.some(o=>o.id===r.id))];
    list=fresh;message='';paint();
  }catch(err){if(gen===generation)errorText(err)}
  if(gen===generation&&seq===menuRequest&&['open','quick','mine'].includes(mode)&&!document.hidden){
    clearTimeout(refreshTimer);refreshTimer=setTimeout(()=>readMenu(),12000);
  }
}
function flash(event){
  if(!host||!room)return;
  const text=event.kind==='challenge'?`${nameAt(event.marked)} уличён в шулерстве`:
    ['surrender','timeout'].includes(event.kind)?`${nameAt(event.seat)} ${event.kind==='timeout'?'пропустил ход':'сдался'}`:'';
  if(text)toast(text);
}
function showActions(frames){
  const labels={attack:'Подкинул',defend:'Отбиваю',transfer:'Перевод',pass:'Пас',take:'Беру',
    discard:'Бито',collect:'Беру',challenge:'Проверяю',undo:'Отмена',surrender:'Сдаюсь',timeout:'Время вышло'};
  const recent=new Map();
  for(const frame of frames)for(const event of frame.events){
    if(event.seat!=null&&labels[event.kind])recent.set(event.seat,
      event.kind==='attack'&&event.opening?'Хожу':labels[event.kind]);
  }
  for(const [seat,text] of recent){
    const node=host.querySelector(`[data-seat="${seat}"] .dk-say`);
    if(!node)continue;
    const badge=document.createElement('b');
    badge.textContent=text;node.replaceChildren(badge);
    setTimeout(()=>badge.remove(),2300);
  }
}
function box(el){
  if(!el)return null;
  const r=el.getBoundingClientRect();
  return {x:r.left,y:r.top,w:r.width,h:r.height};
}
function positions(){
  const map=new Map();
  host?.querySelectorAll('.dk-chair .dk-avatar,[data-origin],[data-on-table],[data-hand]').forEach(el=>{
    const {seat,origin,onTable,hand}=el.matches('.dk-avatar')?el.closest('[data-seat]').dataset:el.dataset;
    if(seat!==undefined)map.set('seat'+seat,box(el));
    if(origin!==undefined)map.set(origin,box(el));
    if(onTable!==undefined)map.set('table'+onTable,box(el));
    if(hand!==undefined)map.set('hand'+hand,box(el));
  });
  return map;
}
function animateHand(before,after){
  if(reducedMotion())return;
  for(const el of host.querySelectorAll('[data-hand]:not(.is-held)')){
    const id='hand'+el.dataset.hand,a=before.get(id);
    const moving=el.getAnimations().find(animation=>animation.id==='durak-hand');
    moving?.cancel();
    const b=moving?box(el):after.get(id);
    if(!a||!b||Math.abs(a.x-b.x)+Math.abs(a.y-b.y)<1)continue;
    el.animate([{transform:`translate(${a.x-b.x}px,${a.y-b.y}px)`},{transform:'none'}],
      {id:'durak-hand',duration:185,easing:'cubic-bezier(.22,.7,.28,1)'});
  }
}
function flight(a,b,card,{delay=0,duration=230,el}={}){
  if(!a?.w||!a.h||!b?.w||!b.h||!host)return;
  const ghost=document.createElement('i');
  ghost.className='dk-flight';
  if(card!==null)ghost.style.backgroundImage=`url("${face(card)}")`;
  ghost.style.cssText+=`left:${a.x}px;top:${a.y}px;width:${a.w}px;height:${a.h}px`;
  host.append(ghost);
  const animation=ghost.animate([{transform:'none'},{transform:`translate(${b.x-a.x}px,${b.y-a.y}px) scale(${b.w/a.w},${b.h/a.h})`}],
    {duration,delay,fill:'backwards',easing:'cubic-bezier(.22,.72,.28,1)'});
  if(delay)ghost.animate([{opacity:0},{opacity:0}],{duration:delay});
  el?.animate([{opacity:0},{opacity:0}],{duration:delay+duration});
  animation.onfinish=animation.oncancel=()=>ghost.remove();
}
function motion(frames,before,after,previous){
  const events=frames.flatMap(f=>f.events);
  events.forEach(flash);
  if(!host?.classList.contains('dk-game')||reducedMotion())return;
  const point=k=>after.get(k)||before.get(k);
  const cardSize=host.querySelector('.dk-tablecard,.dk-handcard')?.getBoundingClientRect().width||48;
  const cardAt=(p,w=cardSize*.76)=>p&&({x:p.x+(p.w-w)/2,y:p.y+(p.h-w*1.42)/2,w,h:w*1.42});
  const stock=cardAt(point('deck')),desk=cardAt(point('table')),discard=cardAt(point('discard'));
  const seat=s=>cardAt(point('seat'+s));
  const hand=card=>host.querySelector(`[data-hand="${card}"]`);
  const table=card=>host.querySelector(`[data-on-table="${card}"]`);
  const collected=new Set(events.filter(e=>e.kind==='collect'&&e.seat===room.own).flatMap(e=>e.cards));
  let drawIndex=0, played=0;
  const newHand=(room.game?.hand||[]).filter(c=>!previous?.hand.includes(c)&&!collected.has(c));
  for(const event of events){
    const {kind,card,cards,seat:player}=event,own=player===room.own;
    if(kind==='deal'){
      host.querySelector('.dk-trump')?.animate([{opacity:0},{opacity:1}],{duration:250});
      for(let i=0;i<6;i++)room.members.forEach(m=>{
        const ownCard=room.game.hand[i], reveal=m.seat===room.own;
        flight(stock,reveal?point('hand'+ownCard):seat(m.seat),reveal?ownCard:null,
          {delay:i*37+m.seat*12,el:reveal?hand(ownCard):null});
      });
    }else if(['attack','defend','transfer'].includes(kind)){
      const released=landing.get(card);
      flight(own?(released?box(released.firstElementChild):before.get('hand'+card)):seat(player),
        point('table'+card)||desk,card,{delay:released?0:Math.min(played++*34,170),el:table(card)});
      released?.remove();
    }else if(['collect','discard','undo'].includes(kind)){
      cards.forEach((c,i)=>{
        const destination=kind==='discard'?discard:own?point('hand'+c):seat(player);
        flight(before.get('table'+c)||desk,destination,c,{delay:i*19,el:own?hand(c):null});
      });
    }else if(kind==='draw'){
      for(let i=0;i<event.count;i++){
        const c=own?newHand[drawIndex++]:undefined;
        flight(stock,c===undefined?seat(player):point('hand'+c),c??null,
          {delay:165+i*29,el:c===undefined?null:hand(c)});
      }
    }
  }
  if(events.some(e=>e.kind==='challenge'||e.kind==='surrender'||e.kind==='timeout')){
    for(const c of newHand)if(before.has('table'+c))flight(before.get('table'+c),point('hand'+c),c,{el:hand(c)});
  }
  animateHand(before,after);
}
function syncReactions(view){
  if(view.reaction_cursor!==undefined)reactionCursor=view.reaction_cursor;
  for(const event of view.reactions||[]){
    if(event.room_id!==room?.id)continue;
    const last=receivedReactions.get(event.sender_id),left=(event.expires-view.reaction_now)*1000;
    if(last?.timestamp>=event.timestamp||left<=0)continue;
    receivedReactions.set(event.sender_id,event);
    const bubble=host.querySelector(`[data-player="${event.sender_id}"] .dk-bubble`);
    if(!bubble||!showReactions)continue;
    const img=document.createElement('img');
    img.src=reactionImage(event.emoji_id);img.alt=emotions[event.emoji_id-1];img.style.setProperty('--visible',left+'ms');
    bubble.replaceChildren(img);setTimeout(()=>img.remove(),left);
  }
}
async function sendReaction(id){
  if(reactionPending||performance.now()<reactionReady)return;
  const rid=room.id,gen=generation;
  reactionPending=true;
  setReactionPanel(false,true);
  try{
    const view=await api('durak/action',{action:'reaction',room:rid,emoji_id:id,nonce:randomNonce()});
    if(gen===generation){
      reactionReady=performance.now()+2800;
      syncReactions(view);
    }
  }catch(err){if(gen===generation)errorText(err)}
  finally{
    reactionPending=false;
    if(host?.querySelector('#dk-reaction-panel:not([hidden])'))setReactionPanel(true);
  }
}
function setReactionPanel(open,focus=false){
  const panel=host?.querySelector('#dk-reaction-panel'),button=host?.querySelector('[data-dk=reactions]');
  if(!panel||!button)return;
  if(open&&!panel.children.length){
    panel.innerHTML=`<div class="dk-reaction-head"><strong>Эмоции</strong>
      ${actionButton('reactions-close','×','dk-back','aria-label="Закрыть эмоции"')}</div>
      <div class="dk-emotions">${(room.cosmetics?.witch?[...emotions,...witchEmotions]:emotions).map((name,i)=>actionButton('react',`<img src="${reactionImage(i+1)}" alt="" width="96" height="96">`,'',
        `data-emoji="${i+1}" aria-label="${name}" title="${name}"`)).join('')}</div>
      <label><input type="checkbox" id="dk-react-show" ${showReactions?'checked':''}> Показывать эмоции в игре</label>`;
  }
  panel.hidden=!open;button.setAttribute('aria-expanded',String(open));
  if(open){
    const left=Math.max(0,reactionReady-performance.now());
    const options=[...panel.querySelectorAll('[data-emoji]')];
    options.forEach(btn=>btn.disabled=reactionPending||left>0);
    if(left>0)setTimeout(()=>options.forEach(btn=>btn.disabled=reactionPending),left);
    if(focus)panel.querySelector('[data-dk=reactions-close]').focus();
  }else if(focus)button.focus();
}
function accept(view,old){
  if(!view)return;
  if(view.unchanged){syncReactions(view);return}
  if(room?.id===view.id&&view.rev<room.rev)return;
  const first=!room||room.id!==view.id,changed=first||room.rev!==view.rev;
  if(!changed){syncReactions(view);return}
  const previous=room?.game,was=room?.status,before=positions();
  room=view;clockDeadline=performance.now()/1000+Math.max(0,view.deadline-view.now);
  undoDeadline=performance.now()/1000+Math.max(0,(view.game?.undo_until||0)-view.now);
  if(mode==='friends'&&room.status!=='waiting')mode='room';
  if(!room.game?.hand.includes(selected))selected=null;
  if(batch&&(!room.game||!batch.every(c=>groupCandidates(room.game,batch[0]).includes(c))||
      batch.length>room.game.capacity-room.game.table.length))batch=null;
  challenge=challenge&&Boolean(room.game?.challenge.length);
  if(drag&&(!room.game||!room.game.hand.includes(drag.card)||room.game.round!==drag.round||
      (drag.moves.length&&!liveDragMoves(drag).length)))cancelDrag();
  message='';
  const frames=view.frames.filter(f=>f.rev>old);
  if(!frames.length&&room.status==='playing'&&(was==='waiting'||(first&&room.game.events.some(e=>e.kind==='deal')))){
    frames.push({events:[{kind:'deal'}]});
  }
  if(was==='playing'&&room.status!=='playing'&&host.querySelector('.dk-felt')&&!reducedMotion()){
    const gen=generation;host.dataset.revision=String(view.rev);
    showActions(frames);
    motion(frames,before,before,previous);
    host.querySelector('.dk-felt').animate([{opacity:1},{opacity:.35}],{delay:90,duration:260,fill:'forwards'});
    setTimeout(()=>{if(gen===generation)paint()},490);
  }else{
    paint();showActions(frames);motion(frames,before,positions(),previous);syncReactions(view);
  }
  if(!['playing','waiting'].includes(room.status))clearInterval(timer);
}

async function syncLoop(id,gen){
  let failures=0;
  while(gen===generation&&!document.hidden&&host&&['room','friends'].includes(mode)){
    const previous=room?.id===id?room.rev:-1;
    const controller=new AbortController();watch=controller;
    try{
      const view=await api('durak/room/'+id+(previous>=0?'?after='+previous+'&reactions='+reactionCursor:''),null,controller.signal);
      if(gen!==generation)return;
      accept(view,previous);failures=0;
      if(!room||!['waiting','playing'].includes(room.status))return;
      if(view.retry)await new Promise(resolve=>setTimeout(resolve,view.retry*1000));
    }catch(err){
      if(gen!==generation||controller.signal.aborted)return;
      errorText(err);
      if([400,401,403,404].includes(err.status)){if(previous<0)store('room',null);return}
      await new Promise(resolve=>setTimeout(resolve,Math.min(8000,750*2**failures++)));
    }
  }
}
function openRoom(id,friendView=false){
  const same=room?.id===id;
  if(!same){room=null;reactionCursor='';reactionReady=0;receivedReactions.clear()}
  change(friendView?'friends':'room');store('room',id);
  timer=setInterval(clockTick,350);
  if(same&&room.status!=='waiting'&&room.status!=='playing'){clearInterval(timer);return}
  syncLoop(id,generation);
}
async function freshRoom(id){
  const gen=generation,rev=room?.id===id?room.rev:-1;
  const view=await api('durak/room/'+id+'?since='+rev);
  if(gen===generation&&host&&['room','friends'].includes(mode))accept(view,rev);
}
async function send(action,fields,after){
  if(pending)return;
  pending=true;message='';
  lockActions();clockTick();
  const gen=generation;
  const payload={action,...fields};
  const serialized=JSON.stringify(payload);
  let saved;
  try{saved=JSON.parse(stored('pending')||'null')}catch{}
  const nonce=saved?.serialized===serialized?saved.nonce:randomNonce();
  store('pending',JSON.stringify({serialized,nonce}));
  try{
    const reply=await api('durak/action',{...payload,nonce});
    store('pending',null);
    if(gen===generation&&host)await after(reply.id);
  }catch(err){
    if(gen===generation&&host){if(room&&['room','friends'].includes(mode))await freshRoom(room.id).catch(()=>{});errorText(err)}
  }finally{pending=false;lockActions();clockTick()}
}
function move(kind,slot){
  const candidate=room?.game?.moves.find(m=>m.kind===kind&&(m.card===undefined||m.card===selected)&&(slot===undefined||slot===m.slot));
  if(candidate)submitMove(candidate);
}
async function submitMove(candidate,gesture){
  if(pending||room?.status!=='playing')return;
  const rid=room.id,rev=room.rev;
  if(gesture)landing.set(gesture.card,gesture.el);
  lastTap=null;selected=null;batch=null;challenge=false;
  updateTargets();
  try{await send('move',{room:rid,rev,move:candidate},()=>room?.id===rid&&room.rev>rev?undefined:freshRoom(rid))}
  finally{
    if(gesture){
      landing.delete(gesture.card);
      if(gesture.b.isConnected)returnCard(gesture,true);
      else gesture.el.remove();
    }
    if(room?.id===rid&&room.rev===rev&&mode==='room')paint();
  }
}
function codeFrom(text){
  const raw=text.trim();
  if(/^[\w-]{22}$/.test(raw))return raw;
  try{const p=new URL(raw).searchParams.get('startapp');return /^nora_d_([\w-]{22})$/.exec(p)?.[1]}catch{return null}
}
async function previewCode(code){
  if(!code){errorText(Error('Введи код или полную ссылку приглашения'));return}
  const gen=generation;
  try{
    const found=await api('durak/preview',{code});
    if(gen!==generation||!host)return;
    if(list?.mine.some(r=>r.id===found.id)){if(activeParam)store('param',activeParam);openRoom(found.id);return}
    target=found;inviteCode=code;change('preview');
    if(!list)readMenu();
  }catch(err){if(gen===generation)errorText(err)}
}
async function openFriends(){
  openRoom(room.id,true);const gen=generation;
  try{const result=await api('friends');if(gen===generation){friends=result.friends;paint()}}
  catch(err){if(gen===generation)errorText(err)}
}
async function copyText(text){
  try{await navigator.clipboard.writeText(text);toast('Скопировано')}
  catch{sheet(`<h2>Скопировать приглашение</h2><input id="dk-copy" readonly value="${esc(text)}">`);document.getElementById('dk-copy').select()}
}
async function inviteLink(share){
  try{
    const {url}=await api('durak/room/'+room.id+'/link');
    if(share){
      const link='https://t.me/share/url?url='+encodeURIComponent(url)+'&text='+encodeURIComponent('Сыграем в Дурака в Норе?');
      if(tg?.openTelegramLink)tg.openTelegramLink(link);else window.open(link,'_blank','noopener');
    }else await copyText(url);
  }catch(err){errorText(err)}
}
function confirmLeave(){
  const waiting=room.status==='waiting',owner=room.host===room.members[room.own]?.id;
  const title=waiting?(owner?'Отменить стол?':'Выйти из комнаты?'):'Сдаться в партии?';
  sheet(`<h2>${title}</h2><p class="sub">${waiting?'Зарезервированные ставки вышедших игроков вернутся в кошельки.':'Тебе будет засчитано поражение. Ставка останется в банке.'}</p>
    <button class="primary" id="dk-confirm-leave">${waiting?(owner?'Отменить стол':'Выйти и вернуть ставку'):'Сдаться'}</button>`);
  document.getElementById('dk-confirm-leave').onclick=()=>{
    document.getElementById('sheet').close();
    send(waiting&&owner?'cancel':'leave',{room:room.id,rev:room.rev},async id=>{
      if(waiting&&!owner){room=null;change('mine');await readMenu()}else await freshRoom(id);
    });
  };
}
function back(){
  if(!host)return false;
  if(host.querySelector('#dk-reaction-panel:not([hidden])')){setReactionPanel(false,true);return true}
  if(mode==='friends'&&room){openRoom(room.id);return true}
  if(mode==='gift'){change('items');readMenu();return true}
  if(mode==='items'){change('open');readMenu();return true}
  if(!lobbyEntry&&mode!=='open'){change('open');readMenu();return true}
  return false;
}
function pick(card,quick=false){
  if(!room?.game?.hand.includes(card))return;
  if(batch){
    if(batch.includes(card)){
      batch=batch.filter(c=>c!==card);
      if(!batch.length){batch=null;selected=null}
    }else if(batch.length<room.game.capacity-room.game.table.length&&groupCandidates(room.game,batch[0]).includes(card)){
      batch.push(card);
    }
    paint();return;
  }
  const now=performance.now(),options=movesFor(room.game,card);
  if(quick&&lastTap?.card===card&&lastTap.rev===room.rev&&now-lastTap.at<420&&options.length===1){
    submitMove(options[0]);return;
  }
  lastTap=quick?{card,rev:room.rev,at:now}:null;
  selected=selected===card?null:card;challenge=false;paint();
}
function playOn(card,slot){
  if(challenge&&room.game.challenge.includes(card)){
    submitMove({kind:'challenge',card});
  }else if(selected!==null)move('defend',slot);
}
function click(e){
  if(e.detail>0&&handledPointer&&performance.now()-handledPointer.at<650&&
      (e.pointerId==null||e.pointerId===-1||e.pointerId===handledPointer.id||
        (handledPointer.type==='touch'&&e.pointerType==='mouse'))){
    handledPointer=null;
    e.preventDefault();e.stopPropagation();return;
  }
  const b=e.target.closest('button');
  if(!b||!host.contains(b)||b.disabled)return;
  if(host.classList.contains('dk-game')&&room?.status!=='playing')return;
  if(b.dataset.option){
    const name=b.dataset.option;config[name]=['players','deck'].includes(name)?Number(b.dataset.value):b.dataset.value;
    paint();return;
  }
  if(b.hasAttribute('data-hand')){pick(Number(b.dataset.hand),e.detail>0);return}
  if(b.hasAttribute('data-on-table')){
    if(challenge||!b.classList.contains('cover'))playOn(Number(b.dataset.onTable),Number(b.closest('[data-slot]').dataset.slot));
    return;
  }
  const act=b.dataset.dk;
  switch(act){
    case 'mine':change(act);readMenu();break;
    case 'more':readMenu(true);break;
    case 'back':back();break;
    case 'create-form':case 'new-private':config={...initial,private:act==='new-private'};change('create');readMenu();break;
    case 'again':config={...room.config};room=null;change('create');readMenu();break;
    case 'create':send('create',{config:{...config}},id=>{room=null;openRoom(id)});break;
    case 'quick':{
      if(list?.active){openRoom(list.active);break}
      change('quick');readMenu();break;
    }
    case 'topup':
      if(data.cookie_shop?.enabled)window.NoraShop?.openCategory('__cookies');
      else errorText(Error('Пополнение временно недоступно'));
      break;
    case 'items':change('items');readMenu();break;
    case 'buy-night':confirmPack();break;
    case 'gift-night':{
      friends=null;change('gift');const gen=generation;
      api('friends').then(result=>{if(gen===generation){friends=result.friends;paint()}})
        .catch(err=>{if(gen===generation)errorText(err)});
      break;
    }
    case 'gift-friend':{
      const friend=friends?.find(m=>m.id===Number(b.dataset.id));
      if(friend)confirmPack(friend);
      break;
    }
    case 'resume':openRoom(b.dataset.id);break;
    case 'code-form':inviteCode='';change('code');readMenu();break;
    case 'preview':target=[...list.open,...list.invites].find(r=>r.id===b.dataset.id);inviteCode='';if(target)change('preview');break;
    case 'join':send('join',{room:target.id,code:inviteCode},id=>{
      if(activeParam)store('param',activeParam);
      room=null;openRoom(id);
    });break;
    case 'friends':openFriends();break;
    case 'invite':send('invite',{room:room.id,friend:Number(b.dataset.id)},async id=>{await freshRoom(id);toast('Приглашение отправлено')});break;
    case 'copy-code':copyText(room.code);break;
    case 'copy':inviteLink(false);break;
    case 'share':inviteLink(true);break;
    case 'leave-confirm':confirmLeave();break;
    case 'sort':{
      cancelDrag();
      const before=positions();sortRank=!sortRank;savePreference('sort',sortRank?'rank':'suit');
      paint();animateHand(before,positions());break;
    }
    case 'reactions':setReactionPanel(b.getAttribute('aria-expanded')!=='true',true);break;
    case 'reactions-close':setReactionPanel(false,true);break;
    case 'react':sendReaction(Number(b.dataset.emoji));break;
    case 'drop':
      if(batch?.length>1&&b.dataset.kind==='attack')submitMove({kind:'attack_many',cards:[...batch]});
      else move(b.dataset.kind);
      break;
    case 'discard':
      if(room.game?.last_discard?.length)sheet(`<h2>Последний отбой</h2><div class="dk-history">${room.game.last_discard.map(cardImg).join('')}</div>`);
      break;
    case 'game-info':{
      const canLeave=!room.game.out.includes(room.own)&&!room.game.forfeit.includes(room.own);
      sheet(`<h2>Твой стол</h2>${settingsLine(room.config)}${rulesInfo(room.config)}
        <label><input type="checkbox" id="dk-hints" ${hints?'checked':''}> Подсвечивать карты с доступным ходом</label>
        ${canLeave?'<button class="secondary" id="dk-surrender">Сдаться</button>':''}`);
      document.getElementById('dk-hints').onchange=e=>{
        hints=e.target.checked;savePreference('hints',String(hints));paint();
      };
      const quit=document.getElementById('dk-surrender');
      if(quit)quit.onclick=()=>{document.getElementById('sheet').close();confirmLeave()};break;
    }
    case 'challenge-mode':challenge=!challenge;selected=null;paint();break;
    case 'report':playOn(Number(b.dataset.card));break;
    case 'batch':batch=[selected];paint();break;
    case 'batch-cancel':batch=null;selected=null;paint();break;
    case 'attack-group':
      if(batch?.length>1)submitMove({kind:'attack_many',cards:[...batch]});
      break;
    case 'attack':case 'take':case 'pass':case 'transfer':case 'undo':move(act);break;
    case 'defend':move('defend',Number(b.dataset.slot));break;
  }
}
function input(e){
  if(e.target.dataset.item){
    saveItems({action:'equip',part:e.target.dataset.item,enabled:e.target.checked});return;
  }
  if(e.target.id==='dk-react-show'){
    showReactions=e.target.checked;savePreference('reactions',String(showReactions));
    if(!showReactions)host.querySelectorAll('.dk-bubble').forEach(b=>b.replaceChildren());
    return;
  }
  if(e.target.id==='dk-code'){inviteCode=e.target.value;return}
  if(e.target.id==='dk-private'){config.private=e.target.checked;return}
  if(e.target.id!=='dk-stake')return;
  config.stake=values[Number(e.target.value)];
  e.target.setAttribute('aria-valuetext',config.stake+' печенек');
  host.querySelector('.dk-stake span').textContent=chips(config.stake);
  host.querySelector('#dk-eligibility').textContent=why(config);
  const btn=host.querySelector('[data-dk=create]');btn.disabled=!!why(config);btn.textContent='Создать за '+chips(config.stake);
}
function submit(e){if(e.target.id==='dk-code-form'){e.preventDefault();previewCode(codeFrom(host.querySelector('#dk-code').value))}}
function liveDragMoves(gesture){
  const g=room?.game;
  if(!g||g.round!==gesture.round||performance.now()/1000>=clockDeadline)return [];
  return movesFor(g,gesture.card).filter(m=>gesture.moves.some(old=>old.kind===m.kind&&old.slot===m.slot&&
    (m.kind!=='defend'||old.target===g.table[m.slot]?.[0])));
}
function hitTest(x,y,moves){
  const hit=document.elementFromPoint(x,y),pair=hit?.closest('[data-pair]');
  if(pair&&hit.closest('.dk-tablecard:not(.cover)')){
    const move=moves.find(m=>m.kind==='defend'&&m.slot===Number(pair.dataset.slot));
    return {node:pair,move};
  }
  const drop=hit?.closest('[data-drop]');
  if(drop)return {node:drop,move:moves.find(m=>m.kind===drop.dataset.kind)};
  return {node:hit?.closest('.dk-pairs')};
}
function updateTargets(){
  const g=room?.game,felt=host?.querySelector('.dk-felt');
  if(!g||!felt)return;
  const moves=drag?liveDragMoves(drag):movesFor(g,selected);
  const slot=host.querySelector('[data-drop]');
  if(slot){
    const kind=moves.find(m=>m.kind==='attack'||m.kind==='transfer')?.kind||'';
    slot.dataset.kind=kind;
    slot.disabled=!kind;
    slot.tabIndex=kind?0:-1;
    slot.setAttribute('aria-hidden',String(!kind));
    const title=kind==='transfer'?'Перевести':kind==='attack'?(g.table.length?'Подкинуть':'Ход сюда'):'';
    if(slot.firstChild.textContent!==title)slot.firstChild.textContent=title;
    if(slot.dataset.dk!=='drop')slot.dataset.dk='drop';
  }
  for(const pair of felt.querySelectorAll('[data-pair]')){
    pair.classList.toggle('can-cover',moves.some(m=>m.kind==='defend'&&m.slot===Number(pair.dataset.slot)));
  }
  highlightTarget(moves);
}
function highlightTarget(moves){
  const hit=drag?.moved?hitTest(drag.x,drag.y,moves):null;
  const previous=host?.querySelector('.is-target');
  const next=hit?.move?hit.node:null;
  if(previous!==next){previous?.classList.remove('is-target');next?.classList.add('is-target')}
}
function down(e){
  if(e.isPrimary)handledPointer=null;
  const b=e.target.closest('[data-hand]'),g=room?.game;
  if(!g||!b||drag||challenge||!e.isPrimary||e.button!==0)return;
  const card=Number(b.dataset.hand),at=box(b);
  const el=document.createElement('i');
  el.className='dk-flight dk-drag';
  el.style.cssText=`left:${at.x}px;top:${at.y}px;width:${at.w}px;height:${at.h}px`;
  el.innerHTML=cardImg(card);
  el.setAttribute('aria-hidden','true');
  const moves=movesFor(g,card).map(m=>({...m,target:g.table[m.slot]?.[0]}));
  drag={id:e.pointerId,card,b,el,moves,round:g.round,x:e.clientX,y:e.clientY,startX:e.clientX,startY:e.clientY};
  host.append(el);b.classList.add('is-held');
  host.setPointerCapture(e.pointerId);
  e.preventDefault();
  updateTargets();
}
function pointer(e){
  if(!drag||e.pointerId!==drag.id)return;
  drag.x=e.clientX;drag.y=e.clientY;
  const x=drag.x-drag.startX,y=drag.y-drag.startY;
  if(!drag.moved&&Math.hypot(x,y)<7)return;
  drag.moved=true;
  drag.el.style.transform=`translate3d(${x}px,${y}px,0)`;
  highlightTarget(liveDragMoves(drag));
}
function release(gesture){
  drag=null;
  if(host?.hasPointerCapture(gesture.id))host.releasePointerCapture(gesture.id);
  updateTargets();
}
function returnCard(gesture,rejected=false){
  const {b,el}=gesture;
  const reveal=()=>{
    if(drag?.b!==b&&!landing.has(gesture.card))b.classList.remove('is-held');
    el.remove();
  };
  if(!b.isConnected||reducedMotion()){reveal();return}
  const a=box(el),to=box(b);
  el.style.left=a.x+'px';el.style.top=a.y+'px';el.style.transform='none';
  el.classList.add('is-returning');
  const animation=el.animate([
    {transform:'none'},
    {transform:`translate(${to.x-a.x}px,${to.y-a.y}px)`},
  ],{duration:155,easing:'cubic-bezier(.22,.72,.28,1)'});
  animation.onfinish=animation.oncancel=reveal;
  if(rejected)el.firstElementChild.classList.add('is-rejected');
}
function cancelDrag(){
  if(!drag)return;
  const gesture=drag;
  release(gesture);returnCard(gesture);
}
function up(e){
  if(!drag||e.pointerId!==drag.id)return;
  const gesture=drag;
  if(e.type!=='pointerup'){cancelDrag();return}
  handledPointer={id:e.pointerId,type:e.pointerType,at:performance.now()};
  e.preventDefault();
  if(!gesture.moved&&Math.hypot(e.clientX-gesture.startX,e.clientY-gesture.startY)>=7)pointer(e);
  if(!gesture.moved){
    release(gesture);gesture.el.remove();gesture.b.classList.remove('is-held');
    pick(gesture.card,true);return;
  }
  const {node,move}=hitTest(e.clientX,e.clientY,liveDragMoves(gesture));
  release(gesture);
  if(!move||pending){
    returnCard(gesture,Boolean(node));
    return;
  }
  if(batch&&move.kind==='attack'&&batch.length>1&&batch.includes(gesture.card)){
    submitMove({kind:'attack_many',cards:[...batch]},gesture);
  }else submitMove(move,gesture);
}

function visibility(){
  if(!host)return;
  cancelDrag();stopNetwork();
  if(document.hidden)return;
  if(room&&['room','friends'].includes(mode)){openRoom(room.id,mode==='friends')}
  else if(['open','quick','mine','create','preview','items','gift'].includes(mode))readMenu();
}
function keydown(e){
  if(e.key==='Escape'&&host.querySelector('#dk-reaction-panel:not([hidden])')){
    e.stopPropagation();setReactionPanel(false,true);
  }
}
function mount(root){
  if(!root||host===root)return;
  host=root;mode='open';list=null;room=null;friends=null;message='';
  receivedReactions.clear();reactionCursor='';reactionReady=0;
  sortRank=storedPreference('sort')==='rank';
  showReactions=storedPreference('reactions')!=='false';hints=storedPreference('hints')!=='false';
  for(const [type,fn] of Object.entries({click,input,submit,keydown,pointerdown:down,pointermove:pointer,pointerup:up,pointercancel:up,lostpointercapture:up}))host.addEventListener(type,fn);
  document.addEventListener('visibilitychange',visibility);
  const entry=durakEntry;
  durakEntry=null;
  lobbyEntry=Boolean(entry);
  if(entry?.create){
    config={...initial};change('create');readMenu();
    return;
  }
  if(entry?.room){
    const r=entry.room;
    if(r.action==='resume')openRoom(r.id);
    else{
      target={id:r.id,host_name:r.title,count:r.players,config:r.config};
      inviteCode='';change('preview');readMenu();
    }
    return;
  }
  const param=telegramStartParam(),linked=/^nora_d_([\w-]{22})$/.exec(param);
  const invited=durakInboxRoom||/^nora_i_([a-f0-9]{16})$/.exec(param)?.[1];
  durakInboxRoom=null;
  const rid=stored('room');
  if(invited&&!(rid===invited&&stored('param')===param)){
    change('mine');readMenu().then(()=>{
      if(!host||mode!=='mine'||!list)return;
      if(list.mine.some(r=>r.id===invited)){store('param',param);openRoom(invited);return}
      target=list.invites.find(r=>r.id===invited);
      if(target){activeParam=param;inviteCode='';change('preview')}else errorText(Error('Приглашение больше не действует'));
    });
  }else if(linked&&param!==activeParam&&stored('param')!==param){
    activeParam=param;paint();
    readMenu().then(()=>{if(host&&mode==='open')previewCode(linked[1])});
  }else if(rid&&/^[\da-f]{16}$/.test(rid))openRoom(rid);
  else{paint();readMenu()}
}
function unmount(){
  if(!host)return;
  stopNetwork();
  if(drag){const gesture=drag;release(gesture);gesture.el.remove()}
  landing.forEach(el=>el.remove());landing.clear();
  document.removeEventListener('visibilitychange',visibility);
  document.body.classList.remove('dk-playing');host=null;
}
window.NoraDurak={mount,unmount,back};
export {mount};
