'use strict';
// One authenticated loader for all list previews, including dynamically rendered sheets.
(() => {
  const cache=new Map(),pending=new Set();let active=0,timer;
  function paint(node,url){if(!node.isConnected)return;const old=node.querySelector('img[data-mini-avatar]');if(old?.src===url)return;const img=new Image();img.alt='';img.dataset.miniAvatar='';img.src=url;img.decoding='async';img.onload=()=>{if(node.isConnected){node.querySelectorAll('img[data-mini-avatar]').forEach(n=>n.remove());node.prepend(img)}}}
  function clear(id){const old=cache.get(id);if(old?.url)URL.revokeObjectURL(old.url);cache.delete(id);document.querySelectorAll(`[data-person-avatar="${id}"] img[data-mini-avatar]`).forEach(n=>n.remove())}
  async function load(id){active++;pending.add(id);try{const r=await fetch('/api/people/'+id+'/avatar?size=thumb',{headers:{Authorization:'tma '+auth}});if(!r.ok){clear(id);cache.set(id,{url:null,until:Date.now()+30000});return}const blob=await r.blob();clear(id);const url=URL.createObjectURL(blob);cache.set(id,{url,until:Date.now()+60000});document.querySelectorAll(`[data-person-avatar="${id}"]:not([data-avatar-unavailable])`).forEach(n=>paint(n,url))}catch{clear(id);cache.set(id,{url:null,until:Date.now()+10000})}finally{active--;pending.delete(id);schedule()}}
  function hydrate(){if(!auth||document.hidden)return;const nodes=[...document.querySelectorAll('[data-person-avatar]')];for(const n of nodes){const id=n.dataset.personAvatar;if(!/^\d+$/.test(id))continue;if(n.hasAttribute('data-avatar-unavailable')){n.querySelectorAll('img[data-mini-avatar]').forEach(i=>i.remove());continue}const hit=cache.get(id);if(hit?.until>Date.now()){if(hit.url)paint(n,hit.url);continue}if(active<4&&!pending.has(id))load(id)}if(cache.size>200){const visible=new Set(nodes.map(n=>n.dataset.personAvatar));for(const id of cache.keys())if(!visible.has(id))clear(id)}}
  function schedule(){clearTimeout(timer);timer=setTimeout(hydrate,30)}
  new MutationObserver(schedule).observe(document.body,{childList:true,subtree:true});
  setInterval(schedule,15000);document.addEventListener('visibilitychange',schedule);schedule();
})();
