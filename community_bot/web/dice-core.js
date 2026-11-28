/* NORA DICE: local admin alpha. No wallet, ranking or network writes. */
(function(global){
"use strict";
const defs=[
["WIND","Ветер","#d5e6f4",19,.45,"Быстрые воздушные импульсы."],
["FIRE","Огонь","#ff8055",20,.8,"Взрыв по области при попадании."],
["ICE","Лёд","#75dfff",16,1.15,"Три ступени замедления цели."],
["ELECTRIC","Молния","#ffe080",19,.95,"Цепной разряд до трёх целей."],
["IRON","Железо","#b6c4dd",52,1.1,"Атака по наибольшему текущему HP; двойной урон боссам."],
["POISON","Яд","#92e47e",12,1.15,"Случайная цель, периодический урон."],
["CRITICAL","Крит","#ff9bd1",5,1.2,"Повышает шанс критической атаки соседей."],
["LIGHT","Свет","#fff0b0",5,1.2,"Ускоряет соседние кубики."],
["GROWTH","Рост","#75e9a0",4,1.4,"Через 14 секунд превращается в случайный кубик на одну точку выше."],
["JOKER","Джокер","#b3a1ff",5,1.4,"Копирует цель с равным числом точек, не уничтожая её."],
["MIMIC","Мимик","#6ad0bd",5,1.3,"Сливается с любым типом равного ранга."],
["SUPPLEMENT","Усилитель","#ffb97e",4,1.4,"Добавляет точку цели, сохраняя её тип."],
["SACRIFICE","Жертва","#ff8f9f",12,1.2,"Даёт SP при слиянии."],
["SUMMONER","Призыватель","#82a7ff",6,1.35,"При слиянии создаёт дополнительный кубик."],
["SWITCH","Обмен","#a1aaff",10,1.15,"Меняется местами с кубиком равного ранга."],
["ASSASSIN","Ассасин","#f2638e",8,1.3,"При слиянии удаляет точку случайного кубика соперника."],
["COMBO","Комбо","#edb6ff",13,.9,"Урон увеличивается после слияний."],
["YIN YANG","Инь-Ян","#e0e6f3",18,1.1,"Полные линии активируют гармонию."]];
const rarities=[0,0,0,1,0,1,1,1,3,3,2,3,2,3,2,3,3,3];
const dice=defs.map((d,i)=>({id:i,name:d[0],ru:d[1],color:d[2],damage:d[3],interval:d[4],description:d[5],rarity:rarities[i]}));
const pips=[[],[[0,0]],[[-1,-1],[1,1]],[[-1,-1],[0,0],[1,1]],[[-1,-1],[1,-1],[-1,1],[1,1]],[[-1,-1],[1,-1],[0,0],[-1,1],[1,1]],[[-1,-1],[-1,0],[-1,1],[1,-1],[1,0],[1,1]],[[-1,-1],[-1,0],[-1,1],[1,-1],[1,0],[1,1],[0,0]]];
const costs=[0,100,200,400,700], length=814;
const choose=(a,rng)=>a[Math.floor(rng()*a.length)];
function player(pool,training=false,bot=false){return {pool:pool.slice(),bot,board:Array(15).fill(null),sp:training?500:100,cost:10,power:Array(dice.length).fill(1),hp:3,kills:0,combo:0,enemies:[],spawn:.6,queued:0,transfer:0,ai:.8}}
function create(pool,mode="training",rng=Math.random,levels=[]){
if(pool.length!==5||new Set(pool).size!==5||pool.some(i=>!dice[i]))throw Error("Invalid deck");
return {you:player(pool,mode==="training"),opp:mode==="duel"?player([0,1,2,3,4],false,true):null,mode,rng,levels,time:0,wave:1,nextBoss:45,shots:[],events:[],done:false};
}
function emit(g,kind,p,k,extra={}){if(g.events.length<400)g.events.push({kind,p,k,...extra})}
function make(i,p=1){return {i,p,cd:0,grow:14,silence:0}}
function add(g,p,i,rank=1,k=-1){if(!dice[i]||rank<1||rank>7)return false;const free=p.board.flatMap((v,j)=>v?[]:[j]);if(!free.length)return false;if(!free.includes(k))k=choose(free,g.rng);p.board[k]=make(i,rank);emit(g,"summon",p,k,{i});return true}
function summon(g,p){if(p.sp<p.cost||!add(g,p,choose(p.pool,g.rng)))return false;p.sp-=p.cost;p.cost+=10;return true}
function power(p,i){const n=p.power[i];if(!p.pool.includes(i)||n>=5||p.sp<costs[n])return false;p.sp-=costs[n];p.power[i]++;return true}
function rival(g,p){return p===g.you?g.opp:g.you}
function merge(g,p,a,b){
if(a===b||a<0||b<0)return false;const u=p.board[a],v=p.board[b];if(!u||!v||u.p!==v.p)return false;const n=u.p;
if(u.i===9&&v.i!==9){p.board[a]=make(v.i,n);emit(g,"merge",p,a,{i:v.i});return true}
if(u.i===14&&v.i!==14){p.board[a]=v;p.board[b]=u;emit(g,"merge",p,b,{i:u.i});return true}
if(n===7)return false;
if(u.i===11&&v.i!==11){p.board[a]=null;p.board[b]=make(v.i,n+1);emit(g,"merge",p,b,{i:v.i});return true}
if(u.i!==v.i&&u.i!==10&&v.i!==10)return false;
const tags=new Set([u.i,v.i]),i=choose(p.pool,g.rng);p.board[a]=null;p.board[b]=make(i,n+1);
if(tags.has(12))p.sp+=80*n;
if(tags.has(13))add(g,p,choose(p.pool,g.rng),1+Math.floor(g.rng()*n));
if(tags.has(16))p.combo++;
const o=rival(g,p);if(tags.has(15)&&o){const k=choose(o.board.flatMap((d,j)=>d?[j]:[]),g.rng);if(k!==undefined){const target=o.board[k];if(--target.p===0)o.board[k]=null;emit(g,"assassin",o,k,{i:15})}}
emit(g,"merge",p,b,{i});return true;
}
function pos(k){return [72+k%5*54,63+Math.floor(k/5)*45]}
function path(s){return s<=324?[18+s,29]:s<=490?[342,29+s-324]:[342-(s-490),195]}
function spawn(g,p,boss=false,transfer=false){const hp=(55+20*g.wave)*Math.pow(1.26,g.wave-1)*(boss?9:1);const e={pos:0,h:hp,max:hp,boss,transfer,ice:0,slow:0,poison:0,pd:0,flash:0,dead:false,kind:boss?["KNIGHT","SILENCE","LEON","SNAKE","MAGICIAN"][(g.wave-1)%5]:"",skill:7};p.enemies.push(e);return e}
function adjacent(a,b){return a!==b&&Math.abs(a%5-b%5)<=1&&Math.abs(Math.floor(a/5)-Math.floor(b/5))<=1}
function harmony(p,k){const r=Math.floor(k/5),c=k%5,h=[0,1,2,3,4].every(j=>p.board[r*5+j]?.i===17),v=[0,1,2].every(j=>p.board[j*5+c]?.i===17);return h&&v?5:h||v?2:1}
function fire(g,p,k,u,e,d){const i=u.i,[x,y]=pos(k),[a,b]=path(e.pos),speed=[520,230,340,650,300,260][i]||420;const shot={p,e,i,d,power:p.power[i],sx:x,sy:y,x,y,age:0,dur:Math.max(.06,Math.hypot(a-x,b-y)/speed),arc:i===1?28:i===5?17:0,angle:0};if(g.shots.length<300)g.shots.push(shot);else hit(g,shot,a,b);emit(g,"fire",p,k,{i});}
function hit(g,s,x,y){const {p,e,i,d,power}=s;if(e.dead||e.h<=0)return;e.h-=d;e.flash=.1;
if(i===1){for(const f of p.enemies){const [a,b]=path(f.pos);if(f!==e&&f.h>0&&Math.hypot(a-x,b-y)<35){f.h-=d*.7;f.flash=.12}}}
if(i===2){e.ice=Math.min(3,e.ice+1);e.slow=Math.min(.5,e.ice*(.08+.02*(power-1)))}
if(i===3){let last=e,es=p.enemies.filter(f=>f!==e&&f.h>0);for(let j=0;j<2&&es.length;j++){const [a,b]=path(last.pos);es.sort((u,v)=>dist(u,a,b)-dist(v,a,b));const f=es.shift(),[xx,yy]=path(f.pos);if(Math.hypot(xx-a,yy-b)>85)break;f.h-=d*(j===0?.7:.3);f.flash=.13;emit(g,"arc",p,-1,{i,x:a,y:b,a:xx,b:yy});last=f}}
if(i===5){e.poison=4;e.pd=Math.max(e.pd,8+power*5)}
emit(g,"hit",p,-1,{i,x,y});}
function dist(e,x,y){const[a,b]=path(e.pos);return Math.hypot(a-x,b-y)}
function skill(g,p,e){const keys=p.board.flatMap((u,k)=>u?[k]:[]);
if(e.kind==="KNIGHT")for(const k of keys)p.board[k]=make(choose(p.pool,g.rng),p.board[k].p);
if(e.kind==="SILENCE")for(let j=0;j<3&&keys.length;j++)p.board[keys.splice(Math.floor(g.rng()*keys.length),1)[0]].silence=5;
if(e.kind==="LEON")for(const k of keys)if(p.board[k].p>1&&g.rng()<.45)p.board[k].p--;
if(e.kind==="SNAKE")for(let j=0;j<3;j++)spawn(g,p);
if(e.kind==="MAGICIAN"&&keys.length)p.board[choose(keys,g.rng)]=null;
emit(g,"boss",p,-1,{name:e.kind})}
function update(g,p,dt){
p.spawn-=dt;if(p.spawn<=0){spawn(g,p);p.spawn=Math.max(.43,1.25-g.wave*.045)}
if(p.queued>0){p.transfer-=dt;if(p.transfer<=0){p.queued--;spawn(g,p,false,true);p.transfer=.32}}
for(const e of p.enemies){e.pos+=(32+g.wave*2)*(1-e.slow)*(e.boss?.67:1)*dt;e.flash=Math.max(0,e.flash-dt);if(e.poison>0){e.poison-=dt;e.h-=e.pd*dt}if(e.boss&&e.h>0){e.skill-=dt;if(e.skill<=0){skill(g,p,e);e.skill=12}}}
for(let k=0;k<15;k++){let u=p.board[k];if(!u)continue;if(u.silence>0){u.silence-=dt;continue}
if(u.i===8&&u.p<7){u.grow-=dt;if(u.grow<=0){let i=choose(p.pool,g.rng);p.board[k]=make(i,u.p+1);emit(g,"merge",p,k,{i});continue}}
u.cd-=dt;if(u.cd>0)continue;
const es=p.enemies.filter(e=>e.h>0&&e.pos<length).sort((a,b)=>b.pos-a.pos);if(!es.length)continue;
const i=u.i,t=dice[i],pow=p.power[i],e=i===4?es.reduce((a,b)=>a.h>b.h?a:b):i===5?choose(es,g.rng):es[0];let d=t.damage*(1+.32*(pow-1))*(1+(p.bot?0:(g.levels[i]||0)*.05)),haste=1,crit=.05;
for(let j=0;j<15;j++){const v=p.board[j];if(!v||!adjacent(k,j)||v.silence>0)continue;if(v.i===7)haste+=.07*v.p;if(v.i===6)crit+=.025*v.p}
if(i===4&&e.boss)d*=2;if(i===16)d+=p.combo*7;if(i===17){const f=harmony(p,k);d*=f;if(f===5)haste*=2}if(g.rng()<Math.min(.65,crit))d*=2;
fire(g,p,k,u,e,d);u.cd+=t.interval/u.p/Math.min(3,haste);u.cd=Math.max(0,u.cd)}
}
function settle(g,p){p.enemies=p.enemies.filter(e=>{if(e.h<=0){e.dead=true;p.sp+=e.boss?100:10;p.kills++;const o=rival(g,p);if(o&&!e.boss&&!e.transfer)o.queued=Math.min(16,o.queued+1);const[x,y]=path(e.pos);emit(g,"kill",p,-1,{x,y,boss:e.boss});return false}if(e.pos>=length){e.dead=true;p.hp=Math.max(0,p.hp-(e.boss?2:1));emit(g,"hurt",p,-1);return false}return true})}
function bot(g,p,dt){p.ai-=dt;if(p.ai>0)return;p.ai=.7;if(p.board.filter(Boolean).length<12&&summon(g,p))return;if(p.sp>=100&&g.rng()<.4){const i=choose(p.pool.filter(i=>p.power[i]<5),g.rng);if(i!==undefined&&power(p,i))return}for(let a=0;a<15;a++)for(let b=0;b<15;b++)if(merge(g,p,a,b))return;summon(g,p)}
function tick(g,dt){if(g.done)return;g.time+=dt;if(g.time>=g.nextBoss){spawn(g,g.you,true);if(g.opp)spawn(g,g.opp,true);emit(g,"boss",g.you,-1);g.wave++;g.nextBoss+=45}update(g,g.you,dt);if(g.opp){update(g,g.opp,dt);bot(g,g.opp,dt)}
g.shots=g.shots.filter(s=>{if(s.e.dead||s.e.h<=0)return false;s.age+=dt;const [a,b]=path(s.e.pos),t=Math.min(1,s.age/s.dur),ox=s.x,oy=s.y;s.x=s.sx+(a-s.sx)*t;s.y=s.sy+(b-s.sy)*t-Math.sin(t*Math.PI)*s.arc;s.angle=Math.atan2(s.y-oy,s.x-ox);if(t>=1){hit(g,s,a,b);return false}return true});settle(g,g.you);if(g.opp)settle(g,g.opp);g.done=g.you.hp===0||g.opp?.hp===0;}
global.NoraDiceCore={dice,pips,costs,create,add,summon,power,merge,tick,spawn,pos,path};
})(typeof window==="undefined"?globalThis:window);
