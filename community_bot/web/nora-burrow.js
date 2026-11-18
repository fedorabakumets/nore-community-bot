'use strict';
window.NoraBurrow = (() => {
  const path='nora-game/burrow';
  const groups={wear:'Внешность',decor:'Интерьер',record:'Пластинки'};
  const spots=['У дальней стены слева','У дальней стены справа','У левой стены','У правой стены','Слева от центра','Справа от центра','Слева от входа','Справа от входа'];
  let catalog;
  function el(tag,content,cls){
    const node=document.createElement(tag);if(content)node.textContent=content;if(cls)node.className=cls;return node;
  }
  function mount(root,me,{reset,enter,changed,equip,where,returnToLobby}){
    const panel=el('dialog',null,'nora-burrow');panel.setAttribute('aria-label','Мастерская норы');
    const head=el('header'),title=el('h2'),balance=el('small'),tabs=el('div',null,'burrow-tabs'),list=el('div',null,'burrow-list'),status=el('p');
    status.setAttribute('role','status');root.append(panel);panel.append(head,tabs,list,status);
    function button(label,fn,cls){
      const b=el('button',label,cls);b.type='button';b.onclick=()=>run(fn);return b;
    }
    head.append(title,balance,button('Закрыть',()=>panel.close()));
    const homeButton=button('Моя нора',()=>open('home'),'nora-world-outfit burrow-manage');
    homeButton.hidden=true;root.querySelector('.nora-world-bar').append(homeButton);
    let view='',group='decor',own,home,host=null,loading=false,polling=false,next=0,serial=0,dead=false,search='',offset=0,dirVersion=0;
    const request=(body,query='')=>api(path+query,body,AbortSignal.timeout(7000));
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
        const r=await fetch('/nora-burrow-items.json?v=burrows');if(!r.ok)throw Error('Каталог пока недоступен.');
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
      if(!where())throw Error('Сначала вернись в лобби или свою нору.');
      ++serial;host=data.host;enter(host);apply(data);next=performance.now()+2400;
      if(panel.open)panel.close();
    }
    function leave(){
      ++serial;host=null;home=null;homeButton.hidden=true;changed(null,null,catalog);
    }
    function render(){
      tabs.replaceChildren();list.replaceChildren();status.textContent='';
      title.textContent=view==='shop'?'Лавка у портала':view==='deck'?'Проигрыватель «Волна»':'Моя нора';
      balance.textContent=view==='shop'?own.balance+' 🍪':'';
      if(view==='home')tabs.append(button('Пригласить игрока',()=>directory(true)));
      if(view!=='deck')for(const [id,label] of Object.entries(groups)){
        const tab=button(label,()=>{group=id;render();});tab.setAttribute('aria-pressed',String(group===id));tabs.append(tab);
      }
      const state=own.inventory;
      for(const item of catalog.filter(i=>i.group===(view==='deck'?'record':group))){
        const has=state.owned.includes(item.id);if(view!=='shop'&&!has)continue;
        const row=el('article'),picture=el('canvas'),copy=el('div'),actions=el('div',null,'burrow-actions');
        picture.width=picture.height=56;picture.setAttribute('aria-hidden','true');window.NoraBurrowModels.icon(picture,item);
        copy.append(el('strong',item.name),el('small',item.description));row.append(picture,copy,actions);list.append(row);
        const act=(label,action,fields={})=>button(label,async()=>{
          ++serial;const data=await request({action,item:item.id,...fields});++serial;apply(data);
          if(dead)return;render();status.textContent=action==='buy'?'Куплено · '+item.name:'Сохранено · '+item.name;
        });
        if(!has){actions.append(act(item.price+' 🍪 · Купить','buy'));continue;}
        if(item.group==='wear'){const worn=state.wear===item.id;actions.append(act(worn?'Снять':'Надеть',worn?'remove':'wear'));}
        if(item.group==='decor'){
          const selected=Object.keys(state.layout).find(k=>state.layout[k]===item.id);
          const select=el('select');select.setAttribute('aria-label','Место · '+item.name);
          for(const [i,label] of spots.entries()){
            const used=state.layout[i],name=catalog.find(p=>p.id===used)?.name;
            select.add(new Option(label+(name?' · '+name:''),String(i)));
          }
          select.value=selected??String(spots.findIndex((_,i)=>!state.layout[i]));if(select.selectedIndex<0)select.selectedIndex=0;
          const place=button(selected===undefined?'Поставить':'Переставить',async()=>{
            ++serial;const data=await request({action:'place',item:item.id,slot:Number(select.value)});++serial;apply(data);render();status.textContent='Поставлено · '+item.name;
          });
          actions.append(select,place);if(selected!==undefined)actions.append(act('Убрать','place',{slot:null}));
        }
        if(item.group==='record'){
          const active=state.record===item.id;
          if(Object.values(state.layout).includes('hifi'))actions.append(act(active?'Остановить':'Поставить пластинку',active?'stop':'play'));
          else actions.append(el('small','Куплено · поставь проигрыватель «Волна»'));
        }
      }
      if(!list.children.length)list.append(el('p','Здесь появятся покупки из лавки на спавне.'));
    }
    function show(){
      reset();if(!panel.open)panel.showModal();status.textContent='';list.scrollTop=0;
    }
    async function open(mode){
      view=mode;group=mode==='shop'?'wear':'decor';show();title.textContent='Мастерская';list.replaceChildren();tabs.replaceChildren();
      status.textContent='Загрузка…';await items();
      const data=await request();if(dead)return;apply(data);render();
    }
    async function directory(invite=false){
      view=invite?'invite':'directory';show();title.textContent=invite?'Пригласить в свою нору':'Чужие норки';
      balance.textContent='';tabs.replaceChildren();search='';offset=0;
      const form=el('form'),field=el('input'),submit=el('button','Найти');field.type='search';field.placeholder='Ник игрока';field.setAttribute('aria-label','Ник игрока');field.maxLength=16;
      form.append(field,submit);tabs.append(form);
      async function page(){
        const v=++dirVersion;
        const result=await request(undefined,'?'+new URLSearchParams({directory:'1',q:search,offset}));
        if(dead||v!==dirVersion||view!==(invite?'invite':'directory'))return;
        list.replaceChildren();status.textContent='';
        for(const {name,online} of result.players){
          const row=el('article'),copy=el('div');copy.append(el('strong',name),el('small',online?'Сейчас в игре':'Сейчас вне игры'));
          const send=button(invite?'Пригласить':'Попроситься',async()=>{
            await request({action:invite?'invite':'request',target:name});send.disabled=true;send.textContent='Отправлено';
            status.textContent='Сообщение для '+name+' в игровом чате · 10 минут на ответ.';
          });row.append(copy,send);list.append(row);
        }
        if(!result.players.length)list.append(el('p','Игроки не найдены.'));
        if(offset>0)list.append(button('Назад',()=>{offset-=40;return page();}));
        if(result.more)list.append(button('Далее',()=>{offset+=40;return page();}));
      }
      form.onsubmit=e=>{e.preventDefault();search=field.value.trim();offset=0;run(page);};await page();
    }
    async function respond(note,action){
      if(action==='enter'){await go(note.other);await request({action:'dismiss',id:note.id});return;}
      if(note.kind==='invite'&&action==='accept'&&!where())throw Error('Вернись в лобби и прими приглашение.');
      const data=await request({action,id:note.id});
      if(data.enter)await go(data.enter);
    }
    return {
      open,go,directory,respond,leave,run,host:()=>host,home:()=>home,
      switchLamp:async()=>{apply(await request({action:'light',item:'lamp',lit:!home.lamp}));},
      burst:()=>request({action:'burst',target:host}),
      panelOpen:()=>panel.open,
      tick(time,inside){
        homeButton.hidden=!inside||host!==me;
        if(!inside||!host||time<next||polling||loading)return;
        const current=host;
        next=time+2400;polling=true;
        refresh().catch(error=>{
          if(!dead&&host===current&&current!==me&&error.message==='Сначала получи приглашение хозяина.'){
            if(panel.open)panel.close();leave();returnToLobby();toast('Визит завершён. Ты снова в лобби.');
          }
        }).finally(()=>{polling=false;});
      },
      dispose(){dead=true;++serial;++dirVersion;panel.remove();homeButton.remove();}
    };
  }
  return {mount};
})();
