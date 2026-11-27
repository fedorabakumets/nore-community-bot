'use strict';
window.NoraBurrow = (() => {
  const path='nora-game/burrow';
  const groups={wear:NoraI18n.t("Внешность"),decor:NoraI18n.t("Интерьер"),record:NoraI18n.t("Пластинки")};
  const spots=[NoraI18n.t("У дальней стены слева"),NoraI18n.t("У дальней стены справа"),NoraI18n.t("У левой стены"),NoraI18n.t("У правой стены"),NoraI18n.t("Слева от центра"),NoraI18n.t("Справа от центра"),NoraI18n.t("Слева от входа"),NoraI18n.t("Справа от входа")];
  let catalog;
  function el(tag,content,cls){
    const node=document.createElement(tag);if(content)node.textContent=content;if(cls)node.className=cls;return node;
  }
  function mount(root,me,{reset,enter,changed,equip,where,returnToLobby,housesChanged}){
    const panel=el('dialog',null,'nora-burrow');panel.setAttribute('aria-label',NoraI18n.t("Мастерская норы"));
    const head=el('header'),title=el('h2'),balance=el('small'),tabs=el('div',null,'burrow-tabs'),list=el('div',null,'burrow-list'),status=el('p');
    status.setAttribute('role','status');root.append(panel);panel.append(head,tabs,list,status);
    function button(label,fn,cls){
      const b=el('button',label,cls);b.type='button';b.onclick=()=>run(fn);return b;
    }
    head.append(title,balance,button(NoraI18n.t("Закрыть"),()=>panel.close()));
    const homeButton=button(NoraI18n.t("Моя нора"),()=>open('home'),'nora-world-outfit burrow-manage');
    homeButton.hidden=true;root.querySelector('.nora-world-bar').append(homeButton);
    let view='',group='decor',own,home,host=null,loading=false,polling=false,next=0,serial=0,dead=false,search='',offset=0,dirVersion=0;
    let trailAt=0,trailPending=null,trailRevision='';
    const request=(body,query='',timeout=7000)=>api(path+query,body,AbortSignal.timeout(timeout));
    async function run(fn){
      if(loading||dead)return;loading=true;panel.setAttribute('aria-busy','true');
      try{await fn();}catch(error){if(!dead){if(panel.open)status.textContent=error.message;else toast(error.message);}}
      finally{loading=false;panel.removeAttribute('aria-busy');}
    }
    function apply(data){
      if(dead)return;
      if(data.inventory){own=data;equip(data.inventory.wear);}
      if(data.host===host){home=data.home;changed(home,host,catalog);}
    }
    async function items(){
      if(!catalog){
        const r=await fetch('/nora-burrow-items.json?v=burrows');if(!r.ok)throw Error(NoraI18n.t("Каталог пока недоступен."));
        catalog=await r.json();
      }
    }
    async function refresh(){
      const seq=++serial,target=host;
      const data=await request(undefined,target&&target!==me?'?host='+encodeURIComponent(target):'');
      if(seq===serial&&!dead)apply(data);
    }
    async function go(name){
      await items();
      const data=await request(undefined,'?host='+encodeURIComponent(name));
      if(dead)return;
      if(!where())throw Error(NoraI18n.t("Сначала вернись в лобби или свою нору."));
      ++serial;host=data.host;enter(host);apply(data);next=performance.now()+2400;
      if(panel.open)panel.close();
    }
    async function knock(name){
      try{
        await request({action:'knock',target:name});
        if(!dead)toast(NoraI18n.t("Стук услышит ")+name+NoraI18n.t(" в игровом чате."));
      }finally{
        trailAt=0;
      }
    }
    function refreshTrail(time,force=false){
      if(!housesChanged)return;
      if(trailPending)return trailPending;
      if(!force&&time<trailAt)return;
      trailAt=time+12000;
      trailPending=request(undefined,'?trail=1',2500).then(({houses})=>{
        if(dead)return;
        const revision=JSON.stringify(houses);
        if(revision===trailRevision)return;
        trailRevision=revision;housesChanged(houses);
      }).catch(()=>{trailAt=time+3000;}).finally(()=>{trailPending=null;});
      return trailPending;
    }
    function leave(){
      ++serial;host=null;home=null;homeButton.hidden=true;changed(null,null,catalog);
    }
    async function exit(){
      const current=host;
      await refreshTrail(performance.now(),true);
      if(dead||current!==host)return;
      leave();returnToLobby(current);
    }
    function render(){
      tabs.replaceChildren();list.replaceChildren();status.textContent='';
      title.textContent=view==='shop'?NoraI18n.t("Лавка у портала"):view==='deck'?NoraI18n.t("Проигрыватель «Волна»"):NoraI18n.t("Моя нора");
      balance.textContent=view==='shop'?own.balance+' 🍪':'';
      if(view==='home')tabs.append(button(NoraI18n.t("Пригласить игрока"),directory));
      if(view!=='deck')for(const [id,label] of Object.entries(groups)){
        const tab=button(label,()=>{group=id;render();});tab.setAttribute('aria-pressed',String(group===id));tabs.append(tab);
      }
      const state=own.inventory;
      for(const item of catalog.filter(i=>i.group===(view==='deck'?'record':group))){
        const has=state.owned.includes(item.id);if(view!=='shop'&&!has)continue;
        const row=el('article'),picture=el('canvas'),copy=el('div'),actions=el('div',null,'burrow-actions');
        picture.width=picture.height=56;picture.setAttribute('aria-hidden','true');window.NoraBurrowModels.icon(picture,item);
        copy.append(el('strong',NoraI18n.t(item.name)),el('small',NoraI18n.t(item.description)));row.append(picture,copy,actions);list.append(row);
        const act=(label,action,fields={})=>button(label,async()=>{
          ++serial;const data=await request({action,item:item.id,...fields});++serial;apply(data);
          if(dead)return;render();status.textContent=action==='buy'?NoraI18n.t("Куплено · ")+item.name:NoraI18n.t("Сохранено · ")+NoraI18n.t(item.name);
        });
        if(!has){actions.append(act(item.price+NoraI18n.t(" 🍪 · Купить"),'buy'));continue;}
        if(item.group==='wear'){const worn=state.wear===item.id;actions.append(act(worn?NoraI18n.t("Снять"):NoraI18n.t("Надеть"),worn?'remove':'wear'));}
        if(item.group==='decor'){
          const selected=Object.keys(state.layout).find(k=>state.layout[k]===item.id);
          const select=el('select');select.setAttribute('aria-label',NoraI18n.t("Место · ")+NoraI18n.t(item.name));
          for(const [i,label] of spots.entries()){
            const used=state.layout[i],name=catalog.find(p=>p.id===used)?.name;
            select.add(new Option(label+(name?' · '+name:''),String(i)));
          }
          select.value=selected??String(spots.findIndex((_,i)=>!state.layout[i]));if(select.selectedIndex<0)select.selectedIndex=0;
          const place=button(selected===undefined?NoraI18n.t("Поставить"):NoraI18n.t("Переставить"),async()=>{
            ++serial;const data=await request({action:'place',item:item.id,slot:Number(select.value)});++serial;apply(data);render();status.textContent=NoraI18n.t("Поставлено · ")+NoraI18n.t(item.name);
          });
          actions.append(select,place);if(selected!==undefined)actions.append(act(NoraI18n.t("Убрать"),'place',{slot:null}));
        }
        if(item.group==='record'){
          const active=state.record===item.id;
          if(Object.values(state.layout).includes('hifi'))actions.append(act(active?NoraI18n.t("Остановить"):NoraI18n.t("Поставить пластинку"),active?'stop':'play'));
          else actions.append(el('small',NoraI18n.t("Куплено · поставь проигрыватель «Волна»")));
        }
      }
      if(!list.children.length)list.append(el('p',NoraI18n.t("Здесь появятся покупки из лавки на спавне.")));
    }
    function show(){
      reset();if(!panel.open)panel.showModal();status.textContent='';list.scrollTop=0;
    }
    async function open(mode){
      view=mode;group=mode==='shop'?'wear':'decor';show();title.textContent=NoraI18n.t("Мастерская");list.replaceChildren();tabs.replaceChildren();
      status.textContent=NoraI18n.t("Загрузка…");await items();
      const data=await request();if(dead)return;apply(data);render();
    }
    async function directory(){
      view='invite';show();title.textContent=NoraI18n.t("Пригласить в свою нору");
      balance.textContent='';tabs.replaceChildren();search='';offset=0;
      const form=el('form'),field=el('input'),submit=el('button',NoraI18n.t("Найти"));field.type='search';field.placeholder=NoraI18n.t("Ник игрока");field.setAttribute('aria-label',NoraI18n.t("Ник игрока"));field.maxLength=16;
      form.append(field,submit);tabs.append(form);
      async function page(){
        const v=++dirVersion;
        const result=await request(undefined,'?'+new URLSearchParams({directory:'1',q:search,offset}));
        if(dead||v!==dirVersion||view!=='invite')return;
        list.replaceChildren();status.textContent='';
        for(const {name,online} of result.players){
          const row=el('article'),copy=el('div');copy.append(el('strong',name),el('small',online?NoraI18n.t("Сейчас в игре"):NoraI18n.t("Сейчас вне игры")));
          const send=button(NoraI18n.t("Пригласить"),async()=>{
            await request({action:'invite',target:name});send.disabled=true;send.textContent=NoraI18n.t("Отправлено");
            status.textContent=NoraI18n.t("Сообщение для ")+name+NoraI18n.t(" в игровом чате · 10 минут на ответ.");
          });row.append(copy,send);list.append(row);
        }
        if(!result.players.length)list.append(el('p',NoraI18n.t("Игроки не найдены.")));
        if(offset>0)list.append(button(NoraI18n.t("Назад"),()=>{offset-=40;return page();}));
        if(result.more)list.append(button(NoraI18n.t("Далее"),()=>{offset+=40;return page();}));
      }
      form.onsubmit=e=>{e.preventDefault();search=field.value.trim();offset=0;run(page);};await page();
    }
    async function respond(note,action){
      if(action==='enter'){await go(note.other);await request({action:'dismiss',id:note.id});return;}
      if(note.kind==='invite'&&action==='accept'&&!where())throw Error(NoraI18n.t("Вернись в лобби и прими приглашение."));
      const data=await request({action,id:note.id});
      if(data.enter)await go(data.enter);
    }
    return {
      open,go,knock,respond,exit,run,host:()=>host,home:()=>home,
      switchLamp:async()=>{apply(await request({action:'light',item:'lamp',lit:!home.lamp}));},
      burst:()=>request({action:'burst',target:host}),
      panelOpen:()=>panel.open,
      tick(time,inside){
        refreshTrail(time);
        homeButton.hidden=!inside||host!==me;
        if(!inside||!host||time<next||polling||loading)return;
        const current=host;
        next=time+2400;polling=true;
        refresh().catch(error=>{
          if(!dead&&host===current&&current!==me&&(error.serverMessage || error.message)==='Сначала получи приглашение хозяина.'){
            if(panel.open)panel.close();exit();toast(NoraI18n.t("Визит завершён. Ты вышел из норы."));
          }
        }).finally(()=>{polling=false;});
      },
      dispose(){dead=true;++serial;++dirVersion;panel.remove();homeButton.remove();}
    };
  }
  return {mount};
})();
