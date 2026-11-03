'use strict';
window.NoraRecords = (() => {
  const catalog = {
    standard: {name:'Standard Music',url:'/game/nora-theme.mp3'},
    dedzytwo: {name:'Музыкальная пластинка «?» — dedzytwo',url:'/game/dedzytwo-s1.mp3'},
  };
  const giftIcon = '<svg viewBox="0 0 32 32" shape-rendering="crispEdges" aria-hidden="true"><path fill="#160d16" d="M5 12h22v17H5zM3 9h26v7H3zM8 1h6v3h4V1h6v3h3v5H5V4h3z"/><path fill="#e64a57" d="M6 16h20v11H6zM4 10h24v4H4zM9 2h4v3h-4zM19 2h4v3h-4zM6 5h4v3H6zM22 5h4v3h-4z"/><path fill="#9c243e" d="M23 16h3v11h-3zM6 25h20v2H6z"/><path fill="#ffd39a" d="M14 9h4v18h-4zM10 5h4v3h-4zM18 5h4v3h-4z"/><path fill="#fff0cb" d="M14 9h2v18h-2z"/></svg>';
  let coverUrl='/game/dedzytwo-cover.png';
  function drawCover(ctx,image) {
    const side=Math.min(image.width,image.height);
    ctx.drawImage(image,(image.width-side)/2,(image.height-side)/2,side,side,0,0,48,48);
    const letters={d:['001','001','111','101','101','101','111'],e:['000','000','111','101','111','100','111'],z:['000','000','111','001','010','100','111'],y:['000','000','101','101','111','001','110'],t:['010','010','111','010','010','010','011'],w:['000','000','101','101','111','111','101'],o:['000','000','111','101','101','101','111']};
    ctx.fillStyle='#1b101a';ctx.fillRect(0,38,48,10);
    ctx.fillStyle='#fff1db';
    [...'dedzytwo'].forEach((letter,i)=>letters[letter].forEach((row,y)=>[...row].forEach((pixel,x)=>{if(pixel==='1')ctx.fillRect(8+i*4+x,40+y,1,1);})));
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
    let state=null, busy=false, disposed=false, nearShelf=false, nearPlayer=false;
    const controls=new AbortController();
    const actions=document.createElement('div');actions.className='nora-record-actions';actions.hidden=true;
    const held=document.createElement('p');held.className='nora-record-held';held.hidden=true;
    const panel=document.createElement('dialog');panel.className='nora-pet-panel nora-record-panel';panel.setAttribute('aria-label','Коллекция пластинок');
    (root.querySelector('.nora-world-context')||root).append(actions,held);root.append(panel);
    function apply(next) {
      state=next;scenery.setRecords?.(state);
      sounds?.record?.(state.player?catalog[state.player].url:null);
      held.textContent=state.hand?'В руках: '+catalog[state.hand].name:'';held.hidden=!state.hand;
      renderActions();
    }
    async function load() {
      try {
        const next=await api('nora-game/records');if(disposed)return;apply(next);
        if(root.dataset.recordGift==='1'){
          delete root.dataset.recordGift;
          if(!state.claimed)await change('claim');
          if(!disposed)showGift();
        }
      }catch(error){if(!disposed){held.hidden=false;held.textContent=error.message;actions.hidden=false;actions.innerHTML='<button data-record-reload>Загрузить пластинки</button>';}}
    }
    async function change(action,record) {
      if(busy||!state)return false;
      busy=true;panel.querySelectorAll('button').forEach(b=>b.disabled=true);renderActions();
      try {
        const next=await api('nora-game/records',{action,record,revision:state.revision});
        if(disposed)return false;apply(next);return true;
      }catch(error){
        try{const next=await api('nora-game/records');if(!disposed)apply(next);}catch{}
        if(!disposed){
          if(panel.open&&action!=='claim')showShelf();
          const message=panel.open?panel.querySelector('[role="status"]'):null;
          if(message)message.textContent=error.message;else {held.hidden=false;held.textContent=error.message;}
        }
        return false;
      }finally{busy=false;if(!disposed){panel.querySelectorAll('button').forEach(b=>b.disabled=b.hasAttribute('data-record-take')&&!!state?.hand);renderActions();}}
    }
    function openPanel(html) {reset();panel.innerHTML=html;panel.showModal();renderActions();panel.querySelector('button')?.focus();}
    function showGift() {
      const claimed=state?.claimed;
      openPanel(`${art()}<p class="nora-record-season">SEASON 1 • BLOODY NORA</p><h2>${catalog.dedzytwo.name}</h2><p>${claimed?'Твоя пластинка уже в коллекции. Найди стеллаж у дальней стены таверны.':'Забери подарок и поставь пластинку на полку таверны.'}</p><p role="status"></p>${claimed?'':'<button data-record-claim>Забрать пластинку</button>'}<button data-record-close>Войти в мир</button>`);
    }
    function showShelf() {
      openPanel(`<p class="nora-record-season">ТАВЕРНА / КОЛЛЕКЦИЯ</p><h2>Пластинки</h2><div class="nora-record-shelf-list">${state.shelf.map(id=>`<button data-record-take="${id}" ${state.hand?'disabled':''}>${art(id)}<span>${catalog[id].name}</span><small>${state.hand?'Сначала освободи руки':'Взять с полки'}</small></button>`).join('')||'<p>Полка пока пуста.</p>'}</div>${state.hand?'<button data-record-store>Поставить пластинку из рук</button>':''}<p class="nora-record-future">ТРОФЕИ · СКОРО<br>ДРУГИЕ НАХОДКИ · СКОРО</p><p role="status"></p><button data-record-close>Вернуться в таверну</button>`);
    }
    function renderActions() {
      actions.hidden=!state||panel.open||(!nearShelf&&!nearPlayer);
      if(!state)return;
      actions.innerHTML=`${nearPlayer&&state.player?`<small class="nora-record-now">${catalog[state.player].name}</small>`:''}${nearShelf?'<button data-record-shelf>Стеллаж · пластинки</button>':''}${nearPlayer&&state.hand?'<button data-record-insert>Вставить пластинку</button>':''}${nearPlayer&&state.player&&!state.hand?'<button data-record-eject>Достать пластинку</button>':''}`;
      actions.querySelectorAll('button').forEach(b=>b.disabled=busy);
    }
    async function click(e) {
      const button=e.target.closest('button');if(!button||busy)return;
      if(button.hasAttribute('data-record-close')){panel.close();reset();renderActions();return;}
      if(button.hasAttribute('data-record-reload')){load();return;}
      if(button.hasAttribute('data-record-shelf')&&nearShelf){showShelf();return;}
      let action=null,record;
      if(button.hasAttribute('data-record-claim'))action='claim';
      if(button.hasAttribute('data-record-take')&&nearShelf){action='take';record=button.dataset.recordTake;}
      if(button.hasAttribute('data-record-store')&&nearShelf)action='store';
      if(button.hasAttribute('data-record-insert')&&nearPlayer)action='insert';
      if(button.hasAttribute('data-record-eject')&&nearPlayer)action='eject';
      if(action&&await change(action,record)){
        if(action==='take'||action==='store'){panel.close();reset();}
        if(action==='claim')showGift();
      }
    }
    root.addEventListener('click',click,{signal:controls.signal});
    panel.addEventListener('close',()=>{reset();renderActions();},{signal:controls.signal});
    load();
    return {
      panelOpen:()=>panel.open,
      hasRecord:()=>!!state?.player,
      update(inside,x,z,grounded,blocked) {
        const available=inside&&grounded&&!blocked;
        const shelf=available&&Math.hypot(x-.1,z+4.4)<1.9;
        const player=available&&Math.hypot(x,z)<1.8;
        if(shelf!==nearShelf||player!==nearPlayer){nearShelf=shelf;nearPlayer=player;renderActions();}
      },
      dispose(){disposed=true;controls.abort();panel.remove();actions.remove();held.remove();},
    };
  }
  return {mount,art,drawCover,giftIcon,catalog};
})();
