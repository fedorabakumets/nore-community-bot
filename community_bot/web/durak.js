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
let clockDeadline=0, menuRequest=0, activeParam='';
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
function header(title,backText='Дурак'){
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
function menuScreen(){
  const mine=mode==='mine';
  const items=mine?list?.mine:list?.open;
  const quick=mine?null:list?.open.filter(r=>!why(r.config)).sort((a,b)=>
    a.config.stake-b.config.stake||(a.config.players-a.count)-(b.config.players-b.count))[0];
  return `${header('Дурак','Игры')}<div class="dk-cover">
      <div><span class="dk-caption">Карточный стол</span><strong>Сыграем?</strong>
      <small>${list?`В кошельке ${chips(list.balance)}`:'Загружаем кошелёк…'}</small></div>
      <span class="dk-cover-fan" aria-hidden="true">${[43,46,51].map(c=>cardImg(c)).join('')}</span></div>
    <div class="dk-tools">${actionButton('create-form','Создать стол','dk-primary')}${actionButton('code-form','Приватные игры')}</div>
    <div class="dk-tabs" aria-label="Список игр">${actionButton('open','Открытые игры','',`aria-pressed="${!mine}"`)}
    ${actionButton('mine',`Мои игры${list?.invites.length?' · '+list.invites.length:''}`,'',`aria-pressed="${mine}"`)}</div>
    ${mine&&list?.invites.length?`<h2>Приглашения</h2>${list.invites.map(r=>row(r,'invite')).join('')}`:''}
    ${!mine&&list?.active?`${actionButton('current','Вернуться за свой стол','dk-current')}`:''}
    ${quick?actionButton('quick',`Быстрый вход за ${chips(quick.config.stake)}<small>${esc(blurb(quick.config))} · ${quick.count}/${quick.config.players}</small>`,'dk-current',`data-id="${quick.id}"`):''}
    <div class="dk-rooms">${items?.length?items.map(r=>row(r,mine?'mine':'open')).join(''):
      `<p class="dk-empty">${!list?'Ищем столы…':mine?'Здесь появятся твои партии.':'Свободных столов пока нет. Можно создать свой.'}</p>`}</div>
    ${!mine&&list?.next?actionButton('more','Ещё столы'):''}`;
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
function seatPosition(index,total){
  // Adapted from Duren Board.seatPosition. Reserve the lower edge for the viewer's hand.
  const angle=(-90+(index+1)*360/total)*Math.PI/180;
  return `--x:${50+38*Math.cos(angle)}%;--y:${45-31*Math.sin(angle)}%`;
}
function seatLabel(g,seat){
  if(g.forfeit.includes(seat))return 'Сдался';
  if(g.out.includes(seat))return 'Вышел';
  if(seat===g.defender)return 'Защита';
  if(seat===g.attacker)return 'Атака';
  return 'За столом';
}
function turnText(g){
  if(g.phase==='review')return 'Проверка карт';
  if(g.turn===room.own)return {attack:'Твой ход',defend:'Твоя защита',throw:g.taking?'Подкинь или спасуй':'Подкинь или заверши'}[g.phase];
  return `${g.taking?'Забирает · ':g.phase==='defend'?'Отбивается · ':'Ходит · '}${nameAt(g.turn)}`;
}
function groupCandidates(g,first){
  if(!g.moves.some(m=>m.kind==='attack'&&m.card===first)||g.capacity-g.table.length<2)return [];
  const open=g.table.length===0;
  return g.moves.filter(m=>m.kind==='attack'&&(!open||(m.card>>2)===(first>>2))).map(m=>m.card);
}
function controls(g){
  if(challenge)return `<div class="dk-checks" aria-label="Выбери карту для проверки">${g.challenge.map(c=>
    actionButton('report',faceName(c),'dk-secondary',`data-card="${c}" aria-label="Оспорить ${faceName(c)}"`)).join('')}</div>`+
    actionButton('challenge-mode','Отмена');
  if(batch)return actionButton('attack-group',`Сыграть ×${batch.length}`,'dk-primary',batch.length<2?'disabled':'')+
    actionButton('batch-cancel','Отмена');
  const picked=g.moves.filter(m=>m.card===selected);
  const buttons=[];
  if(picked.some(m=>m.kind==='attack'))buttons.push(actionButton('attack',g.table.length?'Подкинуть':'Походить','dk-primary'));
  if(groupCandidates(g,selected).length>1)buttons.push(actionButton('batch','Несколько карт'));
  if(picked.some(m=>m.kind==='transfer'))buttons.push(actionButton('transfer','Перевести','dk-secondary'));
  const cover=picked.filter(m=>m.kind==='defend');
  if(cover.length===1)buttons.push(actionButton('defend','Отбить','dk-primary',`data-slot="${cover[0].slot}"`));
  if(cover.length>1)buttons.push('<span class="dk-muted">Выбери карту на столе</span>');
  if(g.moves.some(m=>m.kind==='take'))buttons.push(actionButton('take','Беру','dk-secondary'));
  if(g.moves.some(m=>m.kind==='pass'))buttons.push(actionButton('pass',g.taking?'Пас':'Бито','dk-secondary'));
  if(g.challenge.length)buttons.push(actionButton('challenge-mode',challenge?'Отмена проверки':'Оспорить','dk-secondary',`aria-pressed="${challenge}"`));
  if(!buttons.length)buttons.push(`<span class="dk-muted">${g.moves.length?'Выбери карту в руке':'Ожидаем ход'}</span>`);
  return buttons.join('');
}
function gameScreen(){
  const g=room.game,c=room.config;
  const n=room.members.length,others=[...room.members.slice(room.own+1),...room.members.slice(0,room.own)];
  const ownHand=[...g.hand].sort((a,b)=>((a%4===g.trump)-(b%4===g.trump))||a%4-b%4||a-b);
  const cardMoves=new Set(batch?groupCandidates(g,batch[0]):g.moves.map(m=>m.card));
  const targetable=new Set(g.moves.filter(m=>m.kind==='defend'&&m.card===selected).map(m=>m.slot));
  return `<header class="dk-gamehead">${actionButton('back','← Столы','dk-back')}<strong>${labels.variant[c.variant]}</strong><span>${chips(c.stake)}</span>
    ${actionButton('game-info','Правила','dk-text')}</header>
    <div class="dk-felt"><div class="dk-ring" aria-hidden="true"></div>
    ${others.map((m,i)=>`<div class="dk-chair ${g.turn===m.seat?'is-turn':''}" data-seat="${m.seat}" style="${seatPosition(i,n)}">
      ${portrait(m)}<span><strong>${esc(m.name)}</strong><small>${g.counts[m.seat]} карт · ${seatLabel(g,m.seat)}</small></span>${g.marked.includes(m.seat)?'<i title="Уличён в шулерстве">!</i>':''}</div>`).join('')}
    <div class="dk-stock" data-origin="deck" aria-label="В колоде ${g.stock}, козырь ${suits[g.trump]}">
      ${g.bottom!==null?`<img class="dk-trump" src="${face(g.bottom)}" alt="Козырь ${faceName(g.bottom)}">`:''}
      <span class="dk-backcard">${g.stock||suits[g.trump]}</span>${g.bottom!==null?`<b class="dk-trump-name">${faceName(g.bottom)}</b>`:''}</div>
    <div class="dk-pairs" data-origin="table" data-slots="${g.table.length}">${g.table.length?g.table.map(([a,d],i)=>
      `<div class="dk-pair ${targetable.has(i)?'can-cover':''}" data-slot="${i}">${[a,d].map((card,j)=>card===null?'':`<button type="button" class="dk-tablecard ${j?'cover':''} ${challenge&&g.challenge.includes(card)?'can-check':''}" data-on-table="${card}" aria-label="${faceName(card)}">${cardImg(card)}</button>`).join('')}</div>`).join(''):
      '<span class="dk-felt-mark" aria-hidden="true">♠</span>'}</div>
    <div class="dk-discard" data-origin="discard">Отбой <b>${g.discard}</b></div></div>
    <div class="dk-turn"><span aria-live="polite"><small>Заход ${g.round} · козырь ${suits[g.trump]}</small><strong>${esc(turnText(g))}</strong></span><time id="dk-clock" aria-live="off"></time></div>
    <div class="dk-hand" data-seat="${room.own}" aria-label="Твои карты">${ownHand.map(card=>
      `<button type="button" data-hand="${card}" class="dk-handcard ${cardMoves.has(card)?'legal':''}" aria-pressed="${batch?batch.includes(card):selected===card}" aria-label="${faceName(card)}">${cardImg(card)}</button>`).join('')}</div>
    <div class="dk-actions">${controls(g)}</div>`;
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
function paint(){
  if(!host?.isConnected)return;
  const playing=mode==='room'&&room?.status==='playing';
  document.body.classList.toggle('dk-playing',playing);
  host.className='dk-root'+(playing?' dk-game':'');
  host.setAttribute('aria-live',playing?'off':'polite');
  host.dataset.revision=room?String(room.rev):'';
  host.dataset.mode=mode;
  const prev=host.querySelector('.dk-hand')?.scrollLeft||0;
  let html;
  if(mode==='open'||mode==='mine')html=menuScreen();
  if(mode==='create')html=createScreen();
  if(mode==='code')html=privateScreen();
  if(mode==='preview'&&target)html=confirmJoin();
  if(mode==='friends'&&room)html=friendScreen();
  if(mode==='room'&&room)html=room.status==='playing'?gameScreen():room.status==='waiting'?waiting():resultScreen();
  host.innerHTML=(html||`${header('Карточный стол')}<p class="dk-muted">Загружаем стол…</p>`)+
    `<p class="dk-error" role="status">${esc(message)}</p>`;
  const hand=host.querySelector('.dk-hand');
  if(hand)hand.scrollLeft=prev;
  if(playing)clockTick();
}
function clockTick(){
  const el=host?.querySelector('#dk-clock');
  if(!el)return;
  const left=Math.max(0,Math.ceil(clockDeadline-performance.now()/1000));
  if(el.textContent!==left+' с')el.textContent=left+' с';
  el.classList.toggle('urgent',left<=5);
}
function stopNetwork(){
  generation++;watch?.abort();watch=null;clearTimeout(refreshTimer);clearInterval(timer);menuRequest++;
}
function change(next){
  stopNetwork();mode=next;message='';selected=null;challenge=false;batch=null;
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
  if(gen===generation&&seq===menuRequest&&['open','mine'].includes(mode)&&!document.hidden){
    clearTimeout(refreshTimer);refreshTimer=setTimeout(()=>readMenu(),12000);
  }
}
function flash(event){
  if(!host||!room)return;
  const text=event.kind==='challenge'?`${nameAt(event.marked)} уличён в шулерстве`:
    event.kind==='transfer'?`Переводит ${nameAt(event.seat)}`:
    ['surrender','timeout'].includes(event.kind)?`${nameAt(event.seat)} ${event.kind==='timeout'?'пропустил ход':'сдался'}`:'';
  if(text)toast(text);
}
function positions(){
  const map=new Map();
  host?.querySelectorAll('[data-seat],[data-origin],[data-on-table],[data-hand]').forEach(el=>{
    for(const name of ['seat','origin','onTable','hand'])if(el.dataset[name]!==undefined){
      const b=el.getBoundingClientRect();
      map.set(name+el.dataset[name],{x:b.left+b.width/2,y:b.top+b.height/2});
    }
  });
  return map;
}
function motion(frames,before){
  if(!frames.length||!host)return;
  const after=positions(),events=frames.flatMap(f=>f.events);
  events.forEach(flash);
  if(matchMedia('(prefers-reduced-motion: reduce)').matches||!host.classList.contains('dk-game'))return;
  host.querySelectorAll('.dk-flight').forEach(el=>el.remove());
  const point=k=>after.get(k)||before.get(k);
  const flight=(a,b,card,delay=0)=>{
    if(!a||!b)return;
    const el=document.createElement('i');el.className='dk-flight';
    if(card!==null)el.style.backgroundImage=`url("${face(card)}")`;
    el.style.left=a.x+'px';el.style.top=a.y+'px';host.append(el);
    const animation=el.animate([{transform:'translate(-50%,-50%) rotate(-8deg) scale(.72)',opacity:0},
      {opacity:1,offset:.18},{transform:`translate(calc(-50% + ${b.x-a.x}px),calc(-50% + ${b.y-a.y}px)) rotate(2deg) scale(.92)`,opacity:.22}],
      {duration:260,delay:Math.min(delay,550),easing:'cubic-bezier(.22,.7,.28,1)',fill:'backwards'});
    animation.onfinish=animation.oncancel=()=>el.remove();
  };
  for(const e of events){
    const seat='seat'+e.seat, desk=point('origintable'), stock=point('origindeck');
    if(e.kind==='deal'){
      host.querySelector('.dk-stock')?.animate([{transform:'rotate(-12deg)'},{transform:'rotate(9deg)'},{transform:'none'}],{duration:260});
      host.querySelector('.dk-trump')?.animate([{opacity:0},{opacity:1}],{duration:450});
      for(let k=0;k<6;k++)room.members.forEach(m=>flight(stock,point('seat'+m.seat),null,30*k+16*m.seat));
    }else if(['attack','defend','transfer'].includes(e.kind)){
      flight(before.get('hand'+e.card)||point(seat),point('onTable'+e.card)||desk,e.card);
    }else if(['collect','discard'].includes(e.kind)){
      e.cards.forEach((c,i)=>flight(before.get('onTable'+c)||desk,e.kind==='collect'?point(seat):point('origindiscard'),c,35+i*8));
    }else if(e.kind==='draw'){
      for(let i=0;i<e.count;i++)flight(stock,point(seat),null,140+i*25);
    }
  }
}
function accept(view,old){
  if(!view||view.unchanged)return;
  if(room?.id===view.id&&view.rev<room.rev)return;
  const first=!room||room.id!==view.id,changed=first||room.rev!==view.rev;
  if(!changed)return;
  const was=room?.status,previousRound=room?.game?.round,prev=positions();
  room=view;clockDeadline=performance.now()/1000+Math.max(0,view.deadline-view.now);
  batch=null;
  if(mode==='friends'&&room.status!=='waiting')mode='room';
  if(!room.game?.hand.includes(selected))selected=null;
  challenge=challenge&&Boolean(room.game?.challenge.length);
  message='';paint();
  const frames=view.frames.filter(f=>f.rev>old);
  if(!frames.length&&room.status==='playing'&&(was==='waiting'||(first&&room.game.events.some(e=>e.kind==='deal')))){
    frames.push({events:[{kind:'deal'}]});
  }
  motion(frames,prev);
  if(previousRound&&room.game?.round>previousRound&&!matchMedia('(prefers-reduced-motion: reduce)').matches){
    host.querySelector('.dk-turn')?.animate([{opacity:.45,transform:'translateY(3px)'},{opacity:1,transform:'none'}],{duration:200});
  }
  if(!['playing','waiting'].includes(room.status))clearInterval(timer);
}
async function syncLoop(id,gen){
  let failures=0;
  while(gen===generation&&!document.hidden&&host&&['room','friends'].includes(mode)){
    const previous=room?.id===id?room.rev:-1;
    const controller=new AbortController();watch=controller;
    try{
      const view=await api('durak/room/'+id+(previous>=0?'?after='+previous:''),null,controller.signal);
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
  if(!same)room=null;
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
  const gen=generation;
  const payload={action,...fields};
  const serialized=JSON.stringify(payload);
  let saved;
  try{saved=JSON.parse(stored('pending')||'null')}catch{}
  const nonce=saved?.serialized===serialized?saved.nonce:
    Array.from(crypto.getRandomValues(new Uint8Array(16)),b=>b.toString(16).padStart(2,'0')).join('');
  store('pending',JSON.stringify({serialized,nonce}));
  try{
    const reply=await api('durak/action',{...payload,nonce});
    store('pending',null);
    if(gen===generation&&host)await after(reply.id);
  }catch(err){
    if(gen===generation&&host){if(room&&['room','friends'].includes(mode))await freshRoom(room.id).catch(()=>{});errorText(err)}
  }finally{pending=false}
}
function move(kind,slot){
  const candidate=room?.game?.moves.find(m=>m.kind===kind&&(m.card===undefined||m.card===selected)&&(slot===undefined||slot===m.slot));
  if(candidate)send('move',{room:room.id,rev:room.rev,move:candidate},()=>{selected=null;challenge=false;return freshRoom(room.id)});
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
  if(mode==='friends'&&room){openRoom(room.id);return true}
  if(!['open','mine'].includes(mode)){change('open');readMenu();return true}
  return false;
}
function pick(card){
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
  selected=selected===card?null:card;challenge=false;paint();
}
function playOn(card,slot){
  if(challenge&&room.game.challenge.includes(card)){
    send('move',{room:room.id,rev:room.rev,move:{kind:'challenge',card}},()=>{challenge=false;return freshRoom(room.id)});
  }else if(selected!==null)move('defend',slot);
}
function click(e){
  if(drag?.suppress){drag=null;return}
  const b=e.target.closest('button');
  if(!b||!host.contains(b)||b.disabled)return;
  if(b.dataset.option){
    const name=b.dataset.option;config[name]=['players','deck'].includes(name)?Number(b.dataset.value):b.dataset.value;
    paint();return;
  }
  if(b.hasAttribute('data-hand')){pick(Number(b.dataset.hand));return}
  if(b.hasAttribute('data-on-table')){playOn(Number(b.dataset.onTable),Number(b.closest('[data-slot]').dataset.slot));return}
  const act=b.dataset.dk;
  switch(act){
    case 'open':case 'mine':change(act);readMenu();break;
    case 'more':readMenu(true);break;
    case 'back':back();break;
    case 'create-form':case 'new-private':config={...initial,private:act==='new-private'};change('create');readMenu();break;
    case 'again':config={...room.config};room=null;change('create');readMenu();break;
    case 'create':send('create',{config:{...config}},id=>{room=null;openRoom(id)});break;
    case 'current':if(list?.active)openRoom(list.active);break;
    case 'quick':send('join',{room:b.dataset.id},id=>{room=null;openRoom(id)});break;
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
    case 'game-info':{
      const canLeave=!room.game.out.includes(room.own)&&!room.game.forfeit.includes(room.own);
      sheet(`<h2>Твой стол</h2>${settingsLine(room.config)}${rulesInfo(room.config)}${canLeave?'<button class="secondary" id="dk-surrender">Сдаться</button>':''}`);
      const quit=document.getElementById('dk-surrender');
      if(quit)quit.onclick=()=>{document.getElementById('sheet').close();confirmLeave()};break;
    }
    case 'challenge-mode':challenge=!challenge;selected=null;paint();break;
    case 'report':playOn(Number(b.dataset.card));break;
    case 'batch':batch=[selected];paint();break;
    case 'batch-cancel':batch=null;selected=null;paint();break;
    case 'attack-group':
      if(batch?.length>1)send('move',{room:room.id,rev:room.rev,move:{kind:'attack_many',cards:[...batch]}},()=>freshRoom(room.id));
      break;
    case 'attack':case 'take':case 'pass':case 'transfer':move(act);break;
    case 'defend':move('defend',Number(b.dataset.slot));break;
  }
}
function input(e){
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
function down(e){
  const b=e.target.closest('[data-hand]');
  if(b&&!batch&&e.isPrimary&&e.button===0)drag={id:e.pointerId,c:Number(b.dataset.hand),x:e.clientX,y:e.clientY};
}
function pointer(e){
  if(!drag||e.pointerId!==drag.id||drag.suppress)return;
  const dx=e.clientX-drag.x,dy=e.clientY-drag.y;
  const sideTray=matchMedia('(orientation:landscape) and (max-height:560px)').matches;
  const toward=sideTray?-dx:-dy,across=sideTray?Math.abs(dy):Math.abs(dx);
  if(!drag.el&&(toward<9||toward<across))return;
  if(!drag.el){
    drag.el=document.createElement('i');drag.el.className='dk-flight dk-drag';
    drag.el.style.backgroundImage=`url("${face(drag.c)}")`;host.append(drag.el);
    host.setPointerCapture?.(e.pointerId);
  }
  drag.el.style.left=e.clientX+'px';drag.el.style.top=e.clientY+'px';
}
function up(e){
  if(!drag||e.pointerId!==drag.id)return;
  if(!drag.el||e.type==='pointercancel'){drag.el?.remove();drag=null;return}
  drag.el.remove();
  const hit=document.elementFromPoint(e.clientX,e.clientY);
  selected=drag.c;drag={suppress:true};setTimeout(()=>{if(drag?.suppress)drag=null},100);
  if(!hit?.closest('.dk-felt')){paint();return}
  const slot=hit.closest('[data-slot]');
  if(slot)move('defend',Number(slot.dataset.slot));
  else if(room.game.moves.some(m=>m.card===selected&&m.kind==='attack'))move('attack');
  else if(room.game.moves.some(m=>m.card===selected&&m.kind==='transfer'))move('transfer');
  paint();
}
function visibility(){
  if(!host)return;
  stopNetwork();
  if(document.hidden)return;
  if(room&&['room','friends'].includes(mode)){openRoom(room.id,mode==='friends')}
  else if(['open','mine','create','preview'].includes(mode))readMenu();
}
function mount(root){
  if(!root||host===root)return;
  host=root;mode='open';list=null;room=null;friends=null;message='';
  for(const [type,fn] of Object.entries({click,input,submit,pointerdown:down,pointermove:pointer,pointerup:up,pointercancel:up}))host.addEventListener(type,fn);
  document.addEventListener('visibilitychange',visibility);
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
  stopNetwork();drag?.el?.remove();drag=null;
  document.removeEventListener('visibilitychange',visibility);
  document.body.classList.remove('dk-playing');host=null;
}
window.NoraDurak={mount,unmount,back};
export {mount};
