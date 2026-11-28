/* Local, isolated DICE admin alpha. No real cookies or network match results. */
(function(){
"use strict";
const C=window.NoraDiceCore,D=C.dice,rar=["Обычный","Редкий","Уникальный","Легендарный"],rarColor=["#b7c5df","#78dfff","#c4a0ff","#ffce87"];
const presets=[[0,1,2,3,4],[0,8,9,10,11],[1,6,7,12,13],[8,9,11,14,17],[4,9,10,15,16]],pn=["Старт","Слияния","Экономика","Гармония","Атака"];

/* Card demonstrations use the same simulation and merge rules as the match.
   Scripted setups, durable targets and a shortened Growth timer are preview-only. */
const previewNames=[
"Скорострельность","Взрыв по области","Накопление льда","Цепная молния","Удар по сильнейшему","Периодический урон",
"Критический резонанс","Ускорение союзников","Автоматический рост","Копирование","Свободное слияние","Усиление без смены типа",
"Генерация SP","Дополнительный призыв","Обмен клеток","Атака поля соперника","Нарастающий урон","Гармония линий"];
function previewScenario(i,rank){
  const pool=[...new Set([0,i,1,2,3,4])].slice(0,5);
  const g=C.create(pool,i===15?"duel":"training",()=>0.001),p=g.you;
  const s={g,p,i,rank,t:0,acted:false,fx:[],status:"",duration:5.4};
  p.spawn=Infinity;if(g.opp)g.opp.spawn=Infinity;
  const add=(id,n,k)=>C.add(g,p,id,n,k);
  const target=(pos,h,boss=false)=>{const e=C.spawn(g,p,boss);e.pos=pos;e.h=e.max=h;e.skill=Infinity;return e};
  if(i<=5){
    add(i,rank,7);
    if(i===4){target(35,380);target(75,20000,true);target(105,380)}
    else if(i===2||i===5){target(55,20000);if(i===5)target(105,10000)}
    else{target(55,4000);target(72,4000);target(89,4000)}
  }else if(i===6||i===7){
    add(i,rank,6);add(0,rank,7);add(0,rank,11);target(48,20000);target(95,20000);
  }else if(i===8){
    add(i,rank,7);if(rank<7)p.board[7].grow=2.1;
  }else if(i===17){
    for(const k of [2,5,6,7,8,9])add(17,k===7?rank:1,k);
    target(45,20000);
  }else{
    add(i,rank,6);add([12,13,15,16].includes(i)?i:0,rank,8);
    if(i===15)C.add(g,g.opp,2,3,7);
    if(i===16)add(16,rank,11);
  }
  g.events.length=0;
  return s;
}
function previewStep(s,dt){
  const {g,p,i,rank}=s;s.t+=dt;
  const special=i>=9&&i<=16;
  if(special){
    if(!s.acted&&s.t>=1.8){
      s.acted=true;s.merged=C.merge(g,p,6,8);
    }
  }else{
    if(i===17&&!s.acted&&s.t>=1.8){s.acted=true;C.add(g,p,17,1,12)}
    C.tick(g,dt);
  }
  for(const e of g.events.splice(0)){
    if(!["hit","arc","summon","merge","assassin","kill"].includes(e.kind))continue;
    const xy=e.k>=0?C.pos(e.k):[e.x,e.y];
    if(!Number.isFinite(xy[0])||!Number.isFinite(xy[1]))continue;
    s.fx.push({kind:e.kind,x:xy[0],y:xy[1],a:e.a,b:e.b,i:e.i??i,enemy:e.p!==p,life:.45,max:.45});
  }
  s.fx=s.fx.filter(f=>(f.life-=dt)>0).slice(-90);
  return s;
}
function previewStatus(s){
  const {i,rank,p,g,acted,t}=s;
  if(i===0)return rank+" точ. · "+(D[0].interval/rank).toFixed(2)+" с между атаками";
  if(i===1)return "Цель + 70% урона ближайшим противникам";
  if(i===2){const n=Math.max(0,...p.enemies.map(e=>e.ice));return "Обледенение "+n+"/3 · замедление "+(n*8)+"%"}
  if(i===3)return "До 3 целей · 100% → 70% → 30%";
  if(i===4)return "Выбор цели с максимальным HP · ×2 против босса";
  if(i===5)return p.enemies.some(e=>e.poison>0)?"Яд активен · 13 урона/с · 4 с":"Случайная цель · наложение яда";
  if(i===6)return "Соседи: +"+(2.5*rank).toLocaleString("ru-RU")+" п.п. к шансу крита";
  if(i===7)return "Соседи: +"+(7*rank)+"% к скорости атаки";
  if(i===8)return rank===7?"7 точек · рост завершён":p.board[7]?.p>rank?"Результат: случайный тип · +1 точка":"Рост через 14 с · время в превью ускорено";
  if(i===17)return acted?"Гармония: пересечение двух линий · ×5 урон":"Заполнена горизонтальная линия · ×2 урон";
  if(!acted)return "Перетащить на кубик с таким же числом точек";
  if(!s.merged)return "7 точек · дальнейшее слияние недоступно";
  if(i===9)return "Копия создана · оба кубика сохранены";
  if(i===10)return "Случайный кубик · +1 точка";
  if(i===11)return "Тип цели сохранён · +1 точка";
  if(i===12)return "+"+(80*rank)+" SP";
  if(i===13)return "Дополнительный случайный кубик · бесплатно";
  if(i===14)return "Кубики поменялись местами";
  if(i===15)return "Кубик соперника потерял одну точку";
  if(i===16)return "COMBO "+p.combo+" · +"+(p.combo*7)+" урона всем COMBO";
  return "";
}
function previewDraw(ctx,s){
  const {i,rank,g,p,t}=s,c=D[i].color;
  const W=360,H=222;ctx.setTransform(2,0,0,2,0,0);ctx.fillStyle="#090b12";ctx.fillRect(0,0,W,H);
  function rr(x,y,w,h,r,f,stroke){ctx.beginPath();if(ctx.roundRect)ctx.roundRect(x,y,w,h,r);else ctx.rect(x,y,w,h);if(f){ctx.fillStyle=f;ctx.fill()}if(stroke){ctx.strokeStyle=stroke;ctx.lineWidth=.9;ctx.stroke()}}
  function dot(x,y,r,col){ctx.beginPath();ctx.arc(x,y,Math.max(.01,r),0,Math.PI*2);ctx.fillStyle=col;ctx.fill()}
  function ring(x,y,r,col,w=1){ctx.beginPath();ctx.arc(x,y,r,0,Math.PI*2);ctx.strokeStyle=col;ctx.lineWidth=w;ctx.stroke()}
  function label(str,x,y,col="#b5bbcc",size=10){ctx.font="600 "+size+"px system-ui,sans-serif";ctx.textAlign="center";ctx.fillStyle=col;ctx.fillText(str,x,y)}
  function line(x,y,a,b,col,w=1){ctx.beginPath();ctx.moveTo(x,y);ctx.lineTo(a,b);ctx.strokeStyle=col;ctx.lineWidth=w;ctx.stroke()}
  function lightning(x,y,a,b,col){ctx.beginPath();ctx.moveTo(x,y);for(let k=1;k<6;k++){const f=k/6;ctx.lineTo(x+(a-x)*f+Math.sin(k*17+t*35)*3,y+(b-y)*f+Math.cos(k*13+t*29)*5)}ctx.lineTo(a,b);ctx.strokeStyle=col+"44";ctx.lineWidth=5;ctx.stroke();ctx.strokeStyle=col;ctx.lineWidth=1.5;ctx.stroke()}
  function die(u,x,y,alpha=1){const col=D[u.i].color;ctx.save();ctx.globalAlpha=alpha;rr(x-22,y-21,44,42,10,"#151824",col+"b0");rr(x-18,y-17,36,34,7,col+"1e","#ffffff1f");
    for(const [a,b] of C.pips[u.p]){dot(x+a*10,y-2+b*9,5.4,col+"22");dot(x+a*10,y-2+b*9,3.7,col);dot(x+a*10-.8,y-3+b*9,1.3,"#fff")}
    label(D[u.i].name==="SUPPLEMENT"?"SUPPL.":D[u.i].name,x,y+15,col,6.5);ctx.restore()}
  for(let k=0;k<35;k++)dot((k*97.3)%W,(k*63.7)%H,.5,"#9aaed525");
  const combat=i<=7||i===17;
  if(combat){
    line(18,29,342,29,"#ffffff1c",11);line(342,29,342,195,"#ffffff16",11);
    for(const e of p.enemies){const [x,y]=C.path(e.pos),r=e.boss?10:5.5,col=e.poison>0?"#92e47e":e.ice?"#75dfff":"#d6ddef";
      if(e.poison>0)ring(x,y,r+5,col+"77",2);
      ctx.save();ctx.translate(x,y);ctx.rotate(t*.4);rr(-r,-r,r*2,r*2,2,e.flash>0?"#fff":col+"30",col);ctx.restore();
      rr(x-10,y-r-6,20,2,1,"#ffffff20");rr(x-10,y-r-6,20*Math.max(0,e.h/e.max),2,1,col);
      for(let j=0;j<e.ice;j++)dot(x+Math.cos(j*2.094)*8,y+Math.sin(j*2.094)*8,2.5,"#9de8ff");
      if(e.boss)label("MAX HP",x,y+23,col,8);
    }
  }
  for(let k=0;k<15;k++){const [x,y]=C.pos(k);rr(x-24,y-22,48,43,10,"#ffffff03","#ffffff12")}
  if(i===6||i===7){
    const [x,y]=C.pos(6);for(const k of [7,11]){const[a,b]=C.pos(k);line(x,y,a,b,c+"80",2);ring(a,b,24,c+"50",1.5)}
    ring(x,y,26,c+"55",1.6);
  }
  if(i===17){
    line(72,108,288,108,c+"40",7);if(s.acted)line(180,63,180,153,c+"60",7);
  }
  const dragging=i>=9&&i<=16&&rank<7||[9,14].includes(i);
  const move=dragging&&!s.acted?Math.max(0,Math.min(1,(t-.65)/1.15)):0;
  for(let k=0;k<15;k++){
    const u=p.board[k];if(!u)continue;const[x,y]=C.pos(k);
    if(k===6&&move>0){const[a,b]=C.pos(8);die(u,x+(a-x)*move,y+(b-y)*move,.86)}
    else die(u,x,y);
    if(i===8&&u.i===8&&u.p<7){rr(x-19,y+24,38,3,1,"#ffffff15");rr(x-19,y+24,38*Math.max(0,1-u.grow/2.1),3,1,c)}
  }
  if(i>=9&&i<=16&&!s.acted){const [x,y]=C.pos(6),[a,b]=C.pos(8);if(dragging){line(x+25,y,a-25,b,c+"99",1.5);line(a-31,b-4,a-25,b,c,1.5);line(a-31,b+4,a-25,b,c,1.5)}}
  if(i===15){const u=g.opp.board[7];label("ПОЛЕ СОПЕРНИКА",180,188,"#ff8fa9",9);if(u)die(u,180,207);else label("−1 точка",180,210,"#ff8fa9")}
  for(const shot of g.shots){const col=D[shot.i].color,x=shot.x,y=shot.y;
    if(shot.i===3){lightning(shot.sx,shot.sy,x,y,col);continue}
    ctx.save();ctx.translate(x,y);ctx.rotate(shot.angle);
    if(shot.i===0){rr(-8,-1,13,2,1,col);dot(4,0,1.5,"#fff")}
    else if(shot.i===1){dot(0,0,9,col+"25");dot(0,0,5,col);dot(1,-1,2.6,"#ffdfa7")}
    else if(shot.i===2){ctx.beginPath();ctx.moveTo(7,0);ctx.lineTo(-5,-3);ctx.lineTo(-1,0);ctx.lineTo(-5,3);ctx.closePath();ctx.fillStyle=col;ctx.fill()}
    else if(shot.i===4)rr(-4,-3,8,6,1,col,"#fff");
    else{dot(0,0,5,col+"35");dot(0,0,3,col)}
    ctx.restore();
  }
  for(const f of s.fx){const col=D[f.i]?.color||c,q=1-f.life/f.max;ctx.globalAlpha=1-q;
    if(f.kind==="arc")lightning(f.x,f.y,f.a,f.b,col);
    else if(f.enemy&&i===15)ring(180,207,12+16*q,"#ff557c",2);
    else{ring(f.x,f.y,4+(f.i===1?35:19)*q,col,1.8);if(f.i===1&&f.kind==="hit")dot(f.x,f.y,6+20*q,col+"40")}
    ctx.globalAlpha=1;
  }
  if(i===12&&s.acted&&s.merged)label("+"+80*rank+" SP",180,65,c,18);
  if(i===16&&s.acted&&s.merged)label("COMBO "+p.combo,180,55,c,16);
}
function mountPreview(panel,i,rank){
  const canvas=panel.querySelector("canvas"),ctx=canvas?.getContext("2d");if(!ctx)return ()=>{};
  const status=panel.querySelector("[data-preview-status]"),toggle=panel.querySelector("[data-preview-toggle]"),replay=panel.querySelector("[data-preview-replay]");
  let s=previewScenario(i,rank),raf=0,last=0,visible=true,disposed=false,playing=!window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches;
  function paint(){previewDraw(ctx,s);const next=previewStatus(s);if(status.textContent!==next)status.textContent=next}
  function syncButton(){toggle.textContent=playing?"Ⅱ":"▶";toggle.setAttribute("aria-label",playing?"Приостановить демонстрацию":"Воспроизвести демонстрацию");toggle.setAttribute("aria-pressed",String(!playing))}
  function frame(now){
    raf=0;if(disposed||!panel.isConnected||!playing||!visible||document.hidden)return;
    if(last&&now-last<30){raf=requestAnimationFrame(frame);return}
    const dt=last?Math.min(.075,(now-last)/1000):0;last=now;
    if(s.t>=s.duration)s=previewScenario(i,rank);
    const steps=Math.max(1,Math.ceil(dt*60));for(let j=0;j<steps;j++)previewStep(s,dt/steps);
    paint();raf=requestAnimationFrame(frame);
  }
  function sync(){cancelAnimationFrame(raf);raf=0;last=0;if(!disposed&&playing&&visible&&!document.hidden)raf=requestAnimationFrame(frame)}
  function onToggle(){playing=!playing;syncButton();sync()}
  function onReplay(){s=previewScenario(i,rank);playing=true;paint();syncButton();sync()}
  toggle.addEventListener("click",onToggle);replay.addEventListener("click",onReplay);
  const observer=typeof IntersectionObserver==="function"?new IntersectionObserver(entries=>{visible=entries[0]?.isIntersecting!==false;sync()},{threshold:.01}):null;
  observer?.observe(panel);document.addEventListener("visibilitychange",sync);
  paint();syncButton();sync();
  return ()=>{disposed=true;cancelAnimationFrame(raf);observer?.disconnect();document.removeEventListener("visibilitychange",sync);toggle.removeEventListener("click",onToggle);replay.removeEventListener("click",onReplay)};
}

let active=null;
function mount(host,{api,exit,tg}){
if(active?.host===host)return;
unmount();
const state={host,dead:false,raf:0,ac:null,master:null,game:null,fx:[],trail:new Map(),last:0,selected:-1,drag:-1,point:null,tab:"arena",mode:"training",deck:presets[0].slice(),slot:-1,detail:-1,rank:1,gold:1800,levels:D.map(()=>0),copies:D.map(()=>2),sound:true,volume:.4,paused:false,speed:1,lab:false,notice:""};
active=state;
const $=s=>host.querySelector(s), S=state;
const tap=()=>{try{tg?.HapticFeedback?.impactOccurred?.("light")}catch{}};
function audio(){
if(!S.sound)return;
try{if(!S.ac){const A=window.AudioContext||window.webkitAudioContext;if(!A)return;S.ac=new A();S.master=S.ac.createGain();S.master.gain.value=S.volume;S.master.connect(S.ac.destination)}if(S.ac.state==="suspended")S.ac.resume().catch(()=>{})}catch{}
}
const stamps={};
function tone(f,to,d,v=.07,w="sine",delay=0){if(!S.ac||!S.sound)return;try{const t=S.ac.currentTime+delay,o=S.ac.createOscillator(),a=S.ac.createGain();o.type=w;o.frequency.setValueAtTime(f,t);o.frequency.exponentialRampToValueAtTime(Math.max(20,to),t+d);a.gain.setValueAtTime(.0001,t);a.gain.exponentialRampToValueAtTime(v,t+.009);a.gain.exponentialRampToValueAtTime(.0001,t+d);o.connect(a);a.connect(S.master);o.start(t);o.stop(t+d+.02)}catch{}}
function noise(d,f,v=.05){if(!S.ac||!S.sound)return;try{const a=S.ac.createGain(),b=S.ac.createBiquadFilter(),s=S.ac.createBufferSource(),t=S.ac.currentTime;if(!S.noise){S.noise=S.ac.createBuffer(1,Math.ceil(S.ac.sampleRate*.4),S.ac.sampleRate);const ar=S.noise.getChannelData(0);for(let i=0;i<ar.length;i++)ar[i]=Math.random()*2-1}s.buffer=S.noise;b.type="bandpass";b.frequency.value=f;a.gain.setValueAtTime(v,t);a.gain.exponentialRampToValueAtTime(.0001,t+d);s.connect(b);b.connect(a);a.connect(S.master);s.start(t);s.stop(t+d)}catch{}}
function sfx(k){if(!S.ac||!S.sound)return;const t=S.ac.currentTime;if(t-(stamps[k]??-10)<.10)return;stamps[k]=t;
if(k==="wind"){noise(.07,3300,.035);tone(950,420,.08,.025)}
else if(k==="fire"){noise(.18,600,.09);tone(120,38,.2,.09,"triangle")}
else if(k==="ice"){tone(1900,880,.12,.035);noise(.08,6400,.025)}
else if(k==="electric"){noise(.12,2200,.075);tone(150,620,.075,.03,"sawtooth")}
else if(k==="iron"){tone(155,42,.18,.1,"triangle");noise(.07,1400,.035)}
else if(k==="poison"){tone(570,260,.15,.035);tone(390,700,.12,.02,"sine",.025)}
else if(k==="merge"){tone(440,740,.15,.065);tone(660,1050,.18,.04,"sine",.045);tone(880,1320,.2,.025,"sine",.09)}
else if(k==="summon"){tone(300,740,.13,.06)}
else if(k==="boss"){tone(90,38,.65,.09,"triangle")}
else if(k==="hurt"){tone(230,75,.23,.07,"triangle")}
else if(k==="power"){tone(350,700,.13,.05);tone(700,1050,.15,.03,"sine",.06)}
else tone(700,420,.065,.02)
}
let serial=0;
function art(i,n=1){const c=D[i].color,id="diceGrad"+(++serial);return '<svg viewBox="0 0 72 72" aria-hidden="true"><defs><linearGradient id="'+id+'" x1="0%" y1="0%" x2="100%" y2="100%"><stop stop-color="'+c+'" stop-opacity=".53"/><stop offset=".55" stop-color="'+c+'" stop-opacity=".07"/><stop offset="1" stop-color="'+c+'" stop-opacity=".3"/></linearGradient></defs><rect x="8" y="10" width="56" height="57" rx="13" fill="#050609" stroke="'+c+'" stroke-opacity=".25"/><rect x="8" y="5" width="56" height="56" rx="13" fill="url(#'+id+')" stroke="'+c+'" stroke-opacity=".8"/><rect x="12" y="9" width="48" height="48" rx="10" fill="none" stroke="#fff" stroke-opacity=".17"/>'+C.pips[n].map(([x,y])=>'<circle cx="'+(36+x*14)+'" cy="'+(33+y*14)+'" r="7" fill="'+c+'" opacity=".14"/><circle cx="'+(36+x*14)+'" cy="'+(33+y*14)+'" r="4.8" fill="'+c+'"/><circle cx="'+(35+x*14)+'" cy="'+(32+y*14)+'" r="1.6" fill="#fff" opacity=".8"/>').join("")+'</svg>'}
const btn=(a,label,i="",cl="dice-secondary")=>'<button type="button" class="'+cl+'" data-dice="'+a+'" data-i="'+i+'">'+label+'</button>';
function card(i,small=false){const d=D[i];return '<button type="button" data-dice="'+(small?"slot":"card")+'" data-i="'+i+'" class="dice-card '+(small?"dice-small":"")+' '+(S.slot>=0&&S.deck[S.slot]===i?"chosen":"")+'" style="--dc:'+d.color+';--edge:'+rarColor[d.rarity]+'">'+art(i)+'<b>'+d.name+'</b><small>CLASS '+(1+2*d.rarity+S.levels[i])+'</small></button>'}
function top(){return '<header class="dice-top"><div><strong>DICE<span>.</span></strong><small>ADMIN ALPHA / NORA</small></div><div>'+btn("sound",S.sound?"♪":"♪ ×")+btn("exit","×")+'</div></header>'}
function nav(){return '<nav class="dice-nav" aria-label="Разделы DICE">'+[["shop","Магазин"],["deck","Колода"],["arena","Арена"],["modes","Режимы"]].map(([a,n])=>btn("nav",n,a,"dice-tab "+(S.tab===a?"chosen":""))).join("")+'</nav>'}
function menu(){if(S.dead)return;S.previewStop?.();S.previewStop=null;cancelAnimationFrame(S.raf);S.game=null;S.fx=[];S.trail.clear();
let h="",i=S.detail;
if(i>=0){const d=D[i],level=1+2*d.rarity+S.levels[i],damage=d.damage*(1+.05*S.levels[i]);h=btn("back","‹ Коллекция")+'<div class="dice-detail" style="--dc:'+d.color+'"><small style="color:'+rarColor[d.rarity]+'">'+rar[d.rarity]+'</small><div class="dice-hero-art">'+art(i,S.rank)+'</div><h2>'+d.name+'</h2><p>'+d.ru+'</p></div><section class="dice-preview" style="--dc:'+d.color+'"><header><div><small>ДЕМОНСТРАЦИЯ</small><b>'+previewNames[i]+'</b></div><div class="dice-preview-buttons"><button type="button" class="dice-secondary" data-preview-replay aria-label="Повторить демонстрацию">↻</button><button type="button" class="dice-secondary" data-preview-toggle aria-label="Приостановить демонстрацию">Ⅱ</button></div></header><canvas width="720" height="444" aria-label="Демонстрация способности '+d.name+'"></canvas><p data-preview-status></p></section><div class="dice-stats"><div><strong>'+Math.round(damage)+'</strong><small>Урон</small></div><div><strong>'+(d.interval/S.rank).toFixed(2)+'с</strong><small>Интервал</small></div><div><strong>'+Math.round(damage*S.rank/d.interval)+'</strong><small>DPS</small></div></div><div class="dice-ranks">'+[1,2,3,4,5,6,7].map(n=>btn("rank",n,n,"dice-secondary "+(S.rank===n?"chosen":""))).join("")+'</div><article class="dice-panel"><small>СПОСОБНОСТЬ</small><p>'+d.description+'</p><small>Точки влияют на частоту атак; Power Up усиливает тип в матче.</small></article><article class="dice-panel"><small>CLASS '+level+' · Копии '+S.copies[i]+'/'+(level+1)+'</small><p>Постоянное улучшение: +5% базового урона за класс.</p>'+btn("upgrade","Улучшить · "+(100*level)+" ◈",i,"dice-primary")+'</article>'}
else if(S.tab==="deck"){h='<h2>Колода</h2><p>Пять разных кубиков.</p><div class="dice-deck">'+S.deck.map(i=>card(i,true)).join("")+'</div><small>'+ (S.slot>=0?"Выбери замену для "+D[S.deck[S.slot]].name:"Нажми на слот, затем на кубик в коллекции.")+'</small><h3>Готовые колоды</h3><div class="dice-presets">'+pn.map((n,k)=>btn("preset",n,k)).join("")+'</div><h3>Коллекция · 18/18</h3><div class="dice-collection">'+D.map(d=>card(d.id)).join("")+'</div>'}
else if(S.tab==="shop"){h='<h2>Магазин</h2><p>Тестовая валюта: '+S.gold+' ◈</p><div class="dice-panel dice-detail"><div class="dice-hero-art">'+art(9,4)+'</div><h3>ORIGIN CACHE</h3><p>12 случайных копий</p>'+btn("chest","Открыть · 180 ◈","","dice-primary")+'</div><h3>Предложения</h3>'+[0,8,9,12,15].map(i=>'<div class="dice-offer dice-panel">'+art(i)+'<div><b>'+D[i].name+'</b><small>5 копий</small></div>'+btn("buy",(80+40*D[i].rarity)+" ◈",i)+'</div>').join("")}
else if(S.tab==="modes"){h='<h2>Режимы</h2>'+[["training","TRAINING","Лаборатория, свободные эксперименты"],["duel","DUEL","Локальный соперник с ИИ"],["survival","SURVIVAL","Бесконечные волны и боссы"]].map(([id,n,desc])=>btn("mode",'<b>'+n+'</b><small>'+desc+'</small>',id,"dice-mode "+(S.mode===id?"chosen":""))).join("")+'<div class="dice-panel"><b>SYNC</b><p>Кооператив · SOON</p></div>'}
else{h='<div class="dice-detail"><small>SEASON 01 / ORIGIN</small><div class="dice-hero-art">'+art(1,5)+'</div><h2>ORIGIN</h2><p>Закрытая альфа</p></div><h3>Твоя колода</h3><div class="dice-deck">'+S.deck.map(i=>card(i,true)).join("")+'</div><div class="dice-mode-label"><small>'+S.mode.toUpperCase()+'</small>'+btn("nav","Изменить","modes")+'</div>'+btn("start","Начать бой","","dice-primary")+'<p>Тестовые матчи без печенек и рейтинга.</p>'}
host.dataset.diceScreen=i>=0?"detail":S.tab;
host.innerHTML=top()+'<div class="dice-body">'+h+'<p class="dice-notice">'+S.notice+'</p></div>'+(i<0?nav():"");
if(i>=0)S.previewStop=mountPreview($(".dice-preview"),i,S.rank);
}
function start(){S.previewStop?.();S.previewStop=null;audio();cancelAnimationFrame(S.raf);S.game=C.create(S.deck,S.mode,Math.random,S.levels);S.fx=[];S.trail.clear();S.selected=S.drag=-1;S.point=null;S.last=0;S.paused=false;S.speed=1;S.lab=false;S.notice="Призови кубик. Слияние: одинаковый тип и точки.";const g=S.game;if(g.opp){C.summon(g,g.opp);C.summon(g,g.opp)}
const h=g.opp?444:222;host.dataset.diceScreen="battle";host.innerHTML=top()+'<div class="dice-body"><div class="dice-mode-label">'+btn("menu","‹ Арена")+'<small>'+S.mode.toUpperCase()+'</small>'+btn("speed","1×")+'</div><div class="dice-stats"><div><strong data-dice-wave>01</strong><small>ВОЛНА</small></div><div><strong data-dice-sp>100</strong><small>SP</small></div><div><strong data-dice-boss>45с</strong><small>ДО БОССА</small></div></div><div class="dice-stage '+(g.opp?"duel":"")+'"><canvas width="720" height="'+h*2+'" class="dice-canvas" aria-label="Игровое поле"></canvas></div><div class="dice-actions">'+btn("summon","Призвать","","dice-primary")+btn("pause","Ⅱ")+(S.mode==="training"?btn("lab","⚗"):"")+'</div><small>POWER UP</small><div class="dice-deck">'+S.deck.map(i=>'<button type="button" class="dice-card dice-small" data-dice="power" data-i="'+i+'" style="--dc:'+D[i].color+';--edge:'+D[i].color+'">'+art(i)+'<b>'+D[i].name+'</b><span class="dice-bars">'+("<i></i>".repeat(5))+'</span><small>100 SP</small></button>').join("")+'</div>'+(S.mode==="training"?btn("demo","Заполнить поле для теста атак"):"")+'<div data-dice-lab></div><p class="dice-notice"></p><div data-dice-result></div></div>';
const cv=$("canvas");S.cv=cv;S.ctx=cv.getContext("2d");
const pointer=e=>{const r=cv.getBoundingClientRect();return [(e.clientX-r.left)*360/r.width,(e.clientY-r.top)*h/r.height]};
const cell=pt=>{const x=Math.floor((pt[0]-45)/54),y=Math.floor((pt[1]-(g.opp?222:0)-40)/45);return x>=0&&x<5&&y>=0&&y<3?y*5+x:-1};
cv.onpointerdown=e=>{if(g.done)return;S.point=pointer(e);S.drag=cell(S.point);try{cv.setPointerCapture(e.pointerId)}catch{}};
cv.onpointermove=e=>{if(S.drag>=0)S.point=pointer(e)};
cv.onpointercancel=()=>{S.drag=-1;S.point=null};
cv.onpointerup=e=>{if(g.done)return;const k=cell(pointer(e)),a=S.drag;S.drag=-1;S.point=null;if(k<0)return;
const source=a>=0&&a!==k?a:S.selected>=0&&S.selected!==k?S.selected:-1;
if(source>=0){if(C.merge(g,g.you,source,k)){S.selected=-1;S.notice="Слияние / специальная способность";tap()}else{S.notice="Нужны совместимые кубики с равным количеством точек.";S.selected=g.you.board[k]?k:-1}}else S.selected=g.you.board[k]&&S.selected!==k?k:-1;events();hud();draw()};
hud();draw();S.raf=requestAnimationFrame(loop)}
function offset(p){return S.game.opp&&p===S.game.you?222:0}
function eventFx(e){const g=S.game,p=e.p,y0=offset(p),c=D[e.i]?.color||"#cad6ef",local=!p.bot;let [x,y]=e.k>=0?C.pos(e.k):[e.x||0,e.y||0];y+=y0;
if(e.kind==="fire"){if(local&&e.i===0)sfx("wind");return}
if(e.kind==="hit"&&local&&e.i!==0)sfx(["wind","fire","ice","electric","iron","poison"][e.i]||"tick");
if(["merge","summon","boss","hurt"].includes(e.kind)&&local)sfx(e.kind);
if(e.kind==="boss"&&local)S.notice="Босс "+(e.name||"на маршруте")+"!";
if(e.kind==="hurt"&&local)S.notice="Прорыв обороны!";
if(e.kind==="arc"){S.fx.push({kind:"arc",x,y,a:e.a,b:e.b+y0,c,life:.2,max:.2});return}
if(["hurt","boss"].includes(e.kind))return;
const big=e.kind==="merge"||e.kind==="hit"&&e.i===1,rad=big?34:e.kind==="summon"?22:13;
S.fx.push({kind:"ring",x,y,c,life:.32,max:.32,rad});
for(let j=0;j<(big?12:4);j++){const a=Math.random()*6.283,v=22+Math.random()*65;S.fx.push({kind:"spark",x,y,c,life:.35,max:.35,vx:Math.cos(a)*v,vy:Math.sin(a)*v})}
if(S.fx.length>280)S.fx.splice(0,S.fx.length-280)
}
function events(){for(const e of S.game.events.splice(0))eventFx(e)}
function hud(){const g=S.game,p=g.you;const n=$(".dice-notice");if(n)n.textContent=S.notice;
$("[data-dice-wave]").textContent=String(g.wave).padStart(2,"0");$("[data-dice-sp]").textContent=Math.floor(p.sp);$("[data-dice-boss]").textContent=Math.max(0,Math.ceil(g.nextBoss-g.time))+"с";
const b=$('[data-dice="summon"]');b.textContent="＋ Призвать · "+p.cost+" SP";b.disabled=g.done||p.sp<p.cost||p.board.every(Boolean);
$('[data-dice="pause"]').textContent=S.paused?"▶":"Ⅱ";$('[data-dice="speed"]').textContent=S.speed+"×";
for(const i of p.pool){const b=$('[data-dice="power"][data-i="'+i+'"]'),n=p.power[i];b.disabled=g.done||n===5||p.sp<C.costs[n];b.querySelector("small").textContent=n===5?"MAX":C.costs[n]+" SP";b.querySelectorAll("i").forEach((el,k)=>el.style.background=k<n?D[i].color:"#ffffff18")}
}
function draw(){const g=S.game,ctx=S.ctx;if(!g||!ctx)return;const h=g.opp?444:222;ctx.setTransform(2,0,0,2,0,0);ctx.fillStyle="#090b12";ctx.fillRect(0,0,360,h);
function dot(x,y,r,c){ctx.beginPath();ctx.arc(x,y,r,0,Math.PI*2);ctx.fillStyle=c;ctx.fill()}
function rr(x,y,w,h,r,c,stroke){ctx.beginPath();if(ctx.roundRect)ctx.roundRect(x,y,w,h,r);else ctx.rect(x,y,w,h);if(c){ctx.fillStyle=c;ctx.fill()}if(stroke){ctx.strokeStyle=stroke;ctx.lineWidth=.8;ctx.stroke()}}
function ring(x,y,r,c,w=1){ctx.beginPath();ctx.arc(x,y,r,0,Math.PI*2);ctx.strokeStyle=c;ctx.lineWidth=w;ctx.stroke()}
function die(u,x,y,ghost=false){const c=D[u.i].color;ctx.save();ctx.translate(x,y);if(ghost)ctx.globalAlpha=.75;const grad=ctx.createLinearGradient(-23,-22,23,20);grad.addColorStop(0,c+"70");grad.addColorStop(.55,c+"10");grad.addColorStop(1,c+"33");rr(-23,-21,46,43,10,"#080a10");rr(-23,-22,46,42,10,grad,c+"bb");rr(-19,-18,38,34,8,null,"#ffffff22");
if(u.p>=5){ring(0,-2,21,c+"45",1);ring(0,-2,24,c+"20",.6)}
for(const[a,b]of C.pips[u.p]){const xx=a*10,yy=b*9-2;dot(xx,yy,5.4,c+"21");dot(xx,yy,3.7,c);dot(xx-.8,yy-.9,1.4,"#ffffffa0")}
ctx.font="700 6px system-ui";ctx.textAlign="center";ctx.fillStyle=c;ctx.fillText(D[u.i].name==="SUPPLEMENT"?"SUPPL.":D[u.i].name,0,16);
if(u.i===8&&u.p<7){rr(-17,19,34,2,1,"#ffffff18");rr(-17,19,34*Math.max(0,1-u.grow/14),2,1,c)}if(u.silence>0){rr(-23,-22,46,42,10,"#06070ac0");ctx.fillStyle="#ffd0db";ctx.font="18px system-ui";ctx.fillText("×",0,5)}ctx.restore()}
function field(p){const y=offset(p);rr(3,y+1,354,218,15,"#ffffff03","#ffffff10");ctx.font="600 10px system-ui";ctx.textAlign="left";ctx.fillStyle=p.bot?"#ff91a7":"#b0e8d0";ctx.fillText(p.bot?"OPPONENT / AI":"ТВОЁ ПОЛЕ",14,y+15);ctx.textAlign="right";ctx.fillText("♥".repeat(p.hp)+"♡".repeat(3-p.hp)+" · "+Math.floor(p.sp)+" SP",346,y+15);
ctx.beginPath();ctx.moveTo(18,y+29);ctx.lineTo(342,y+29);ctx.lineTo(342,y+195);ctx.lineTo(18,y+195);ctx.lineJoin="round";ctx.strokeStyle="#ffffff0c";ctx.lineWidth=12;ctx.stroke();ctx.strokeStyle="#ffffff25";ctx.lineWidth=.8;ctx.stroke();dot(18,y+29,3,"#91caff");dot(18,y+195,6,"#ff648024");dot(18,y+195,3,"#ff6480");
for(let k=0;k<15;k++){const[x,yy]=C.pos(k),u=p.board[k],sel=!p.bot&&S.selected===k;rr(x-25,y+yy-23,50,44,11,sel?"#ffffff14":"#ffffff04",sel?"#eeeaff":"#ffffff12");if(u)die(u,x,y+yy);else dot(x,y+yy,1.4,"#ffffff24")}
for(const e of p.enemies){const[x,yy]=C.path(e.pos),a=yy+y,r=e.boss?10:5.4,c=e.boss?"#ff829b":e.poison>0?"#a3e98a":"#d9e2f4";if(e.poison>0)dot(x,a,r+6,"#92e47e18");ctx.save();ctx.translate(x,a);ctx.rotate(e.pos*.01);rr(-r,-r,r*2,r*2,2,e.flash>0?"#fff":c+"33",c);ctx.restore();for(let j=0;j<e.ice;j++){const an=j*2.094+g.time*.3;dot(x+Math.cos(an)*r,a+Math.sin(an)*r,2.5,"#91e0ff")}rr(x-8,a-r-5,16,2,1,"#ffffff20");rr(x-8,a-r-5,16*Math.max(0,e.h/e.max),2,1,c);if(e.boss){ctx.font="7px system-ui";ctx.textAlign="center";ctx.fillStyle=c;ctx.fillText(e.kind,x,a+r+8)}}
ctx.font="8px system-ui";ctx.textAlign="left";ctx.fillStyle="#8e96aa";ctx.fillText("KILLS "+p.kills+(p.combo?" / COMBO "+p.combo:""),28,y+212)}
function lightning(x,y,a,b,c,seed){ctx.beginPath();ctx.moveTo(x,y);const dx=a-x,dy=b-y,len=Math.hypot(dx,dy)||1;for(let j=1;j<6;j++){const t=j/6,n=Math.sin(seed+j*18.2)*5;ctx.lineTo(x+dx*t-dy/len*n,y+dy*t+dx/len*n)}ctx.lineTo(a,b);ctx.strokeStyle=c+"44";ctx.lineWidth=5;ctx.stroke();ctx.strokeStyle=c;ctx.lineWidth=1.4;ctx.stroke();ctx.strokeStyle="#fff7df";ctx.lineWidth=.5;ctx.stroke()}
for(let j=0;j<50;j++)dot(j*137.3%360,j*83.7%h,.5,"#a9bada26");if(g.opp)field(g.opp);field(g.you);
const alive=new Set(g.shots);for(const s of S.trail.keys())if(!alive.has(s))S.trail.delete(s);
for(const s of g.shots){const c=D[s.i].color,y0=offset(s.p),x=s.x,y=s.y+y0;let trail=S.trail.get(s)||[];trail.push([x,y]);if(trail.length>6)trail.shift();S.trail.set(s,trail);if(s.i===3){lightning(s.sx,s.sy+y0,x,y,c,s.age*30);continue}trail.forEach(([a,b],j)=>{const t=(j+1)/trail.length;ctx.globalAlpha=t*.28;dot(a,b,(s.i===1?4:2)*t,c)});ctx.globalAlpha=1;ctx.save();ctx.translate(x,y);ctx.rotate(s.angle);if(s.i===0){rr(-7,-1,12,2,1,c)}else if(s.i===1){dot(0,0,8,"#ff6a3020");dot(0,0,5,"#ff703e");dot(1,-1,3,"#ffc36f")}else if(s.i===2){ctx.beginPath();ctx.moveTo(7,0);ctx.lineTo(-4,-3);ctx.lineTo(-1,0);ctx.lineTo(-4,3);ctx.closePath();ctx.fillStyle=c;ctx.fill()}else if(s.i===4){rr(-4,-3,8,6,1,"#9faac0","#f1f5ff")}else if(s.i===5){dot(0,0,5,c+"25");dot(0,0,3.3,c)}else{dot(0,0,3,c)}ctx.restore()}
for(const f of S.fx){const t=1-f.life/f.max;ctx.globalAlpha=1-t;if(f.kind==="arc")lightning(f.x,f.y,f.a,f.b,f.c,t*30);else if(f.kind==="ring")ring(f.x,f.y,3+f.rad*t,f.c,1.5);else dot(f.x,f.y,1.3,f.c)}ctx.globalAlpha=1;
if(S.drag>=0&&S.point&&g.you.board[S.drag])die(g.you.board[S.drag],S.point[0],S.point[1],true);
if(S.paused){rr(136,3,88,18,8,"#1c202b","#ffffff20");ctx.fillStyle="#fff";ctx.font="9px system-ui";ctx.textAlign="center";ctx.fillText("ПАУЗА",180,15)}
}
let hudAt=0,acc=0;
function loop(now){if(S.dead||!S.host.isConnected||!S.game)return;const g=S.game,dt=S.last?Math.min(.075,(now-S.last)/1000):0;S.last=now;
if(!S.paused&&!g.done){acc+=dt*S.speed;let count=0;while(acc>=1/120&&count++<20&&!g.done){C.tick(g,1/120);acc-=1/120}events();S.fx=S.fx.filter(f=>{f.life-=dt*S.speed;if(f.kind==="spark"){f.x+=f.vx*dt;f.y+=f.vy*dt}return f.life>0});if(now-hudAt>100){hud();hudAt=now}if(g.done){hud();$("[data-dice-result]").innerHTML='<div class="dice-panel dice-detail"><h2>'+(g.opp&&g.you.hp>0?"Победа":"Матч завершён")+'</h2><p>Волна '+g.wave+' · Уничтожено '+g.you.kills+'</p>'+btn("start","Играть снова","","dice-primary")+btn("menu","На арену")+'</div>'}}
draw();if(!g.done)S.raf=requestAnimationFrame(loop)}
function lab(){const el=$("[data-dice-lab]");el.innerHTML=S.lab?'<div class="dice-panel"><h3>Лаборатория</h3><div class="dice-labgrid"><select aria-label="Кубик" data-dice-type>'+S.deck.map(i=>'<option value="'+i+'">'+D[i].name+'</option>').join("")+'</select><select aria-label="Точки" data-dice-rank>'+[1,2,3,4,5,6,7].map(i=>'<option>'+i+'</option>').join("")+'</select>'+btn("add","Создать")+btn("sp","+500 SP")+btn("boss","Босс")+btn("clear","Очистить")+'</div></div>':""}
function click(e){const b=e.target.closest("[data-dice]");if(!b||!host.contains(b)||b.disabled)return;const a=b.dataset.dice,i=Number(b.dataset.i);audio();if(a==="exit"){exit();return}if(a==="sound"){S.sound=!S.sound;if(S.master)S.master.gain.value=S.sound?S.volume:0;if(S.sound)audio();b.textContent=S.sound?"♪":"♪ ×";return}
if(a==="menu"){S.tab="arena";menu();return}if(a==="start"){start();return}
if(S.game){const g=S.game,p=g.you;if(g.done)return;
if(a==="summon"){if(C.summon(g,p))tap()}
if(a==="power"&&C.power(p,i)){sfx("power");tap()}
if(a==="pause")S.paused=!S.paused;if(a==="speed")S.speed=S.speed===1?2:1;
if(S.mode==="training"){
if(a==="lab"){S.lab=!S.lab;lab()}if(a==="add")C.add(g,p,Number($("[data-dice-type]").value),Number($("[data-dice-rank]").value));if(a==="sp")p.sp+=500;if(a==="boss")C.spawn(g,p,true);
if(a==="clear"||a==="demo"){p.board.fill(null);p.enemies=[];g.shots=[];S.fx=[];S.trail.clear();p.hp=3;S.selected=-1;if(a==="demo"){for(let j=0;j<5;j++){C.add(g,p,p.pool[j],1,j);C.add(g,p,p.pool[j],5,j+5)}for(let j=0;j<5;j++){const en=C.spawn(g,p);en.pos=25+j*40;en.h*=2;en.max*=2}S.paused=false}}}
events();hud();draw();return}
S.notice="";if(a==="nav"){S.tab=b.dataset.i;S.detail=-1;S.slot=-1}if(a==="mode"){S.mode=b.dataset.i;S.tab="arena"}if(a==="slot"){S.tab="deck";S.slot=S.deck.indexOf(i)}
if(a==="card"){if(S.slot>=0&&!S.deck.includes(i)){S.deck[S.slot]=i;S.slot=-1}else{S.detail=i;S.rank=1}}
if(a==="back"){S.detail=-1;S.tab="deck"}if(a==="rank")S.rank=i;
if(a==="preset"){S.deck=presets[i].slice();S.slot=-1}
if(a==="upgrade"){const n=1+2*D[i].rarity+S.levels[i];if(S.copies[i]>=n+1&&S.gold>=100*n){S.gold-=100*n;S.copies[i]-=n+1;S.levels[i]++;S.notice="Класс повышен"}else S.notice="Недостаточно копий или тестовой валюты"}
if(a==="chest"){if(S.gold>=180){S.gold-=180;for(let j=0;j<12;j++)S.copies[Math.floor(Math.random()*D.length)]++;S.notice="12 копий добавлены"}else S.notice="Недостаточно тестовой валюты"}
if(a==="buy"){const price=80+40*D[i].rarity;if(S.gold>=price){S.gold-=price;S.copies[i]+=5;S.notice=D[i].name+" ×5"}else S.notice="Недостаточно тестовой валюты"}
menu()}
S.dispose=()=>{S.dead=true;S.previewStop?.();S.previewStop=null;cancelAnimationFrame(S.raf);host.removeEventListener("click",click);S.ac?.close().catch(()=>{});S.game=null;S.fx=[];S.trail.clear()};
host.innerHTML='<p class="sub">Проверяем доступ к закрытой альфе…</p>';
api("dice/access").then(r=>{if(S.dead||!host.isConnected)return;if(r.allowed!==true)throw Error("SOON");host.addEventListener("click",click);menu()}).catch(()=>{if(!S.dead&&host.isConnected){host.innerHTML='<p class="sub">DICE · SOON</p><button type="button" class="secondary" data-tab="games">К играм</button>'}});
}
function unmount(){if(active){active.dispose();active=null}}
window.NoraDice={mount,unmount,previewScenario,previewStep,previewStatus,previewDraw};
})();
