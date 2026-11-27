'use strict';
/* Stage 8: durable operation receipts. Never retry an uncertain Telegram send. */
window.NoraStaffDelivery = {
  create({getAuth,onConfirmed}) {
    const storageKey='nora-staff-chat-pending-v1';
    let pending=null, state='idle', detail='', checking=false, confirming=false;
    const createId=()=>{
      const bytes=new Uint8Array(16),c=window.crypto;
      if(typeof c?.randomUUID==='function')return c.randomUUID();
      if(typeof c?.getRandomValues==='function')c.getRandomValues(bytes);
      else for(let i=0;i<16;i++)bytes[i]=Math.floor(Math.random()*256);
      bytes[6]=(bytes[6]&15)|64;bytes[8]=(bytes[8]&63)|128;
      const h=[...bytes].map(x=>x.toString(16).padStart(2,'0')).join('');
      return h.slice(0,8)+'-'+h.slice(8,12)+'-'+h.slice(12,16)+'-'+h.slice(16,20)+'-'+h.slice(20);
    };
    const store=()=>{
      try {
        if(pending)sessionStorage.setItem(storageKey,JSON.stringify({id:pending.id,created:pending.created}));
        else sessionStorage.removeItem(storageKey);
      }catch{}
    };
    function render() {
      const root=document.getElementById('staff-chat-delivery');
      if(!root)return;
      root.hidden=!pending&&!detail;
      root.dataset.state=state;
      if(root.hidden){root.replaceChildren();return;}
      const text=document.createElement('span');
      text.className='staff-chat-delivery-text';
      text.textContent=detail;
      root.replaceChildren(text);
      if(pending){
        const check=document.createElement('button');
        check.type='button';check.dataset.chatCheckDelivery='';
        check.textContent=checking?NoraI18n.t("Проверяем…"):NoraI18n.t("Проверить");
        check.disabled=checking;
        root.append(check);
      }
      if(pending&&state==='uncertain'){
        const reset=document.createElement('button');
        reset.type='button';reset.dataset.chatResetDelivery='';
        reset.textContent=confirming?NoraI18n.t("Подтвердить риск дубля"):NoraI18n.t("Начать новую отправку");
        reset.className=confirming?'is-confirming':'';
        root.append(reset);
      }
    }
    function finish(sent,error=''){
      const current=pending;
      if(!current)return;
      pending=null;confirming=false;store();
      state=sent?'sent':'failed';
      detail=sent?NoraI18n.t("✓ Отправлено в Telegram"):error||NoraI18n.t("Не отправлено. Можно повторить.");
      render();
      if(sent)onConfirmed?.(!!current.restored);
    }
    async function check() {
      const current=pending;
      if(!current||checking)return;
      checking=true;
      render();
      const controller=new AbortController();
      const timeout=setTimeout(()=>controller.abort(),12000);
      try{
        const response=await fetch('/api/community/chat/delivery/'+current.id,{
          headers:{Authorization:'tma '+getAuth()},cache:'no-store',signal:controller.signal
        });
        if(current!==pending)return;
        if(!response.ok)throw new Error(NoraI18n.t("Не получилось проверить отправку"));
        const data=await response.json();
        if(data.state==='sent'){finish(true);return;}
        if(data.state==='failed'){finish(false,data.error);return;}
        state=data.state==='sending'?'sending':'uncertain';
        detail=state==='sending'
          ?NoraI18n.t("Отправка ещё обрабатывается. Не повторяй её вручную.")
          :NoraI18n.t("Telegram мог получить сообщение. Проверь чат перед новой отправкой.");
      }catch{
        if(current!==pending)return;
        state='uncertain';
        detail=NoraI18n.t("Статус неизвестен. Проверь Telegram перед новой отправкой.");
      }finally{
        clearTimeout(timeout);checking=false;render();
      }
    }
    function begin(){
      if(pending)return null;
      pending={id:createId(),created:Date.now(),restored:false};
      state='sending';detail=NoraI18n.t("Отправляем сообщение…");
      confirming=false;store();render();
      return pending.id;
    }
    function acknowledge(result){
      if(result?.ok&&result.state==='sent'){finish(true);return true;}
      return false;
    }
    function restore(){
      if(pending)return;
      try {
        const value=JSON.parse(sessionStorage.getItem(storageKey)||'null');
        if(value&&typeof value.id==='string'&&
          /^[a-f0-9-]{36}$/.test(value.id)&&
          Number.isFinite(value.created)&&Date.now()-value.created<7*86400000){
          pending={id:value.id,created:value.created,restored:true};
          state='checking';detail=NoraI18n.t("Проверяем последнюю отправку…");
        }else if(value)sessionStorage.removeItem(storageKey);
      }catch{}
      render();
      if(pending)void check();
    }
    function reset(){
      if(!pending||state!=='uncertain')return false;
      if(!confirming){
        confirming=true;
        detail=NoraI18n.t("Telegram мог получить сообщение. Новая отправка может создать дубль.");
        render();return false;
      }
      pending=null;confirming=false;store();
      state='failed';detail=NoraI18n.t("Предыдущая попытка оставлена без подтверждения. Проверь Telegram.");
      render();return true;
    }
    return {
      begin,check,acknowledge,restore,reset,render,
      get pending(){return !!pending;},
      get status(){return state;}
    };
  }
};
