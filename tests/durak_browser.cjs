const assert=require('node:assert/strict');
const path=require('node:path');
const {chromium,webkit,devices}=require('playwright');
const base=process.env.DURAK_TEST_URL||'http://127.0.0.1:18761';
assert.equal(new URL(base).hostname,'127.0.0.1','This scenario uses the isolated localhost fixture.');
const clicks=(p,action)=>p.locator(`[data-dk="${action}"]`).click();
async function ready(p,sel){await p.locator(sel).first().waitFor({state:'visible'})}
async function tableId(p){
  return p.evaluate(()=>sessionStorage.getItem('nora-durak-'+tg.initDataUnsafe.user.id+'room'));
}
async function state(p,id){
  return p.evaluate(id=>api('durak/room/'+id),id);
}
async function revision(p,n){
  await p.waitForFunction(n=>Number(document.querySelector('#durak-root')?.dataset.revision)>=n,n,{timeout:12000});
}
async function openGame(p,id,extra=''){
  await p.goto(`${base}/?player=${id}&view=durak${extra}`);
  await ready(p,'#durak-root');
}
async function choose(p,key,value){
  await p.locator(`[data-option="${key}"][data-value="${value}"]`).click();
}
async function bounds(p){
  const rect=await p.evaluate(()=>{
    const area=e=>{const r=e.getBoundingClientRect();return {x:r.x,y:r.y,w:r.width,h:r.height,right:r.right,bottom:r.bottom}};
    return {view:innerWidth,h:innerHeight,width:document.documentElement.scrollWidth,
      buttons:[...document.querySelectorAll('.dk-actions button,.dk-create-row button,.dk-rule-grid button')].map(area),
      hand:document.querySelector('.dk-hand')?area(document.querySelector('.dk-hand')):null,
      actions:document.querySelector('.dk-actions')?area(document.querySelector('.dk-actions')):null,
      ownNav:document.querySelector('#nav')?.getClientRects().length||0};
  });
  assert.ok(rect.width<=rect.view+1,`Horizontal overflow ${JSON.stringify(rect)}`);
  for(const b of rect.buttons)assert.ok(b.x>=-1&&b.right<=rect.view+1);
  if(rect.hand){
    assert.equal(rect.ownNav,0,'Main navigation occupies the table');
    if(rect.view<rect.h)assert.ok(rect.hand.bottom<=rect.actions.y+2,'Hand overlaps controls');
    assert.ok(rect.actions.bottom<=rect.h+2,`Actions below viewport ${JSON.stringify(rect)}`);
  }
}
async function shot(page,name){
  if(process.env.DURAK_SHOTS)await page.screenshot({path:path.join(process.env.DURAK_SHOTS,name+'.png')});
}
async function enterOpen(p,uid,id){
  await openGame(p,uid);
  const card=p.locator(`[data-dk=preview][data-id="${id}"]`);
  await card.click();await clicks(p,'join');await ready(p,'[data-dk=friends],.dk-gamehead');
}
async function hitPoint(page,selector){
  await page.locator('#nora-intro').waitFor({state:'hidden'});
  return page.locator(selector).evaluate(el=>{
    const r=el.getBoundingClientRect();
    const hits=[];
    for(const y of [.3,.12,.5,.75])for(const x of [.13,.25,.5,.72]){
      const point={x:r.x+r.width*x,y:r.y+r.height*y};
      const target=document.elementFromPoint(point.x,point.y);
      if(el.contains(target))return point;
      hits.push(target?.getAttribute('data-hand')??target?.className);
    }
    throw Error(`No exposed point at ${r.x},${r.y} ${r.width}×${r.height} on ${innerWidth}×${innerHeight} for ${el.outerHTML}. Hits: ${[...new Set(hits)]}`);
  });
}
async function dragCard(page,card,target,{cancel=false,beforeDrop,touch=false}={}){
  const start=await hitPoint(page,`[data-hand="${card}"]`);
  if(touch&&page.context().browser().browserType().name()==='chromium'){
    const cdp=await page.context().newCDPSession(page);
    const dispatch=(type,touchPoints)=>cdp.send('Input.dispatchTouchEvent',{type,touchPoints});
    try{
      await dispatch('touchStart',[start]);
      await ready(page,'.dk-drag');
      const end=await hitPoint(page,target);
      for(let i=1;i<=5;i++)await dispatch('touchMove',[{
        x:start.x+(end.x-start.x)*i/5, y:start.y+(end.y-start.y)*i/5,
      }]);
      if(beforeDrop)await beforeDrop();
      await dispatch(cancel?'touchCancel':'touchEnd',[]);
    }finally{await cdp.detach()}
    return;
  }
  await page.mouse.move(start.x,start.y);await page.mouse.down();
  await ready(page,'.dk-drag');
  const end=await hitPoint(page,target);
  await page.mouse.move(end.x,end.y,{steps:8});
  if(beforeDrop)await beforeDrop();
  if(cancel)await page.locator('#durak-root').dispatchEvent('pointercancel',{pointerId:1});
  await page.mouse.up();
}
async function tapCard(page,card){
  const {x,y}=await hitPoint(page,`[data-hand="${card}"]`);
  await page.touchscreen.tap(x,y);
}
async function reactions(players,id){
  const [sender,observer]=players, rev=(await state(sender,id)).rev;
  const uid=await sender.evaluate(()=>tg.initDataUnsafe.user.id);
  const uid2=await observer.evaluate(()=>tg.initDataUnsafe.user.id);
  const first=`[data-player="${uid}"] .dk-bubble img[src$="/reaction-3.webp"]`;
  const other=`[data-player="${uid2}"] .dk-bubble img[src$="/reaction-9.webp"]`;
  await Promise.all(players.slice(0,2).map(p=>clicks(p,'reactions')));
  const picker=sender.locator('#dk-reaction-panel');
  assert.equal(await picker.locator('[data-emoji]').count(),25);
  await Promise.all([sender.locator('[data-emoji="3"]').click(),observer.locator('[data-emoji="9"]').click()]);
  await Promise.all(players.map(async p=>{
    await Promise.all([ready(p,first),ready(p,other)]);
    assert.equal(await p.locator('.dk-bubble img').count(),2);
    assert.equal(Number(await p.locator('#durak-root').getAttribute('data-revision')),rev);
  }));
  await clicks(sender,'reactions');
  assert.ok(await picker.locator('[data-emoji="3"]').isDisabled());
  await clicks(sender,'reactions-close');
  await Promise.all(players.map(p=>p.locator('.dk-bubble img').first().waitFor({state:'detached'})));
  await clicks(observer,'reactions');
  await observer.locator('#dk-react-show').uncheck();await clicks(observer,'reactions-close');
  await clicks(sender,'reactions');await sender.locator('[data-emoji="3"]').click();
  await ready(sender,first);
  assert.equal(await observer.locator(first).count(),0);
  await clicks(observer,'reactions');
  await observer.locator('#dk-react-show').check();await clicks(observer,'reactions-close');
}
async function throughTable(players,id){
  // Drive only actions advertised to the corresponding authenticated player.
  let v=await state(players[0],id), count=0, didDrag=false, tossed=false;
  while(v.status==='playing'&&count++<800){
    const seat=v.game.turn, actor=players[seat];
    const view=await state(actor,id);
    await revision(actor,view.rev);
    const moves=view.game.moves;
    let m=moves.find(x=>x.kind==='defend')||moves.find(x=>x.kind==='transfer')||
          moves.find(x=>x.kind==='attack')||moves.find(x=>x.kind==='pass')||moves.find(x=>x.kind==='take');
    assert.ok(m,`No actionable control for ${view.game.phase}`);
    if(m.kind==='attack'&&(!didDrag||(!tossed&&view.game.table.length))){
      await dragCard(actor,m.card,'[data-drop]');
      tossed||=view.game.table.length>0;
      didDrag=true;
    }else{
      if(m.card!==undefined)await tapCard(actor,m.card);
      if(m.kind==='defend')await actor.locator(`.dk-pair[data-slot="${m.slot}"] .dk-tablecard`).first().click({force:true});
      else await actor.locator(`[data-dk="${m.kind}"]`).click({force:true});
    }
    try{await revision(actor,view.rev+1)}
    catch(error){
      const state=await actor.locator('#durak-root').evaluate(root=>({
        actions:root.querySelector('.dk-actions')?.innerText,error:root.querySelector('.dk-error')?.innerText,
        held:root.querySelector('[aria-pressed=true][data-hand]')?.dataset.hand,rev:root.dataset.revision,
      }));
      throw Error(`Move ${JSON.stringify(m)} at ${view.rev} did not land: ${JSON.stringify(state)}`,{cause:error});
    }
    v=await state(actor,id);
  }
  assert.ok(didDrag&&tossed&&count<800);
  assert.equal(v.status,'finished');
  await Promise.all(players.map(p=>ready(p,'.dk-result')));
  assert.equal(v.members.reduce((s,p)=>s+p.payout,0),v.config.stake*v.members.length);
  return count;
}
async function groupedTransferAndChallenge(players,id){
  const table=await state(players[0],id),lead=table.game.attacker,def=table.game.defender;
  const a=players[lead], b=players[def];
  const hands=(await Promise.all(players.map(p=>state(p,id)))).map(s=>s.game.hand);
  const group=hands[lead].map(c=>hands[lead].filter(k=>(k>>2)===(c>>2))).find(cards=>
    cards.length>1&&hands[def].some(z=>(z>>2)===(cards[0]>>2)));
  assert.ok(group,'Expected repeated ranks in the seeded fixture deal');
  await tapCard(a,group[0]);await clicks(a,'batch');
  await tapCard(a,group[1]);await dragCard(a,group[1],'[data-drop]');
  await revision(b,table.rev+1);
  const same=hands[def].find(c=>(c>>2)===(group[0]>>2));
  await dragCard(b,same,'[data-drop]',{beforeDrop:async()=>assert.equal(await b.locator('.dk-drop').getAttribute('data-kind'),'transfer')});
  await revision(a,table.rev+2);
  const view=await state(a,id),trump=view.game.trump,attack=view.game.table[0][0];
  const invalid=view.game.hand.find(c=>c%4===attack%4?c<attack:c%4!==trump);
  assert.notEqual(invalid,undefined);
  await dragCard(a,invalid,'.dk-pair[data-slot="0"] .dk-tablecard');
  await revision(b,table.rev+3);await shot(b,'durak-midround');
  await clicks(b,'challenge-mode');await b.locator(`[data-dk=report][data-card="${invalid}"]`).click();
  await revision(a,table.rev+4);
  const after=await state(a,id);assert.ok(after.game.marked.includes(lead));
  assert.ok(after.game.hand.includes(invalid));assert.equal(after.game.table[0][1],null);
}
async function transferChain(players,id){
  const [a,b,c]=players;
  let {rev}=await state(a,id);
  // Cancel a captured pointer and leave both the DOM node and room revision intact.
  const held=await a.locator('[data-hand="16"]').elementHandle();
  await dragCard(a,16,'[data-drop]',{touch:true,cancel:true});
  await a.locator('.dk-drag').waitFor({state:'detached'});
  assert.equal(await held.evaluate(el=>el.isConnected),true);
  assert.equal((await state(a,id)).rev,rev);
  await dragCard(a,16,'[data-drop]',{touch:true});await revision(b,rev+1);
  await clicks(a,'undo');await revision(a,rev+2);
  rev+=2;
  await a.locator('.dk-flight').first().waitFor({state:'detached'});
  const {x,y}=await hitPoint(a,'[data-hand="16"]');
  await a.touchscreen.tap(x,y);await a.touchscreen.tap(x,y);await revision(b,rev+1);
  // A diamond of the correct rank can be transferred but cannot beat the club.
  await dragCard(b,17,'.dk-pair[data-slot="0"] .dk-tablecard');
  assert.equal((await state(b,id)).rev,rev+1);
  await b.locator('.dk-drag').waitFor({state:'detached'});
  await dragCard(b,17,'[data-drop]',{touch:true});await revision(c,rev+2);
  assert.equal(await c.locator('.is-defender').getAttribute('data-seat'),'2');
  await dragCard(c,19,'[data-drop]');await revision(a,rev+3);
  assert.equal(await a.locator('.is-defender').getAttribute('data-seat'),'0');
  // Card 21 can cover the diamond at index 1. The empty slot would be a transfer, which is illegal.
  await dragCard(a,21,'[data-drop]');
  assert.equal((await state(a,id)).rev,rev+3);
  await a.locator('.dk-drag').waitFor({state:'detached'});
  await dragCard(a,21,'.dk-pair[data-slot="1"] .dk-tablecard',{beforeDrop:async()=>{
    const id=await tableId(a);
    // An independent player updates the table while the local pointer is captured.
    // The target remains identified by the attack card as well as by its slot.
    await c.evaluate(id=>api('durak/action',{
      action:'reaction',room:id,emoji_id:4,nonce:crypto.randomUUID(),
    }),id);
    await ready(a,'[data-player="3"] .dk-bubble img');
    assert.equal(await a.locator('.dk-drag').count(),1);
  }});
  await revision(b,rev+4);
  const pairs=(await state(a,id)).game.table;
  assert.deepEqual(pairs,[[16,null],[17,21],[19,null]]);
  assert.equal(await a.locator('[data-slot="1"] .cover').getAttribute('data-on-table'),'21');
  await dragCard(a,39,'.dk-pair[data-slot="2"] .dk-tablecard',{beforeDrop:async()=>{
    const view=await state(c,id);
    const move=view.game.moves.find(m=>m.kind==='attack'&&m.card===23);
    assert.ok(move);
    await c.evaluate(fields=>api('durak/action',fields),{
      action:'move',room:id,rev:view.rev,move,nonce:crypto.randomUUID(),
    });
    await revision(a,rev+5);
    assert.equal(await a.locator('.dk-drag').count(),1);
  }});
  await revision(c,rev+6);
  assert.deepEqual((await state(a,id)).game.table,[[16,null],[17,21],[19,39],[23,null]]);
}
async function denseLayout(page,id){
  const view=await state(page,id),url=new RegExp('/api/durak/room/'+id+'(?:\\?|$)');
  view.game.hand=Array.from({length:26},(_,i)=>i);
  view.game.table=Array.from({length:6},(_,i)=>[26+i*2,27+i*2]);
  view.game.counts=view.game.counts.map((_,seat)=>seat===view.own?26:2);
  view.game.moves=[];view.game.events=[];view.frames=[];
  await page.route(url,route=>route.fulfill({json:new URL(route.request().url()).searchParams.has('after')?
    {rev:view.rev,unchanged:true,retry:2}:view}));
  await page.reload();await ready(page,'.dk-tablecard');
  await page.locator('#nora-intro').waitFor({state:'hidden'});
  for(const [width,height] of [[320,568],[360,640],[390,844],[430,932],[568,320],[844,390]]){
    await page.setViewportSize({width,height});
    await page.evaluate(()=>{
      const css=document.documentElement.style;
      css.setProperty('--tg-content-safe-area-inset-top','29px');
      css.setProperty('--tg-safe-area-inset-bottom','15px');
    });
    await bounds(page);
    await page.evaluate(()=>{
      const check=(ok,message)=>{if(!ok)throw Error(message)};
      const box=el=>el.getBoundingClientRect(),felt=box(document.querySelector('.dk-felt'));
      const pairs=[...document.querySelectorAll('.dk-pair')];
      check(pairs.length===6 && document.querySelectorAll('.dk-handcard').length===26,'Unexpected fixture layout');
      const boxes=pairs.map(pair=>{
        const [a,b]=[...pair.children].map(box);
        check(b.left>a.left&&b.left<a.right&&b.top>a.top&&b.top<a.bottom,'Cover is not stacked');
        return {left:a.left,top:a.top,right:b.right,bottom:b.bottom};
      });
      for(const [i,a] of boxes.entries()){
        check(a.left>=felt.left&&a.top>=felt.top&&a.right<=felt.right&&a.bottom<=felt.bottom,'Pair outside felt');
        for(const b of boxes.slice(i+1))
          check(a.right<=b.left||b.right<=a.left||a.bottom<=b.top||b.bottom<=a.top,
            `Adjacent pairs overlap on ${innerWidth}×${innerHeight}: ${JSON.stringify({a,b})}`);
      }
    });
    if(width===320||width===844)await shot(page,'durak-dense-'+width);
    for(const card of [0,7,14,25])await hitPoint(page,`[data-hand="${card}"]`);
  }
  await clicks(page,'sort');
  const sorted=await page.locator('[data-hand]').evaluateAll(nodes=>nodes.map(el=>Number(el.dataset.hand)));
  assert.deepEqual(sorted,view.game.hand);
  await page.unroute(url);
}
async function main(){
  const browser=await chromium.launch({channel:'chrome',headless:true});
  const safari=process.env.DURAK_WEBKIT?await webkit.launch({headless:true}):null;
  const errors=[];
  try{
    const players=[];
    for(let i=0;i<6;i++){
      const preset=i%2?devices['Pixel 7']:devices['iPhone 13'];
      const context=await (safari&&i%2===0?safari:browser).newContext({...preset,defaultBrowserType:undefined,deviceScaleFactor:1});
      const p=await context.newPage();
      p.on('pageerror',e=>errors.push(e.message));
      players.push(p);
    }
    const [a,b]=players;
    await a.goto(base+'/?player=1');
    await a.locator('#nav [data-tab=community]').click();
    await a.locator('#app [data-tab=games]').first().click();
    await ready(a,'[data-tab=durak]');
    assert.equal(await a.evaluate(()=>performance.getEntriesByType('resource').filter(e=>/\/durak(?:\.js|\.css|-cards\/)/.test(e.name)).length),0);
    await a.locator('[data-tab=durak]').click();await clicks(a,'create-form');
    for(const size of [{width:320,height:568},{width:390,height:844},{width:412,height:915}]){
      await a.setViewportSize(size);await bounds(a);
    }
    await choose(a,'deck',24);assert.ok(await a.locator('[data-option=players][data-value="5"]').isDisabled());
    await choose(a,'speed','fast');await choose(a,'variant','transfer');await choose(a,'honesty','cheats');
    await a.locator('#dk-stake').fill('0');
    assert.equal(await a.locator('#dk-stake').getAttribute('aria-valuetext'),'5 печенек');
    await a.locator('#dk-stake').fill('10');await shot(a,'durak-create');
    await a.locator('#dk-private').check();await clicks(a,'create');await ready(a,'[data-dk=friends]');
    const privateId=await tableId(a),waiting=await state(a,privateId);
    assert.equal(waiting.config.stake,250);assert.ok(waiting.config.private);
    await clicks(a,'share');await a.waitForFunction(()=>Boolean(window.fixtureShared));
    const telegramLink=await a.evaluate(()=>new URL(window.fixtureShared).searchParams.get('url'));
    const param=new URL(telegramLink).searchParams.get('startapp');
    assert.equal(param,'nora_d_'+waiting.code);
    await clicks(a,'friends');await a.locator('[data-dk=invite][data-id="2"]').click();
    await ready(a,'[data-dk=invite][data-id="2"]:disabled');
    await openGame(b,2);await clicks(b,'mine');await ready(b,`[data-kind=invite][data-id="${privateId}"]`);
    await b.goto(base+'/?player=2&view=notices');await b.locator('[data-durak-invite]').click();await ready(b,'[data-dk=join]');
    await openGame(players[2],3);await clicks(players[2],'code-form');await players[2].locator('#dk-code').fill(waiting.code);
    await players[2].locator('#dk-code-form button').click();await ready(players[2],'[data-dk=join]');
    await openGame(b,2,'&startapp='+param);
    await ready(b,'[data-dk=join]');
    assert.ok((await b.locator('[data-dk=join]').innerText()).includes('250'));
    await clicks(b,'join');await ready(b,'.dk-gamehead');await ready(a,'.dk-gamehead');
    await b.context().setOffline(true);await b.context().setOffline(false);
    await b.reload();await ready(b,'.dk-gamehead');
    const back=await state(b,privateId);assert.equal(back.status,'playing');assert.equal(back.game.hand.length,6);
    await b.setViewportSize({width:844,height:390});await bounds(b);await shot(b,'durak-landscape');
    await reactions([a,b],privateId);
    await groupedTransferAndChallenge([a,b],privateId);
    await clicks(b,'game-info');await b.locator('#dk-surrender').click();await b.locator('#dk-confirm-leave').click();
    await ready(a,'.dk-result');await ready(b,'.dk-result');
    await clicks(a,'again');await choose(a,'speed','normal');await choose(a,'honesty','fair');await choose(a,'variant','throw');
    await a.locator('#dk-private').uncheck();await clicks(a,'create');await ready(a,'[data-dk=friends]');
    const played=await tableId(a);await clicks(b,'back');await enterOpen(b,2,played);
    await ready(a,'.dk-gamehead');await a.setViewportSize({width:390,height:844});await bounds(a);
    const turns=await throughTable([a,b],played);
    await shot(a,'durak-result');
    await clicks(a,'again');await choose(a,'deck',36);await choose(a,'players',3);await choose(a,'variant','transfer');
    await clicks(a,'create');await ready(a,'[data-dk=friends]');const three=await tableId(a);
    await clicks(b,'back');await enterOpen(b,2,three);await enterOpen(players[2],3,three);
    await Promise.all(players.slice(0,3).map(p=>ready(p,'.dk-gamehead')));
    await reactions(players.slice(0,3),three);
    await transferChain(players.slice(0,3),three);
    for(const p of [players[2],b]){
      const {rev}=await state(p,three);
      await clicks(p,'game-info');await p.locator('#dk-surrender').click();await p.locator('#dk-confirm-leave').click();
      await revision(a,rev+1);
    }
    await ready(a,'.dk-result');
    await clicks(a,'again');await choose(a,'deck',52);await choose(a,'players',6);await choose(a,'scope','all');
    await clicks(a,'create');await ready(a,'[data-dk=friends]');const six=await tableId(a);
    for(let i=1;i<players.length;i++){
      const p=players[i];
      if(i<=2)await clicks(p,'back');
      if(i===5){await openGame(p,i+1);await p.locator(`[data-dk=quick][data-id="${six}"]`).click();await ready(p,'.dk-gamehead')}
      else await enterOpen(p,i+1,six);
    }
    await Promise.all(players.map(p=>ready(p,'.dk-gamehead')));
    for(const p of players){
      const v=await state(p,six);assert.equal(v.members.length,6);assert.equal(v.game.hand.length,6);
    }
    await reactions(players,six);
    await a.setViewportSize({width:320,height:568});await bounds(a);await shot(a,'durak-six-320');
    await a.setViewportSize({width:412,height:915});await bounds(a);await shot(a,'durak-six-android');
    await a.setViewportSize({width:844,height:390});await bounds(a);await shot(a,'durak-six-wide');
    await denseLayout(a,six);
    assert.deepEqual(errors,[]);
    console.log(`Playwright passed: invitation, link, reload, real pointer drag, ${turns} table actions, payout, six authenticated clients and mobile geometry.`);
  }finally{await Promise.all([browser.close(),safari?.close()])}
}
main().catch(err=>{console.error(err.stack);process.exitCode=1});
