'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'..','community_bot','web','staff-chat-delivery.js'),'utf8');
const saved=new Map(),elements=new Map();
const window={crypto:require('node:crypto').webcrypto};
const sessionStorage={
  getItem:k=>saved.get(k)||null,
  setItem:(k,v)=>saved.set(k,v),
  removeItem:k=>saved.delete(k)
};
const document={getElementById:id=>{
  if(!elements.has(id))elements.set(id,{
    hidden:true,dataset:{},children:[],replaceChildren(...parts){this.children=parts},
    append(...parts){this.children.push(...parts)}
  });
  return elements.get(id);
},createElement:tag=>({tagName:tag, dataset:{},className:'',textContent:'',disabled:false})};
let next={ok:true,state:'sent',message_ids:[99]}, calls=0, confirmed=[];
const fetch=async()=>{
  calls++;
  return {ok:true,json:async()=>next};
};
const context={window,document,sessionStorage,fetch,AbortController,setTimeout,clearTimeout,Uint8Array,Date,JSON,Math};
vm.runInNewContext(source,context);
const make=()=>window.NoraStaffDelivery.create({
  getAuth:()=> 'SIGNED',
  onConfirmed:restored=>confirmed.push(restored)
});
async function run(){
  const first=make();
  const operation=first.begin();
  assert.match(operation,/^[a-f0-9-]{36}$/);
  assert.equal(first.pending,true);
  first.restore();
  assert.equal(first.pending,true);
  assert.equal(first.acknowledge(next),true);
  assert.equal(first.pending,false);
  assert.deepEqual(confirmed,[false]);
  const second=make();
  const id=second.begin();
  assert.notEqual(id,operation);
  const third=make();
  third.restore();
  assert.equal(third.pending,true);
  // restore() launches reconciliation asynchronously; wait for its in-flight GET.
  await new Promise(resolve=>setTimeout(resolve,5));
  assert.equal(third.pending,false);
  assert.deepEqual(confirmed,[false,true]);
  next={ok:false,state:'uncertain'};
  const fourth=make();fourth.begin();
  await fourth.check();
  assert.equal(fourth.pending,true);
  assert.equal(fourth.reset(),false);
  assert.equal(fourth.reset(),true);
  assert.equal(fourth.pending,false);
  assert.ok(calls>=2);
  console.log('NORA stage 8 delivery recovery smoke passed');
}
run().catch(e=>{console.error(e);process.exitCode=1});
