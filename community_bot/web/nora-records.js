'use strict';
window.NoraRecords = (() => {
  const catalog = {
    standard: {name:'Standard Music',url:'/game/nora-theme.mp3'},
    dedzytwo: {name:NoraI18n.t("Музыкальная пластинка «?» — dedzytwo"),url:'/game/dedzytwo-s1.mp3'},
  };
  const giftIcon = '<svg viewBox="0 0 32 32" shape-rendering="crispEdges" aria-hidden="true"><path fill="#160d16" d="M5 12h22v17H5zM3 9h26v7H3zM8 1h6v3h4V1h6v3h3v5H5V4h3z"/><path fill="#e64a57" d="M6 16h20v11H6zM4 10h24v4H4zM9 2h4v3h-4zM19 2h4v3h-4zM6 5h4v3H6zM22 5h4v3h-4z"/><path fill="#9c243e" d="M23 16h3v11h-3zM6 25h20v2H6z"/><path fill="#ffd39a" d="M14 9h4v18h-4zM10 5h4v3h-4zM18 5h4v3h-4z"/><path fill="#fff0cb" d="M14 9h2v18h-2z"/></svg>';
  let coverUrl='/game/dedzytwo-cover.png';
  function drawCover(ctx,image) {
    const side=Math.min(image.width,image.height);
    ctx.drawImage(image,(image.width-side)/2,(image.height-side)/2,side,side,0,0,48,48);
    const letters={d:['001','001','111','101','101','101','111'],e:['000','000','111','101','111','100','111'],z:['000','000','111','001','010','100','111'],y:['000','000','101','101','111','001','110'],t:['010','010','111','010','010','010','011'],w:['000','000','101','101','111','111','101'],o:['000','000','111','101','101','101','111']};
    const pixels=[];
    [...'dedzytwo'].forEach((letter,i)=>letters[letter].forEach((row,y)=>[...row].forEach((pixel,x)=>{if(pixel==='1')pixels.push([8+i*4+x,30+y]);})));
    ctx.fillStyle='#1b101a';
    for(const [x,y] of pixels)for(let dy=-1;dy<=1;dy++)for(let dx=-1;dx<=1;dx++)ctx.fillRect(x+dx,y+dy,1,1);
    ctx.fillStyle='#fff1db';
    for(const [x,y] of pixels)ctx.fillRect(x,y,1,1);
  }
  const cover=new Image();
  cover.onload=()=>{
    const canvas=document.createElement('canvas');canvas.width=canvas.height=48;
    drawCover(canvas.getContext('2d'),cover);
    coverUrl=canvas.toDataURL();document.querySelectorAll('[data-record-cover]').forEach(img=>img.src=coverUrl);
  };
  cover.src=coverUrl;
  function art(id='dedzytwo') {
    return `<div class="nora-vinyl-art ${id==='standard'?'nora-vinyl-standard':''}" aria-hidden="true"><div class="nora-vinyl-sleeve">${id==='dedzytwo'?`<img data-record-cover src="${coverUrl}" alt="">`:'<span>STANDARD<br>MUSIC</span>'}</div><div class="nora-vinyl-disc"><i></i></div></div>`;
  }
  function mount(root, scenery, sounds, reset) {
    let state=null, busy=false, loading=false, disposed=false, nearShelf=false, nearPlayer=false, inLobby=false;
    let deck=null, nextSync=0, syncing=false, activeTrack, activeLobby;
    const controls=new AbortController();
    const inventory=document.createElement('button');
    inventory.type='button';inventory.className='nora-world-outfit nora-world-inventory';
    inventory.textContent=NoraI18n.t("Инвентарь");inventory.dataset.recordInventory='';
    root.querySelector('.nora-world-bar').append(inventory);
    const panel=document.createElement('dialog');panel.className='nora-pet-panel nora-record-panel';panel.setAttribute('aria-label',NoraI18n.t("Пластинки и инвентарь"));
    root.append(panel);
    let homeTrack, visiting=false;
    function track(){
      const id=inLobby?deck?.record:homeTrack||(visiting?null:state?.player);
      if(id===activeTrack&&inLobby===activeLobby)return;
      activeTrack=id;activeLobby=inLobby;sounds?.record?.(id?(catalog[id]?.url||homeTrack):null,inLobby);
    }
    function applyDeck(next){
      if(deck&&deck.revision>=next.revision)return;
      const returned=deck?.mine&&deck.record&&!next.record;
      deck=next;scenery.setLobbyRecord(next.record);track();
      if(returned)load();
    }
    async function syncDeck(){
      if(syncing)return;
      syncing=true;nextSync=Date.now()+1500;
      try{
        const next=await api('nora-game/records?room=lobby',undefined,AbortSignal.timeout(3000));
        if(!disposed)applyDeck(next);
      }catch{}finally{syncing=false;}
    }
    function apply(next) {
      state=next;scenery.setRecords?.(state);
      if(next.lobby_deck)applyDeck(next.lobby_deck);
      track();
    }
    async function load() {
      if(loading||disposed)return;
      loading=true;syncInventory();
      try {
        const next=await api('nora-game/records');if(disposed)return;apply(next);
        if(root.dataset.recordGift==='1'){
          delete root.dataset.recordGift;
          if(!state.claimed)await change('claim');
          if(!disposed)showGift();
        }
      }catch(error){if(!disposed)toast(error.message);}
      finally{loading=false;if(!disposed)syncInventory();}
    }
    async function change(action,record,slot) {
      if(busy||!state)return false;
      busy=true;panel.querySelectorAll('button').forEach(b=>b.disabled=true);syncInventory();
      try {
        const next=await api('nora-game/records',{action,record,slot,revision:state.revision,deck_revision:deck?.revision});
        if(disposed)return false;apply(next);return true;
      }catch(error){
        try{const next=await api('nora-game/records');if(!disposed)apply(next);}catch{}
        if(!disposed){
          if(action.startsWith('lobby_'))syncDeck();
          if(panel.open&&panel.dataset.view==='inventory')showInventory();
          else if(panel.open&&action!=='claim')showShelf();
          const message=panel.open?panel.querySelector('[role="status"]'):null;
          if(message)message.textContent=error.message;else toast(error.message);
        }
        return false;
      }finally{busy=false;if(!disposed){panel.querySelectorAll('button').forEach(b=>{
        if(b.hasAttribute('data-record-slot'))b.disabled=Boolean(state.inventory[Number(b.dataset.recordSlot)])===Boolean(state.hand);
        else b.disabled=b.hasAttribute('data-record-take')&&!!state?.hand;
      });syncInventory();}}
    }
    function openPanel(html) {reset();panel.innerHTML=html;if(!panel.open)panel.showModal();panel.querySelector('button')?.focus();}
    function showGift() {
      panel.dataset.view='gift';
      const claimed=state?.claimed;
      openPanel(`${art()}<p class="nora-record-season">SEASON 1 • BLOODY NORA</p><h2>${catalog.dedzytwo.name}</h2><p>${claimed?NoraI18n.t("Твоя пластинка уже в коллекции. Найди стеллаж у дальней стены таверны."):NoraI18n.t("Забери подарок и поставь пластинку на полку таверны.")}</p><p role="status"></p>${claimed?'':("<button data-record-claim>" + NoraI18n.html("Забрать пластинку") + "</button>")}<button data-record-close>${NoraI18n.html("Войти в мир")}</button>`);
    }
    function showShelf() {
      panel.dataset.view='shelf';
      openPanel(`<p class="nora-record-season">${NoraI18n.html("ТАВЕРНА / КОЛЛЕКЦИЯ")}</p><h2>${NoraI18n.html("Пластинки")}</h2><div class="nora-record-shelf-list">${state.shelf.map(id=>`<button data-record-take="${id}" ${state.hand?'disabled':''}>${art(id)}<span>${catalog[id].name}</span><small>${state.hand?NoraI18n.t("Сначала освободи руки"):NoraI18n.t("Взять с полки")}</small></button>`).join('')||("<p>" + NoraI18n.html("Полка пока пуста.") + "</p>")}</div>${state.hand?("<button data-record-store>" + NoraI18n.html("Поставить пластинку из рук") + "</button>"):''}<p class="nora-record-future">${NoraI18n.html("ТРОФЕИ · СКОРО")}<br>${NoraI18n.html("ДРУГИЕ НАХОДКИ · СКОРО")}</p><p role="status"></p><button data-record-close>${NoraI18n.html("Вернуться в таверну")}</button>`);
    }
    function showInventory(){
      panel.dataset.view='inventory';
      const slots=state.inventory.map((id,slot)=>{
        const name=id?catalog[id].name:NoraI18n.t("пусто");
        return `<button type="button" data-record-slot="${slot}" aria-label="${NoraI18n.html("Клетка")} ${slot+1}: ${name}"
          title="${name}" ${Boolean(id)===Boolean(state.hand)?'disabled':''}>${id?art(id):`<span>${slot+1}</span>`}</button>`;
      }).join('');
      const hint=state.hand?`${NoraI18n.t("В руках:")} ${catalog[state.hand].name}${NoraI18n.t(". Выбери свободную клетку.")}`:NoraI18n.t("Нажми на пластинку, чтобы взять её в руки.");
      openPanel(`<p class="nora-record-season">${NoraI18n.html("СУМКА /")} ${state.inventory.filter(Boolean).length} ${NoraI18n.html("ИЗ")} ${state.inventory.length}</p>
        <h2>${NoraI18n.html("Инвентарь")}</h2><p>${hint}</p><div class="nora-inventory-grid">${slots}</div>
        <p role="status"></p><button data-record-close>${NoraI18n.html("Закрыть")}</button>`);
    }
    function syncInventory(){inventory.disabled=loading||busy;}
    const shelfAction={id:'shelf',text:NoraI18n.t("Пластинки"),run:showShelf};
    function playerAction() {
      if(!state||busy||panel.open||!nearPlayer)return null;
      const id=inLobby?deck?.record:state.player;
      const canInsert=state.hand&&(!inLobby||(deck&&!id));
      const canEject=id&&(inLobby?deck.mine&&(!state.hand||state.inventory.includes(null)):!state.hand);
      if(canInsert)return {id:'insert',text:NoraI18n.t("Вставить пластинку"),run:()=>change(inLobby?'lobby_insert':'insert')};
      if(canEject)return {id:'eject',text:NoraI18n.t("Достать пластинку"),run:()=>change(inLobby?'lobby_eject':'eject')};
      return null;
    }
    async function click(e) {
      const button=e.target.closest('button');if(!button||busy)return;
      if(button.hasAttribute('data-record-inventory')){
        if(!state)await load();
        if(!disposed&&state&&!panel.open)showInventory();
        return;
      }
      if(button.hasAttribute('data-record-slot')&&panel.open){
        const slot=Number(button.dataset.recordSlot);
        if(await change(state.hand?'pack':'unpack',undefined,slot)&&panel.open)showInventory();
        return;
      }
      if(button.hasAttribute('data-record-close')){panel.close();reset();return;}
      let action=null,record;
      if(button.hasAttribute('data-record-claim'))action='claim';
      if(button.hasAttribute('data-record-take')&&nearShelf){action='take';record=button.dataset.recordTake;}
      if(button.hasAttribute('data-record-store')&&nearShelf)action='store';
      if(action&&await change(action,record)){
        if(action==='take'||action==='store'){panel.close();reset();}
        if(action==='claim')showGift();
      }
    }
    root.addEventListener('click',click,{signal:controls.signal});
    panel.addEventListener('close',reset,{signal:controls.signal});
    load();
    return {
      refresh:load,
      homeMusic(url,guest){homeTrack=url;visiting=guest;track();},
      panelOpen:()=>panel.open,
      hasRecord:()=>!!state?.player,
      lobbyPlaying:()=>!!deck?.playing,
      canToggleLobby:()=>!!deck?.mine,
      toggleLobby:()=>change('lobby_toggle'),
      shelfAction:()=>state&&!busy&&!panel.open&&nearShelf?shelfAction:null,
      playerAction,
      isBusy:()=>busy,
      update(inside,x,z,grounded,blocked,lobby,nearLobbyDeck) {
        if(inLobby!==lobby){
          inLobby=lobby;nextSync=0;track();
        }
        if(inLobby&&Date.now()>=nextSync)syncDeck();
        const available=inside&&grounded&&!blocked;
        const shelf=available&&Math.hypot(x-.1,z+4.4)<1.9;
        const player=(available&&Math.hypot(x,z)<1.8)||(inLobby&&nearLobbyDeck&&!blocked);
        nearShelf=shelf;nearPlayer=player;
      },
      dispose(){disposed=true;controls.abort();panel.remove();inventory.remove();},
    };
  }
  return {mount,art,drawCover,giftIcon,catalog};
})();
