"use strict";
window.NoraDot = (() => {
  const {W,H,X,R,PIPE,STEP,clamp,lerp,STAGES,stageAt,gravityMode,softMode,speedAt,typeNames,gateShape,segments,witnessFor,createRun,seededRandom}=window.NoraDotCore;

  let root,canvas,ctx,hud,score,progress,overlay,title,detail,button,soundButton,abort,observer;
  let raf=0,last=0,acc=0,run,mode="ready",muted=false,audio,master;
  let results,resultsBody,restart,queuedTicket=null,ticketRequest=null,flightTicket=null,flaps=[],flightId=0,viewId=0,resultRequest=null,connectTimer=0,initialStartPending=false;
  let intro=null,introTimer=0,introKey="",introActive=false,introStarted=false;
  let particles=[],trail=[],rings=[],labels=[],visualTime=0,crashTime=0,impact=0,stretch=0,coinPulse=0,zoom=1,shake=0,trailClock=0,flapAt=-10,gravityPulse=0;
  let reduced=false,scaleX=1,scaleY=1,paceNode,meterNode,pauseButton,lastPace=-1,lastSpeed="",renderAt=0,bank=0,cameraY=0,noiseBuffer=null,nearFlash=0,nearIds=new Set(),stageNode,stageBanner,stageTitle,stageDescription,stageTimer=0,theme=STAGES[0].color.slice();
  const SKINS={
    red:{name:"Классика",light:"#ffb4c1",mid:"#ff5977",dark:"#b8143c",rgb:[255,89,119]},
    mint:{name:"Мята",light:"#e3ffc8",mid:"#a5e86f",dark:"#41883c",rgb:[165,232,111]},
    ice:{name:"Лёд",light:"#d5faff",mid:"#66d8f1",dark:"#237da8",rgb:[102,216,241]},
    violet:{name:"Аметист",light:"#eadbff",mid:"#ac83f5",dark:"#6541b6",rgb:[172,131,245]}
  };
  let shopPanel,shopBody,shopBalance,shopStatus,shopState=null,shopBusy=false,shopOpen=false,skinId="red",shopRevision=0;
  let reviveTick=null,reviveBusy=false,lifePurchaseId=null;
  const skin=()=>SKINS[skinId]||SKINS.red;
  function applyShop(state){
    shopState=state;skinId=Object.hasOwn(SKINS,state.equipped)?state.equipped:"red";
    const s=skin();
    root.style.setProperty("--dot-skin-light",s.light);
    root.style.setProperty("--dot-skin-mid",s.mid);
    root.style.setProperty("--dot-skin-dark",s.dark);
    root.style.setProperty("--dot-skin-glow",rgb(...s.rgb,.4));
    renderShop();
  }
  function renderShop(){
    if(!shopBody||!shopState)return;
    shopBalance.textContent=Number(shopState.balance).toLocaleString("ru-RU")+" 🍪";
    shopBody.innerHTML=Object.entries(SKINS).map(([id,s])=>{
      const owned=shopState.owned.includes(id),active=shopState.equipped===id,price=shopState.prices[id];
      const label=active?"Выбран":owned?"Выбрать":price+" 🍪";
      return '<button type="button" class="dot-skin-item" data-dot-skin="'+id+'" '+(active||shopBusy||(!owned&&shopState.balance<price)?"disabled":"")+'><span class="dot-skin-preview" style="--sl:'+s.light+';--sm:'+s.mid+';--sd:'+s.dark+'"></span><span><b>'+s.name+'</b><small>'+label+'</small></span></button>';
    }).join("")+'<button type="button" class="dot-skin-item dot-life-item" data-dot-life '+(shopBusy||shopState.balance<(shopState.life_price||1500)?"disabled":"")+'><span class="dot-life-icon">♥</span><span><b>Вторая жизнь</b><small>'+Number(shopState.life_price||1500)+' 🍪 · в запасе '+Number(shopState.lives||0)+'</small></span></button>';
  }
  async function refreshShop(){
    const view=viewId,rev=++shopRevision;
    try{const state=await api("dot/shop");if(view===viewId&&rev===shopRevision&&root)applyShop(state);}
    catch(e){if(view===viewId&&rev===shopRevision&&shopOpen)shopStatus.textContent=e?.message||"Магазин недоступен";}
  }
  async function openShop(e){
    e?.stopPropagation();
    if(shopOpen||!(mode==="ready"||mode==="over"))return;
    shopOpen=true;shopPanel.hidden=false;shopStatus.textContent="";shopBody.innerHTML="Загрузка…";shopBalance.textContent="…";
    const view=viewId;
    if(resultRequest)await resultRequest.catch(()=>{});
    if(view===viewId&&shopOpen)await refreshShop();
  }
  function closeShop(){
    shopOpen=false;if(shopPanel)shopPanel.hidden=true;
  }
  async function chooseSkin(e){
    const id=e.target.closest("[data-dot-skin]")?.dataset.dotSkin;
    const life=!!e.target.closest("[data-dot-life]");
    if((!id&&!life)||shopBusy||!shopState||!shopOpen)return;
    const view=viewId;++shopRevision;shopBusy=true;shopStatus.textContent="";renderShop();
    try{
      if(life&&!lifePurchaseId)lifePurchaseId=globalThis.crypto?.randomUUID?.()||Date.now()+"-"+Math.random().toString(36).slice(2)+"-"+Math.random().toString(36).slice(2);
      const state=await api("dot/shop",life?{action:"buy_life",purchase_id:lifePurchaseId}:{action:shopState.owned.includes(id)?"equip":"buy",skin:id});
      if(life)lifePurchaseId=null;
      if(view===viewId&&root){applyShop(state);haptic("flap");}
    }catch(e){if(view===viewId&&root){shopStatus.textContent=e?.message||"Не удалось выполнить покупку";}}
    finally{if(view===viewId&&root){shopBusy=false;renderShop();}}
  }
  const motion=()=>window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches||false;
  const rgb=(r,g,b,a)=>"rgba("+r+","+g+","+b+","+clamp(a,0,1)+")";
  function disk(x,y,r,color){ctx.beginPath();ctx.arc(x,y,Math.max(.01,r),0,Math.PI*2);ctx.fillStyle=color;ctx.fill();}
  function rounded(x,y,w,h,r){ctx.beginPath();if(ctx.roundRect)ctx.roundRect(x,y,w,h,r);else ctx.rect(x,y,w,h);}
  function gradient(x,y,r,stops){const g=ctx.createRadialGradient(x,y,0,x,y,r);for(const [a,c] of stops)g.addColorStop(a,c);return g;}
  function line(x1,y1,x2,y2,color,w=1){ctx.beginPath();ctx.moveTo(x1,y1);ctx.lineTo(x2,y2);ctx.strokeStyle=color;ctx.lineWidth=w;ctx.stroke();}
  function haptic(kind){try{const h=window.Telegram?.WebApp?.HapticFeedback;if(kind==="cookie")h?.impactOccurred("heavy");else if(kind==="flap")h?.impactOccurred("light");else if(kind==="crash")h?.notificationOccurred("error");}catch{}}
  function wakeAudio(){
    if(muted)return;
    try{
      const AC=window.AudioContext||window.webkitAudioContext;if(!AC)return;
      if(!audio){audio=new AC();master=audio.createGain();master.gain.value=.19;const limiter=audio.createDynamicsCompressor?.();if(limiter){limiter.threshold.value=-16;limiter.ratio.value=6;master.connect(limiter);limiter.connect(audio.destination);}else master.connect(audio.destination);}
      if(audio.state==="suspended")void audio.resume().catch(()=>{});
    }catch{}
  }
  function tone(start,end,seconds,volume,delay=0,type="sine"){
    if(muted||!audio||audio.state!=="running")return;
    try{
      const t=audio.currentTime+delay,o=audio.createOscillator(),g=audio.createGain();
      o.type=type;o.frequency.setValueAtTime(start,t);o.frequency.exponentialRampToValueAtTime(end,t+seconds);
      g.gain.setValueAtTime(.001,t);g.gain.exponentialRampToValueAtTime(volume,t+.012);g.gain.exponentialRampToValueAtTime(.001,t+seconds);
      o.connect(g);g.connect(master);o.start(t);o.stop(t+seconds+.01);
      o.onended=()=>{o.disconnect();g.disconnect();};
    }catch{}
  }
  function noise(duration,volume,frequency){
    if(muted||!audio||audio.state!=="running")return;
    try{
      if(!noiseBuffer){noiseBuffer=audio.createBuffer(1,Math.floor(audio.sampleRate*.42),audio.sampleRate);const data=noiseBuffer.getChannelData(0);for(let i=0;i<data.length;i++)data[i]=Math.random()*2-1;}
      const t=audio.currentTime,s=audio.createBufferSource(),filter=audio.createBiquadFilter(),g=audio.createGain();
      s.buffer=noiseBuffer;filter.type="lowpass";filter.frequency.setValueAtTime(frequency,t);filter.frequency.exponentialRampToValueAtTime(Math.max(90,frequency*.18),t+duration);
      g.gain.setValueAtTime(volume,t);g.gain.exponentialRampToValueAtTime(.001,t+duration);
      s.connect(filter);filter.connect(g);g.connect(master);s.start(t);s.stop(t+duration);s.onended=()=>{s.disconnect();filter.disconnect();g.disconnect();};
    }catch{}
  }
  // Original adaptive house score: one uninterrupted 128 BPM clock, no external audio.
  const HOUSE_BEAT=60/128,HOUSE_STEP=HOUSE_BEAT/4;
  const HOUSE_ROOTS=[45,41,48,43]; // A, F, C, G
  const HOUSE_CHORDS=[[57,60,64],[53,57,60],[55,60,64],[55,59,62]];
  let house=null,houseIndex=0,housePhase=0,houseBreath=0;
  const hz=n=>440*Math.pow(2,(n-69)/12);
  function houseVoice(t,n,duration,volume,type="sine",cutoff=0,endHz=0){
    const h=house;if(!h)return;
    const o=audio.createOscillator(),g=audio.createGain(),f=cutoff?audio.createBiquadFilter():null;
    o.type=type;o.frequency.setValueAtTime(n,t);
    if(endHz)o.frequency.exponentialRampToValueAtTime(endHz,t+duration*.7);
    g.gain.setValueAtTime(.0001,t);g.gain.exponentialRampToValueAtTime(volume,t+.008);g.gain.exponentialRampToValueAtTime(.0001,t+duration);
    if(f){f.type="lowpass";f.frequency.setValueAtTime(cutoff,t);f.Q.value=.75;o.connect(f);f.connect(g);}else o.connect(g);
    g.connect(h.bus);h.sources.add(o);o.onended=()=>{h.sources.delete(o);o.disconnect();f?.disconnect();g.disconnect();if(h.stopped&&!h.sources.size)h.bus.disconnect();};
    o.start(t);o.stop(t+duration+.012);
  }
  function houseNoise(t,duration,volume,cutoff,type="highpass"){
    const h=house;if(!h)return;
    if(!h.noise){h.noise=audio.createBuffer(1,Math.ceil(audio.sampleRate*.5),audio.sampleRate);const v=h.noise.getChannelData(0);let seed=53;for(let i=0;i<v.length;i++){seed=(Math.imul(seed,1664525)+1013904223)>>>0;v[i]=seed/2147483648-1;}}
    const o=audio.createBufferSource(),f=audio.createBiquadFilter(),g=audio.createGain();
    o.buffer=h.noise;f.type=type;f.frequency.setValueAtTime(cutoff,t);f.Q.value=.65;
    g.gain.setValueAtTime(.0001,t);g.gain.exponentialRampToValueAtTime(volume,t+.004);g.gain.exponentialRampToValueAtTime(.0001,t+duration);
    o.connect(f);f.connect(g);g.connect(h.bus);h.sources.add(o);o.onended=()=>{h.sources.delete(o);o.disconnect();f.disconnect();g.disconnect();if(h.stopped&&!h.sources.size)h.bus.disconnect();};
    o.start(t);o.stop(t+duration+.009);
  }
  function stopHouse(resetClock=false){
    const h=house;house=null;
    if(resetClock){houseIndex=0;housePhase=0;houseBreath=0;}else if(h)houseIndex=Math.ceil(h.playedIndex/4)*4;
    if(!h)return;
    h.stopped=true;const now=h.context.currentTime;
    try{h.bus.gain.cancelScheduledValues(now);h.bus.gain.setTargetAtTime(.0001,now,.008);}catch{}
    for(const source of h.sources){try{source.stop(now+.035);}catch{}}
    if(!h.sources.size)h.bus.disconnect();
  }
  function startHouse(){
    if(house||muted||mode!=="play"||!audio||audio.state!=="running"||!master)return;
    const bus=audio.createGain(),now=audio.currentTime;bus.gain.setValueAtTime(.0001,now);bus.gain.setTargetAtTime(.78,now,.04);bus.connect(master);
    house={context:audio,bus,sources:new Set(),noise:null,next:now+.045,index:houseIndex,playedIndex:houseIndex,stage:run.stage,lastBeat:now+.045,lastBeatIndex:houseIndex,beatQueue:[],stopped:false};
  }
  function houseTransition(t,stage){
    const bar=Math.floor(house.index/16)%4,notes=HOUSE_CHORDS[bar];
    houseNoise(t,.24,.17,1800,"bandpass");
    houseVoice(t,hz(HOUSE_ROOTS[bar]-12),.26,.38,"sine",0,hz(HOUSE_ROOTS[bar]-12)*.8);
    notes.forEach((n,i)=>houseVoice(t+i*HOUSE_STEP*.5,hz(n+12),.20,.105,"triangle"));
    if(stage>=4)houseVoice(t,hz(notes[0]+24),.27,.045,"sine");
  }
  function houseNote(t,i){
    const h=house,beat=i%4===0,slot=i%16,bar=Math.floor(i/16)%4,root=HOUSE_ROOTS[bar],chord=HOUSE_CHORDS[bar];
    if(beat&&h.stage!==run.stage){h.stage=run.stage;houseTransition(t,h.stage);}
    const stage=h.stage;
    if(beat){
      h.beatQueue.push({t,i});
      houseVoice(t,145,.23,stage>=4?.77:.65,"sine",0,43);
      houseNoise(t,.018,.08,2400);
    }
    // Off-beat bass leaves room for the kick; later stages add syncopation and octave accents.
    if(slot%4===2||(stage>=4&&(slot===7||slot===15))){
      const n=root-12+(stage>=5&&slot===14?12:0);
      houseVoice(t,hz(n),.17,.37,"triangle",stage>=4?1100:650);
      if(stage>=3)houseVoice(t,hz(n+12),.13,.10,"sawtooth",stage>=5?1350:800);
    }
    if(slot%4===2)houseNoise(t,stage>=2?.115:.07,stage>=2?.12:.075,6500);
    if(stage>=1&&(slot===4||slot===12)){
      houseNoise(t,.11,.16,1600,"bandpass");houseNoise(t+.012,.065,.07,4200);
    }
    if(stage>=2&&(slot===2||slot===10||(stage>=4&&slot===14))){
      chord.forEach(n=>houseVoice(t,hz(n),.16,stage>=4?.055:.038,"triangle",stage>=5?2300:1250));
    }
    if(stage>=3&&(slot%2===1||stage>=6&&slot%4===0)){
      const n=chord[Math.floor(slot/2)%3]+12+(slot===15?12:0);
      houseVoice(t,hz(n),.105,stage>=5?.068:.043,"triangle",2500);
    }
    if(stage>=4&&slot%2===1)houseNoise(t,.035,.055,8000);
    if(stage>=5&&slot===0)houseVoice(t,hz(root+12),.64,.035,"sawtooth",700);
    if(stage>=6&&(slot===6||slot===14))houseVoice(t,hz(chord[2]+12),.21,.07,"triangle",3200);
  }
  function pumpHouse(){
    if(muted||mode!=="play"||!audio||audio.state!=="running"){if(house)stopHouse();return;}
    try{
      startHouse();const h=house;if(!h)return;const now=audio.currentTime;
      // Never burst overdue notes after a stalled frame.
      if(h.next<now-.03){const skip=Math.ceil((now+.025-h.next)/HOUSE_STEP);h.next+=skip*HOUSE_STEP;h.index+=skip;}
      while(h.next<now+.085){houseNote(h.next,h.index);h.index++;h.next+=HOUSE_STEP;}
      while(h.beatQueue.length&&h.beatQueue[0].t<=now){const beat=h.beatQueue.shift();h.lastBeat=beat.t;h.lastBeatIndex=beat.i;h.playedIndex=beat.i+1;}
      housePhase=h.lastBeatIndex/4+Math.max(0,now-h.lastBeat)/HOUSE_BEAT;
    }catch{stopHouse();}
  }
  function sfx(kind){
    if(kind==="flap"){tone(210,430,.085,.095);tone(570,890,.05,.045);noise(.075,.045,1800);}
    if(kind==="flip"){const up=run.gravity<0;tone(up?220:540,up?560:185,.14,.12,0,"sine");tone(up?470:320,up?820:150,.10,.045,.02);}
    if(kind==="cookie"){tone(784,1047,.13,.23);tone(1175,1568,.17,.16,.047);tone(2093,1960,.20,.07,.09);}
    if(kind==="pass")tone(370,415,.065,.045);
    if(kind==="stage"&&!house){const hz=220+run.stage*35;tone(hz,hz*1.5,.22,.17);tone(hz*1.5,hz*2,.25,.13,.10);tone(hz*2,hz*3,.30,.08,.20);noise(.24,.065,900+run.stage*200);}
    if(kind==="crash"){tone(145,38,.29,.42,0,"triangle");tone(76,32,.36,.3,.018);noise(.30,.38,2200);}
  }
  function setMute(value){
    muted=value;soundButton.setAttribute("aria-pressed",String(muted));
    soundButton.setAttribute("aria-label",muted?"Включить звук DOT":"Выключить звук DOT");
    soundButton.classList.toggle("muted",muted);
    if(master&&audio)master.gain.setTargetAtTime(muted?0:.19,audio.currentTime,.015);
    try{localStorage.setItem("nora.dot.muted",muted?"1":"0");}catch{}
    if(muted)stopHouse();else wakeAudio();
  }
  function reset(ticket=null){
    stopHouse(true);flightId++;flightTicket=ticket;flaps=[];reviveTick=null;reviveBusy=false;resultRequest=null;initialStartPending=false;clearTimeout(connectTimer);connectTimer=0;
    run=createRun(ticket?seededRandom(ticket.seed):Math.random);particles=[];trail=[];rings=[];labels=[];crashTime=impact=stretch=coinPulse=shake=trailClock=0;
    zoom=1;bank=cameraY=nearFlash=gravityPulse=0;nearIds.clear();lastPace=-1;lastSpeed="";flapAt=-10;acc=0;last=0;mode="ready";stageTimer=0;theme=STAGES[0].color.slice();updateStage(false);updateHud();showOverlay();
  }
  function updateStage(announce){
    const s=STAGES[run.stage];stageNode.textContent=s.name;canvas.setAttribute("aria-label",gravityMode(run.passed)?"Игровое поле DOT. Касание, пробел или стрелка вверх меняют гравитацию.":"Игровое поле DOT. Касание, пробел или стрелка вверх для прыжка.");root.style.setProperty("--dot-phase","rgb("+s.color.join(",")+")");root.dataset.dotPhase=String(run.stage);stageBanner.hidden=!announce;stageTimer=announce?1.85:0;
    if(announce){stageTitle.textContent=s.name;stageDescription.textContent=s.description;stageBanner.getAnimations?.().forEach(a=>a.cancel());if(!reduced)stageBanner.animate?.([{opacity:0,transform:"translateY(-8px) scale(.96)"},{opacity:1,transform:"none",offset:.15},{opacity:1,offset:.78},{opacity:0}],{duration:1850,easing:"ease-out"});}
  }
  function updateHud(){
    const value=String(run.cookies);if(score.textContent!==value){score.textContent=value;score.classList.remove("pop");score.classList.add("pop");if(score.animate&&!reduced)score.animate([{transform:"scale(.82)",color:"#ffe0ac"},{transform:"scale(1.22)",color:"#ffe0ac",offset:.55},{transform:"scale(1)"}],{duration:330,easing:"cubic-bezier(.16,1,.3,1)"});}
    progress.textContent=String(run.passed);
    hud.setAttribute("aria-label","Печеньки: "+run.cookies+", пройдено: "+run.passed);
  }
  function showOverlay(){
    overlay.hidden=mode==="play"||mode==="crash"||mode==="over";results.hidden=mode!=="over";
    overlay.dataset.state=mode;root.dataset.dotState=mode;if(pauseButton){pauseButton.disabled=mode!=="play";pauseButton.setAttribute("aria-disabled",String(mode!=="play"));}
    title.textContent=mode==="over"?"Полёт завершён":mode==="paused"?"Пауза":"DOT";
    detail.textContent=mode==="over"?"🍪 "+run.cookies+"  ·  "+run.passed+" пройдено":mode==="paused"?"Продолжи, когда будешь готов":"Касайся экрана, чтобы взлететь";
    button.textContent=mode==="over"?"Ещё раз":mode==="paused"?"Продолжить":"Играть";
    overlay.querySelector(".dot-shop-open").hidden=mode!=="ready";
    overlay.querySelector(".dot-start").hidden=mode==="revive";
    overlay.querySelector(".dot-revive-actions").hidden=mode!=="revive";
    if(mode==="revive"){title.textContent="Вторая жизнь";detail.textContent="Продолжить этот полёт? В запасе: "+Number(shopState?.lives||0);}
  }
  function burst(x,y,count,color,velocity){
    for(let i=0;i<(reduced?Math.ceil(count/3):count);i++){
      const a=Math.random()*Math.PI*2,v=velocity*(.22+Math.random()*.78),life=.25+Math.random()*.48;
      particles.push({x,y,vx:Math.cos(a)*v,vy:Math.sin(a)*v,life,max:life,size:1+Math.random()*2.8,color,angle:a,spin:(Math.random()-.5)*9,shard:Math.random()>.55});
    }
    if(particles.length>180)particles.splice(0,particles.length-180);
  }
  function input(){
    if(introActive||shopOpen||shopBusy||mode==="revive")return;
    if(!root||document.hidden||document.querySelector("dialog[open]")||mode==="crash"||initialStartPending)return;
    wakeAudio();
    if(mode==="over"||mode==="ready"){
      if(!queuedTicket&&!ticketRequest)primeTicket();
      if(!queuedTicket&&ticketRequest){
        initialStartPending=true;if(mode==="ready")button.textContent="Подключаемся…";const view=viewId;
        const launch=()=>{if(view!==viewId||!initialStartPending||!root?.isConnected)return;initialStartPending=false;clearTimeout(connectTimer);connectTimer=0;startFlight();};
        connectTimer=setTimeout(launch,1000);ticketRequest.then(launch,launch);return;
      }
      startFlight();return;
    }
    if(mode==="ready"||mode==="paused"){mode="play";last=0;acc=0;run.py=run.y;run.previousDistance=run.distance;run.previousTime=run.time;flapAt=-10;showOverlay();canvas.focus?.({preventScroll:true});}
    if(run.time-flapAt<.0225||flaps.at(-1)===run.ticks)return;
    run.flap();if(flaps.at(-1)!==run.ticks)flaps.push(run.ticks);flapAt=run.time;stretch=1;
    if(gravityMode(run.passed)){
      gravityPulse=1;const color=run.gravity<0?[102,224,239]:[187,148,255];
      burst(X-7,run.y,12,color,60);rings.push({x:X,y:run.y,life:.36,max:.36,color,size:65});sfx("flip");
    }else{burst(X-7,run.y+4,7,skin().rgb,48);rings.push({x:X,y:run.y,life:.19,max:.19,color:skin().rgb,size:12});sfx("flap");}
    haptic("flap");
  }
  const INTRO_FRAMES=[
    ["ПОБЕЙ","МИРОВОЙ","РЕКОРД"],
    ["ЗАБЕРИ","ВСЕ","ПЕЧЕНЬКИ"],
    ["НЕ БОЛЕЕ","ДВУХ НАГРАД","ЗА 24 ЧАСА"],
    ["СОБИРАЙ","ПЕЧЕНЬКИ DOT","ОТКРЫВАЙ ЦВЕТА"]
  ];
  function introStorageKey(){
    const id=typeof data!=="undefined"?data?.user?.user_id:null;
    return "nora.dot.reward-intro.v1."+(id||"device");
  }
  function closeIntro(remember=false){
    clearTimeout(introTimer);introTimer=0;
    if(intro){intro.remove();intro=null;}
    if(root)root.inert=false;
    introActive=false;introStarted=false;
    if(remember){
      try{localStorage.setItem(introKey,"1");}catch{}
      api("dot/intro",{}).catch(()=>{});
    }
  }
  function showIntroFrame(index){
    if(!introActive||!intro)return;
    const frame=INTRO_FRAMES[index];
    if(!frame){intro.classList.add("dot-intro-out");introTimer=setTimeout(()=>closeIntro(true),reduced?30:620);return;}
    const words=intro.querySelector(".dot-intro-words");
    words.innerHTML=frame.map((line,i)=>'<span style="--word:'+i+'">'+line+'</span>').join("");
    words.classList.toggle("dot-intro-accent",index===1);
    introTimer=setTimeout(()=>showIntroFrame(index+1),reduced?1800:2250);
  }
  function launchIntro(){
    if(!introActive||introStarted)return;
    introStarted=true;clearTimeout(introTimer);showIntroFrame(0);
  }
  function prepareIntro(){
    introKey=introStorageKey();
    try{if(localStorage.getItem(introKey)==="1")return;}catch{}
    intro=document.createElement("div");intro.className="dot-intro-screen";intro.setAttribute("role","dialog");intro.setAttribute("aria-modal","true");
    intro.setAttribute("aria-label","Побей мировой рекорд. Забери все печеньки. Не более двух наград за 24 часа. Собирай печеньки DOT и открывай цвета.");
    intro.innerHTML='<div class="dot-intro-logo">D<span>O</span>T</div><div class="dot-intro-words" aria-hidden="true"></div><div class="dot-intro-line" aria-hidden="true"></div>';
    document.body.append(intro);root.inert=true;introActive=true;introStarted=false;
    introTimer=setTimeout(launchIntro,450);
  }
  function primeTicket(){
    if(queuedTicket||ticketRequest||!root)return;
    const view=viewId;
    const promise=api("dot/start",{}).then(ticket=>{
      if(view===viewId&&root&&ticket&&Number.isInteger(ticket.seed)&&typeof ticket.token==="string"){
        queuedTicket=ticket;
        if(introActive&&ticket.intro_seen){try{localStorage.setItem(introKey,"1");}catch{}closeIntro(false);}
        else if(introActive)launchIntro();
      }
    }).catch(()=>{});
    ticketRequest=promise;promise.finally(()=>{if(ticketRequest===promise)ticketRequest=null;});
  }
  function startFlight(){
    if(!root?.isConnected||document.hidden||document.querySelector("dialog[open]")){initialStartPending=false;showOverlay();return;}
    const ticket=queuedTicket;queuedTicket=null;
    reset(ticket);mode="play";showOverlay();canvas.focus?.({preventScroll:true});primeTicket();
    run.flap();flaps.push(0);flapAt=0;stretch=1;burst(X-7,run.y+4,7,skin().rgb,48);sfx("flap");haptic("flap");
  }
  function avatarHTML(person){
    const id=Number(person.id),name=String(person.name||"Участник"),initial=(name.match(/[\p{L}\p{N}]/u)?.[0]||"?").toUpperCase();
    return '<span class="person-avatar dot-rank-avatar"'+(id>0?' data-person-avatar="'+id+'"'+(person.has_avatar?'':' data-avatar-unavailable'):'')+'>'+esc(initial)+'</span>';
  }
  function profileAttrs(person){
    if(!person.id)return ' disabled';
    return person.self?' data-tab="lk"':' data-person-view="'+Number(person.id)+'"';
  }
  function renderRanking(payload,message=""){
    if(!root||!resultsBody)return;
    const leaders=payload?.top||[],mine=payload?.self,record=!!payload?.new_record;
    const reward=Number(payload?.reward||0),world=!!payload?.world_record;
    const rewardHTML=reward>0?'<div class="dot-reward-earned">+'+reward+' 🍪 НА БАЛАНС</div>':payload?.limit_reached?'<div class="dot-reward-limit">Мировой рекорд! Лимит наград на 24 часа исчерпан.</div>':'';
    const dotEarned=Number(payload?.dot_earned||0);
    const dotHTML=dotEarned>0?'<div class="dot-shop-earned">+'+dotEarned+' 🍪 DOT · в магазин</div>':'';
    const slots=[2,1,3].map(rank=>{
      const row=leaders.find(p=>p.rank===rank);
      if(!row)return '<div class="dot-podium-slot rank-'+rank+' dot-podium-empty"><span class="dot-rank-avatar">·</span><span class="dot-rank-name">Свободно</span><span class="dot-rank-score">—</span><span class="dot-podium-step">'+rank+'</span></div>';
      return '<button type="button" class="dot-podium-slot rank-'+rank+(row.self?' is-self':'')+'"'+profileAttrs(row)+' aria-label="'+esc(row.name)+', место '+rank+'">'+(rank===1?'<span class="dot-crown" aria-hidden="true">♛</span>':'')+avatarHTML(row)+'<span class="dot-rank-name">'+esc(row.name)+'</span>'+(row.prefix?'<span class="dot-rank-prefix">'+esc(row.prefix.emoji||"")+' '+esc(row.prefix.text||"")+'</span>':'')+'<span class="dot-rank-score">🍪 '+row.cookies+'</span><span class="dot-podium-step">'+rank+'</span>'+(row.self?'<span class="dot-rank-you">ТЫ</span>':'')+'</button>';
    }).join("");
    const personal=mine&&mine.rank>3?'<button type="button" class="dot-self-rank"'+profileAttrs(mine)+'><strong>#'+mine.rank+'</strong>'+avatarHTML(mine)+'<span><b>Ты на '+mine.rank+' месте</b><small>Личный рекорд</small></span><b>🍪 '+mine.cookies+'</b></button>':(!mine&&payload?'<p class="dot-rank-status">У тебя пока нет сохранённого результата.</p>':'');
    const podium=payload?'<div class="dot-podium">'+slots+'</div>': '<div class="dot-rank-loading">'+(message?esc(message):'<span class="dot-rank-spinner"></span> Обновляем топ…')+'</div>';
    resultsBody.innerHTML='<div class="dot-result-heading"><span>ТВОЙ РЕЗУЛЬТАТ</span><strong>🍪 '+run.cookies+'</strong><small>'+STAGES[run.stage].name+' · '+run.passed+' пройдено</small>'+(record?'<b class="dot-new-record">✦ '+(world?'WORLD RECORD':'NEW RECORD')+'</b>':'')+rewardHTML+dotHTML+'</div><div class="dot-rank-caption">ТОП-3 <span>ЗА ВСЁ ВРЕМЯ</span></div>'+podium+personal+(payload&&message?'<p class="dot-rank-status">'+esc(message)+'</p>':'');
    results.classList.toggle("has-record",record);
  }
  function endFlight(){
    if(reviveBusy)return;
    mode="over";showOverlay();finishFlight();
  }
  async function useSecondLife(){
    if(mode!=="revive"||reviveBusy||!flightTicket||reviveTick!==null)return;
    const view=viewId,id=flightId,tick=run.ticks;
    reviveBusy=true;
    const controls=overlay.querySelector(".dot-revive-actions");
    controls.querySelectorAll("button").forEach(b=>b.disabled=true);
    try{
      const state=await api("dot/revive",{token:flightTicket.token,ticks:tick,flaps:flaps.slice()});
      if(view!==viewId||id!==flightId||!root?.isConnected)return;
      ++shopRevision;applyShop(state);
      if(!run.revive())throw Error("Не удалось восстановить полёт");
      reviveTick=tick;particles=[];trail=[];rings=[];labels=[];impact=shake=stretch=0;flapAt=-10;
      mode="paused";last=acc=0;showOverlay();haptic("cookie");
    }catch(e){if(view===viewId&&id===flightId&&root)detail.textContent=e?.message||"Не удалось использовать жизнь. Повтори попытку.";}
    finally{if(view===viewId&&id===flightId&&root){reviveBusy=false;controls.querySelectorAll("button").forEach(b=>b.disabled=false);}}
  }
  function finishFlight(){
    const view=viewId,id=flightId,ticket=flightTicket,record={token:ticket?.token,ticks:run.ticks,flaps:flaps.slice(),revive_tick:reviveTick};
    renderRanking(null);
    const still=()=>view===viewId&&id===flightId&&root?.isConnected&&mode==="over";
    const request=ticket?api("dot/finish",record):api("dot/top");
    resultRequest=request;
    request.then(payload=>{if(payload?.reward>0&&typeof toast==="function")toast("DOT: +"+payload.reward+" 🍪 за мировой рекорд");if(still()){renderRanking(payload,ticket?"":"Тренировочная партия: результат не записан.");void refreshShop();}}).catch(async()=>{
      if(!still())return;
      try{const payload=await api("dot/top");if(still())renderRanking(payload,"Не удалось подтвердить результат этой партии.");}
      catch{if(still())renderRanking(null,"Топ временно недоступен.");}
    });
    primeTicket();
  }
  function event(kind){
    if(kind==="cookie"){
      coinPulse=1;updateHud();burst(X,run.y,25,[255,196,111],135);burst(X,run.y,6,[255,240,205],90);
      rings.push({x:X,y:run.y,life:.4,max:.4,color:[255,195,103]});
      labels.push({x:X+15,y:run.y-18,life:.65,max:.65});
    }
    if(kind==="pass")updateHud();
    if(kind==="stage"){if(gravityMode(run.passed))gravityPulse=1;else gravityPulse=0;updateStage(true);const c=STAGES[run.stage].color;burst(X,run.y,18,c,95);rings.push({x:X,y:run.y,life:.55,max:.55,color:c,size:55});}
    if(kind==="crash"){
      stopHouse();mode="crash";crashTime=0;impact=1;shake=reduced?0:1;
      burst(X,run.y,55,[255,70,96],245);burst(X,run.y,19,[255,222,228],160);
      rings.push({x:X,y:run.y,life:.48,max:.48,color:[255,75,102],size:64});rings.push({x:X,y:run.y,life:.28,max:.28,color:[255,220,235],size:34});
      showOverlay();
    }
    sfx(kind);haptic(kind);
  }
  function pause(){
    if(mode==="play"){stopHouse();mode="paused";showOverlay();}
    last=0;acc=0;
  }
  function simulate(dt){
    if(mode!=="play")return;
    run.step(dt,event);
    trailClock+=dt;
    if(trailClock>=1/90){trailClock-=1/90;trail.push({y:run.y,d:run.distance,time:run.time});}
    while(trail.length>0&&run.time-trail[0].time>.36)trail.shift();
    for(const g of run.gates){for(const p of segments(g,run.time)){const x=g.x-run.distance+p.offset,clearance=p.gap/2-Math.abs(run.y-p.center)-R;if(x<=X+R&&x+p.width>=X-R&&clearance>=0&&clearance<8&&!nearIds.has(g.x)){nearIds.add(g.x);nearFlash=.6;}}}
    for(const x of nearIds)if(x<run.distance-140)nearIds.delete(x);
  }
  function visual(dt){
    houseBreath=lerp(houseBreath,!reduced&&house&&mode==="play"&&!muted?1:0,1-Math.exp(-dt*3.2));
    visualTime+=dt;if(stageTimer>0){stageTimer=Math.max(0,stageTimer-dt);if(stageTimer===0)stageBanner.hidden=true;}theme=theme.map((v,i)=>lerp(v,STAGES[run.stage].color[i],1-Math.exp(-dt*2.3)));stretch*=Math.exp(-dt*10);coinPulse*=Math.exp(-dt*5);impact*=Math.exp(-dt*8);shake*=Math.exp(-dt*10);
    gravityPulse*=Math.exp(-dt*6);nearFlash*=Math.exp(-dt*6);const target=mode==="ready"?1:1+Math.min(.045,(speedAt(run.time,run.passed)-125)*.00019);
    zoom=lerp(zoom,reduced?1:target,1-Math.exp(-dt*2.6));bank=lerp(bank,reduced?0:clamp(run.vy/500,-.55,.55),1-Math.exp(-dt*13));cameraY=lerp(cameraY,reduced?0:clamp((run.y-H/2)*.055,-10,10),1-Math.exp(-dt*4));
    if(mode==="crash"){crashTime+=dt;if(crashTime>=(reduced?.12:.34)){if(flightTicket&&reviveTick===null&&Number(shopState?.lives||0)>0){mode="revive";showOverlay();}else endFlight();}}
    for(const p of particles){p.x+=p.vx*dt;p.y+=p.vy*dt;p.vy+=85*dt;p.vx*=Math.exp(-dt*2);p.angle+=p.spin*dt;p.life-=dt;}
    for(const r of rings)r.life-=dt;
    for(const l of labels){l.y-=38*dt;l.life-=dt;}
    particles=particles.filter(p=>p.life>0);rings=rings.filter(r=>r.life>0);labels=labels.filter(l=>l.life>0);
  }
  // Slow, offset breathing across the whole orb field. One cycle spans 4 or 8 beats;
  // a continuous cosine has no attack flash or abrupt decay at the beat boundary.
  function orbBreath(i,beats,mix){
    const cycle=i%3===1?8:4;
    const wave=.5-.5*Math.cos(2*Math.PI*(beats/cycle+i*.173));
    const amount=clamp(mix,0,1)*(.72+(i%3)*.14);
    return {light:.024*wave*amount,scale:1+.115*wave*amount};
  }
  function background(distance){
    ctx.fillStyle="#08090e";ctx.fillRect(0,0,W,H);
    const v=clamp((speedAt(run.time,run.passed)-125)/240,0,1),cy=H*.48-cameraY*2;
    ctx.fillStyle=gradient(W*.36,cy,H*.61*zoom,[[0,rgb(...theme,.19)],[.5,rgb(...theme,.045)],[1,"#08090e"]]);ctx.fillRect(0,0,W,H);
    ctx.save();ctx.globalAlpha=.75;
    const bands=[{s:46,p:.10,a:.055,r:.65},{s:91,p:.26,a:.15,r:1.05}];
    for(const l of bands){
      const offset=distance*l.p%l.s;
      ctx.beginPath();
      for(let x=-offset;x<W;x+=l.s)for(let y=15;y<H;y+=l.s){ctx.moveTo(x+l.r,y);ctx.arc(x,y,l.r,0,Math.PI*2);}
      ctx.fillStyle=rgb(...theme,l.a);ctx.fill();
    }
    ctx.restore();
    if(!reduced){
      for(let i=0;i<6;i++){
        const y=35+i*85-cameraY*(.4+i*.1),x=((i*193-distance*.09)%510+510)%510-150;
        const breath=orbBreath(i,housePhase,houseBreath),radius=(65+i*5)*breath.scale;
        ctx.fillStyle=gradient(x,y,radius,[[0,rgb(...theme,.045+v*.035+breath.light)],[.42,rgb(...theme,(.045+v*.035+breath.light)*.38)],[1,rgb(...theme,0)]]);
        ctx.fillRect(x-radius,y-radius,2*radius,2*radius);
      }
      if(v>.06){for(let i=0;i<15;i++){
        const x=((i*91-distance*(.75+i%3*.18))%460+460)%460-60,y=22+(i*89)%456;
        const g=ctx.createLinearGradient(x,y,x+18+v*45,y);g.addColorStop(0,"#ff769100");g.addColorStop(1,rgb(...theme,v*.19));
        line(x,y,x+18+v*45,y,g,.8);
      }}
    }
  }
  function wall(x,y,w,h,isTop,kind="static",t=0){
    if(h<=0)return;
    const radius=Math.min(9,h*.5),g=ctx.createLinearGradient(x,y,x+w,y),cap=isTop?y+h:y;
    g.addColorStop(0,"#4a4455");g.addColorStop(.065,"#8a7c95");g.addColorStop(.13,"#393243");g.addColorStop(.56,"#211e2b");g.addColorStop(.88,"#181722");g.addColorStop(1,"#413748");
    rounded(x,y,w,h,radius);ctx.save();if(kind==="phantom")ctx.globalAlpha=.27+.25*(.5+.5*Math.sin(t*2.2));ctx.fillStyle=g;ctx.fill();ctx.restore();ctx.strokeStyle=rgb(...theme,kind==="phantom"?.72:.45);ctx.lineWidth=kind==="phantom"?1.5:.9;ctx.stroke();
    ctx.save();ctx.clip();if(kind==="phantom")ctx.globalAlpha=.25+.35*(.5+.5*Math.sin(t*2.2));
    const reflection=ctx.createLinearGradient(x,y,x+w,y+Math.min(h,105));reflection.addColorStop(0,"#f8e9ff1f");reflection.addColorStop(.36,"#ffffff05");reflection.addColorStop(.39,"#d9c7f016");reflection.addColorStop(.44,"#ffffff00");reflection.addColorStop(1,"#e19ac30c");
    ctx.fillStyle=reflection;ctx.fillRect(x,y,w,h);
    line(x+3,y+4,x+3,y+h-4,"#f1e5ff47",.8);line(x+w-3,y+4,x+w-3,y+h-4,"#06050caa",2);
    const glow=ctx.createLinearGradient(0,cap+(isTop?-32:32),0,cap);
    glow.addColorStop(0,"#e16a8f00");glow.addColorStop(1,rgb(...theme,.30));
    ctx.fillStyle=glow;ctx.fillRect(x,isTop?cap-32:cap,w,32);
    line(x+6,cap+(isTop?-1:1),x+w-6,cap+(isTop?-1:1),rgb(...theme,.85),1.4);
    line(x+8,cap+(isTop?-5:5),x+w-8,cap+(isTop?-5:5),"#ffd3e333",.7);
    ctx.restore();
  }
  function drawCookie(x,y){
    const bob=reduced?1:1+Math.sin(visualTime*4+x*.025)*.045;
    ctx.save();ctx.translate(x,y);ctx.scale(bob,bob);ctx.rotate(reduced?0:Math.sin(visualTime*2+x*.01)*.10);
    ctx.fillStyle=gradient(0,0,29,[[0,"#ffc27338"],[1,"#ffc27300"]]);ctx.fillRect(-30,-30,60,60);
    disk(0,1.6,11.8,"#70432a");disk(0,0,11.5,"#b57740");disk(0,-1,10.6,"#e2af70");
    const g=ctx.createLinearGradient(-7,-8,8,8);g.addColorStop(0,"#ffe0a2");g.addColorStop(1,"#c98242");disk(0,-1,9.4,g);
    for(const [dx,dy,r] of [[-4,-5,1.8],[4,-4,1.6],[-1,1,1.7],[-5,4,1.5],[5,5,1.8]]){disk(dx,dy+.5,r+.3,"#8d582d");disk(dx,dy,r,"#633721");}
    ctx.beginPath();ctx.arc(0,-1,9.2,3.5,5.1);ctx.strokeStyle="#fff0c68a";ctx.lineWidth=.8;ctx.stroke();
    ctx.restore();
  }
  function drawGravity(){
    if(!gravityMode(run.passed))return;
    const up=run.gravity<0,color=up?[102,224,239]:[187,148,255],edge=up?0:H;
    const g=ctx.createLinearGradient(0,edge,0,edge+(up?90:-90));
    g.addColorStop(0,rgb(...color,.23));g.addColorStop(1,rgb(...color,0));
    ctx.fillStyle=g;ctx.fillRect(0,up?0:H-90,W,90);
    line(0,up?2:H-2,W,up?2:H-2,rgb(...color,.82),1.8);
    const cy=up?25:H-25,dir=up?-1:1;
    for(let x=24;x<W;x+=52){
      line(x-4,cy-dir*3,x,cy+dir*3,rgb(...color,.55),1.1);
      line(x+4,cy-dir*3,x,cy+dir*3,rgb(...color,.55),1.1);
    }
    if(gravityPulse>.015&&!reduced){
      const y=up?H*gravityPulse:H*(1-gravityPulse);
      const wave=ctx.createLinearGradient(0,y-24,0,y+24);
      wave.addColorStop(0,rgb(...color,0));wave.addColorStop(.5,rgb(...color,.14*gravityPulse));wave.addColorStop(1,rgb(...color,0));
      ctx.fillStyle=wave;ctx.fillRect(0,y-24,W,48);
    }
    ctx.save();ctx.font="600 10px system-ui";ctx.textAlign="center";
    ctx.fillStyle=rgb(...color,.95);ctx.fillText((up?"↑  ":"↓  ")+(softMode(run.passed)?"SOFT GRAVITY":"GRAVITY"),W/2,up?45:H-39);ctx.restore();
  }
  function drawPlayer(y,distance){
    if(mode==="over"||mode==="revive"||(mode==="crash"&&crashTime>.12))return;
    const maxAge=.20+clamp((speedAt(run.time,run.passed)-125)/240,0,1)*.15;
    const list=trail.filter(t=>run.time-t.time<=maxAge);
    if(list.length>1&&!reduced&&mode!=="crash"){
      ctx.lineCap="round";ctx.lineJoin="round";
      for(let i=1;i<=list.length;i++){
        const a=list[i-1],b=list[i]||{y,d:distance},f=i/list.length,ax=X-(distance-a.d),bx=X-(distance-b.d);
        line(ax,a.y,bx,b.y,rgb(...skin().rgb,.055*f),5+22*f);
        line(ax,a.y,bx,b.y,rgb(...skin().rgb,.15*f),2+10*f);
        line(ax,a.y,bx,b.y,rgb(...skin().rgb,.52*f),.7+3.5*f);
      }
    }
    ctx.save();ctx.translate(X,y);
    const angle=bank,s=reduced?0:stretch*.19;
    ctx.rotate(angle);ctx.scale(1+s,1-s*.72);
    if(mode==="crash"){const z=Math.max(.01,1-crashTime/.12);ctx.scale(z,z);ctx.globalAlpha=z;}
    const sColor=skin(),halo=gradient(0,0,32,[[0,rgb(...sColor.rgb,.30)],[.4,rgb(...sColor.rgb,.15)],[1,rgb(...sColor.rgb,0)]]);
    ctx.fillStyle=halo;ctx.fillRect(-32,-32,64,64);
    const g=ctx.createLinearGradient(-8,-9,8,9);g.addColorStop(0,sColor.light);g.addColorStop(.38,sColor.mid);g.addColorStop(1,sColor.dark);
    disk(0,0,R+1,g);disk(0,0,5.5,"#160e1b");ctx.beginPath();ctx.arc(0,0,8.8,3.5,5.2);ctx.strokeStyle="#ffedf3ba";ctx.lineWidth=1.2;ctx.stroke();disk(-3,-6,1.05,"#fff0f3c5");if(coinPulse>.05){ctx.beginPath();ctx.arc(0,0,12+coinPulse*4,0,Math.PI*2);ctx.strokeStyle=rgb(255,211,141,coinPulse*.75);ctx.lineWidth=1.2;ctx.stroke();}
    ctx.restore();
  }
  function draw(alpha){
    const moving=mode==="play"||mode==="paused";
    const distance=mode==="play"?lerp(run.previousDistance,run.distance,alpha):run.distance;
    const y=mode==="play"?lerp(run.py,run.y,alpha):run.y;
    ctx.setTransform(scaleX,0,0,scaleY,0,0);ctx.clearRect(0,0,W,H);
    background(distance);
    ctx.save();
    const wobble=reduced?0:shake*3;
    ctx.translate(W/2+Math.sin(visualTime*93)*wobble,H/2+Math.cos(visualTime*79)*wobble);
    /* Keep the collision area fully visible; depth zoom is applied to the background. */
    ctx.translate(-W/2,-H/2);
    const t=mode==="play"?lerp(run.previousTime,run.time,alpha):run.time;
    for(const g of run.gates){
      const x=g.x-distance;
      if(x>W+20||x+g.width<-20)continue;
      for(const p of segments(g,t)){
        const px=x+p.offset,top=p.center-p.gap/2,bottom=p.center+p.gap/2;
        wall(px,-20,p.width,top+20,true,g.type,t);wall(px,bottom,p.width,H-bottom+20,false,g.type,t);
      }
      const shape=gateShape(g,t);
      if(!g.collected)drawCookie(x+g.width/2,shape.center);
      if(g.type!=="static"){
        const color=STAGES[g.stage].color;
        ctx.save();ctx.font="600 8px system-ui";ctx.textAlign="center";ctx.fillStyle=rgb(...color,.9);ctx.fillText(typeNames[g.type],x+g.width/2,shape.center-shape.gap/2-12);
        if(g.amp>0){const px=x+g.width+7,cy=shape.center;line(px,cy-12,px,cy+12,rgb(...color,.65));line(px,cy-12,px-3,cy-7,rgb(...color,.65));line(px,cy-12,px+3,cy-7,rgb(...color,.65));line(px,cy+12,px-3,cy+7,rgb(...color,.65));line(px,cy+12,px+3,cy+7,rgb(...color,.65));}
        if(g.squeeze>0){const cx=x+g.width/2,top=shape.center-shape.gap/2,bottom=shape.center+shape.gap/2;line(cx-5,top+6,cx,top+11,rgb(...color,.9));line(cx+5,top+6,cx,top+11,rgb(...color,.9));line(cx-5,bottom-6,cx,bottom-11,rgb(...color,.9));line(cx+5,bottom-6,cx,bottom-11,rgb(...color,.9));}
        ctx.restore();
      }
    }
    drawPlayer(y,distance);
    for(const p of particles){const f=p.life/p.max,s=p.size*(.45+.55*f),c=rgb(...p.color,f);if(p.shard&&!reduced){ctx.save();ctx.translate(p.x,p.y);ctx.rotate(p.angle);ctx.fillStyle=c;ctx.fillRect(-s/2,-s/2,s*1.9,s*.65);ctx.restore();}else disk(p.x,p.y,s,c);}
    for(const r of rings){const f=1-r.life/r.max;ctx.beginPath();ctx.arc(r.x,r.y,12+f*(r.size||43),0,Math.PI*2);ctx.strokeStyle=rgb(...r.color,(1-f)*.65);ctx.lineWidth=1.5;ctx.stroke();}
    for(const l of labels){ctx.font="600 13px system-ui";ctx.fillStyle=rgb(255,218,158,l.life/l.max);ctx.fillText("+1",l.x,l.y);}
    ctx.restore();
    const edges=ctx.createLinearGradient(0,0,0,H);
    edges.addColorStop(0,"#08080dbb");edges.addColorStop(.075,"#08080d00");edges.addColorStop(.925,"#08080d00");edges.addColorStop(1,"#08080dbb");
    ctx.fillStyle=edges;ctx.fillRect(0,0,W,H);
    line(0,1,W,1,"#ffffff19");line(0,H-1,W,H-1,"#ffffff19");drawGravity();
    if(impact>.01&&!reduced){ctx.fillStyle=rgb(255,35,71,impact*.10);ctx.fillRect(0,0,W,H);}
    if(nearFlash>.01&&!reduced){ctx.strokeStyle=rgb(255,133,163,nearFlash*.30);ctx.lineWidth=2;ctx.strokeRect(1,1,W-2,H-2); }
    if(moving||mode==="ready"){
      const v=mode==="ready"?1:speedAt(run.time,run.passed)/125,shown=v.toFixed(1)+"×",pace=Math.round(clamp((v-1)/1.92,0,1)*100);
      if(shown!==lastSpeed){paceNode.textContent=shown;lastSpeed=shown;}
      if(pace!==lastPace){meterNode.style.setProperty("--dot-pace",String(pace/100));lastPace=pace;}
    }
  }
  function resize(){
    if(!canvas)return;const rect=canvas.getBoundingClientRect(),dpr=Math.min(3,Math.max(1,window.devicePixelRatio||1));
    const width=Math.max(1,Math.round(rect.width*dpr)),height=Math.max(1,Math.round(rect.height*dpr));
    if(canvas.width!==width||canvas.height!==height){canvas.width=width;canvas.height=height;}
    scaleX=width/W;scaleY=height/H;
  }
  function tick(now){
    raf=0;if(!root?.isConnected){unmount();return;}
    const dt=last?Math.min(.05,Math.max(0,(now-last)/1000)):0;last=now;
    if(document.hidden){pause();return;}
    if(document.querySelector("dialog[open]")&&mode==="play")pause();
    if(mode==="play"){
      acc+=dt;
      while(acc>=STEP&&mode==="play"){simulate(STEP);acc-=STEP;}
    }else acc=0;
    pumpHouse();visual(dt);
    if(mode==="play"||mode==="crash"||now-renderAt>=1000/30){draw(clamp(acc/STEP,0,1));renderAt=now;}
    raf=requestAnimationFrame(tick);
  }
  function screen(){
    return '<section id="dot-root" class="dot-game" data-no-swipe><header class="dot-header"><button type="button" class="dot-back" data-tab="games" aria-label="Назад в игры"><svg viewBox="0 0 24 24"><path d="m15 5-7 7 7 7"/></svg></button><div class="dot-wordmark"><b>D<span>O</span>T</b><small data-dot-phase>FLOW</small></div><div class="dot-tools"><button type="button" class="dot-pause" aria-label="Пауза" disabled><svg viewBox="0 0 24 24"><path d="M9 5v14m6-14v14"/></svg></button><button type="button" class="dot-sound" aria-label="Выключить звук DOT" aria-pressed="false"><svg viewBox="0 0 24 24"><path d="M3 9v6h4l5 4V5L7 9Z"/><path class="dot-sound-waves" d="M16 9a4 4 0 0 1 0 6m2-9a8 8 0 0 1 0 12"/><path class="dot-sound-off" d="m16 9 5 6m0-6-5 6"/></svg></button></div></header><div class="dot-hud" aria-live="off"><div class="dot-stat"><span>ПЕЧЕНЬКИ</span><strong>🍪 <i data-dot-score>0</i></strong></div><div class="dot-stat dot-pace"><span>СКОРОСТЬ</span><strong data-dot-speed>1.0×</strong><i class="dot-meter" data-dot-meter></i></div><div class="dot-stat"><span>ПРОЙДЕНО</span><strong data-dot-passed>0</strong></div></div><div class="dot-field"><div class="dot-stage"><canvas width="360" height="500" tabindex="0" aria-label="Игровое поле DOT. Касание, пробел или стрелка вверх для прыжка."></canvas><div class="dot-stage-banner" hidden aria-live="polite"><small>НОВАЯ СТАДИЯ</small><strong></strong><span></span></div><section class="dot-results" hidden aria-label="Результат и рейтинг DOT"><div class="dot-results-body" aria-live="polite"></div><button type="button" class="dot-start dot-restart"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 11a8 8 0 1 1 2 6M4 4v7h7"/></svg>Играть снова</button><button type="button" class="dot-shop-open dot-shop-result">Магазин DOT</button><button type="button" class="dot-results-exit" data-tab="games">Вернуться к играм</button></section><div class="dot-overlay"><div class="dot-overlay-card"><span class="dot-emblem" aria-hidden="true"></span><strong></strong><small></small><button type="button" class="dot-start"></button><button type="button" class="dot-shop-open">Магазин DOT</button><div class="dot-revive-actions" hidden><button type="button" class="dot-start" data-dot-revive>♥ Использовать жизнь</button><button type="button" class="dot-revive-decline" data-dot-decline>Завершить полёт</button></div></div></div><section class="dot-shop-panel" hidden aria-label="Магазин DOT"><div class="dot-shop-head"><button type="button" class="dot-shop-close" aria-label="Закрыть магазин">‹</button><b>МАГАЗИН</b><strong class="dot-shop-balance">…</strong></div><small>Печеньки DOT · цвета и вторая жизнь</small><div class="dot-shop-items"></div><p class="dot-shop-status" role="status"></p></section></div></div></section>';
  }
  function mount(next){
    if(root===next&&root)return;unmount();if(!next)return;
    root=next;canvas=root.querySelector("canvas");ctx=canvas.getContext("2d");if(!ctx){root.textContent="Не удалось открыть игровое поле DOT";return;}
    hud=root.querySelector(".dot-hud");score=root.querySelector("[data-dot-score]");progress=root.querySelector("[data-dot-passed]");
    overlay=root.querySelector(".dot-overlay");title=overlay.querySelector("strong");detail=overlay.querySelector("small");button=overlay.querySelector("button");soundButton=root.querySelector(".dot-sound");pauseButton=root.querySelector(".dot-pause");paceNode=root.querySelector("[data-dot-speed]");meterNode=root.querySelector("[data-dot-meter]");stageNode=root.querySelector("[data-dot-phase]");stageBanner=root.querySelector(".dot-stage-banner");stageTitle=stageBanner.querySelector("strong");stageDescription=stageBanner.querySelector("span");results=root.querySelector(".dot-results");resultsBody=root.querySelector(".dot-results-body");restart=root.querySelector(".dot-restart");
    shopPanel=root.querySelector(".dot-shop-panel");shopBody=root.querySelector(".dot-shop-items");shopBalance=root.querySelector(".dot-shop-balance");shopStatus=root.querySelector(".dot-shop-status");shopState=null;shopOpen=shopBusy=false;skinId="red";
    viewId++;queuedTicket=null;ticketRequest=null;abort=new AbortController();const options={signal:abort.signal};reduced=motion();visualTime=renderAt=0;
    try{muted=localStorage.getItem("nora.dot.muted")==="1";}catch{muted=false;}
    soundButton.setAttribute("aria-pressed",String(muted));soundButton.setAttribute("aria-label",muted?"Включить звук DOT":"Выключить звук DOT");soundButton.classList.toggle("muted",muted);
    soundButton.addEventListener("click",()=>setMute(!muted),options);pauseButton.addEventListener("click",pause,options);
    canvas.addEventListener("pointerdown",e=>{if(e.isPrimary&&e.button===0){e.preventDefault();input();}},options);
    overlay.querySelector("[data-dot-revive]").addEventListener("click",e=>{e.stopPropagation();void useSecondLife();},options);
    overlay.querySelector("[data-dot-decline]").addEventListener("click",e=>{e.stopPropagation();endFlight();},options);
    overlay.addEventListener("click",()=>{if(!shopOpen)input();},options);restart.addEventListener("click",()=>input(),options);
    root.querySelectorAll(".dot-shop-open").forEach(el=>el.addEventListener("click",openShop,options));
    root.querySelector(".dot-shop-close").addEventListener("click",closeShop,options);shopBody.addEventListener("click",chooseSkin,options);
    document.addEventListener("keydown",e=>{
      if(shopOpen){if(e.code==="Escape"){e.preventDefault();closeShop();}return;}
      if(e.code==="Escape"&&mode==="play"&&!document.querySelector("dialog[open]")){e.preventDefault();pause();return;}
      if((e.code==="Space"||e.code==="ArrowUp")&&!e.repeat&&!e.target.closest?.("button,input,textarea,select,[contenteditable]")&&!document.querySelector("dialog[open]")){e.preventDefault();input();}
    },options);
    document.addEventListener("visibilitychange",()=>{if(document.hidden){pause();cancelAnimationFrame(raf);raf=0;}else if(root&&!raf){last=0;raf=requestAnimationFrame(tick);}},options);
    window.addEventListener("blur",pause,options);
    if(window.ResizeObserver){observer=new ResizeObserver(resize);observer.observe(canvas);}
    else window.addEventListener("resize",resize,options);
    reset();resize();draw(0);prepareIntro();primeTicket();void refreshShop();raf=requestAnimationFrame(tick);
  }
  function unmount(){
    closeIntro(false);closeShop();shopPanel=shopBody=shopBalance=shopStatus=null;shopState=null;viewId++;flightId++;clearTimeout(connectTimer);connectTimer=0;initialStartPending=false;queuedTicket=null;ticketRequest=null;cancelAnimationFrame(raf);raf=0;abort?.abort();abort=null;observer?.disconnect();observer=null;
    stopHouse(true);if(audio){const old=audio;audio=null;master=null;noiseBuffer=null;try{void old.close().catch(()=>{});}catch{}}
    root=canvas=ctx=null;last=acc=0;particles=[];rings=[];labels=[];trail=[];
  }
  return {screen,mount,unmount,createRun,stepSeconds:STEP,speedAt,stageAt,gateShape,segments,witnessFor};
})();
