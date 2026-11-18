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
async function throughTable(players,id){
  // Drive only actions advertised to the corresponding authenticated player.
  let v=await state(players[0],id), count=0, didDrag=false;
  while(v.status==='playing'&&count++<800){
    const seat=v.game.turn, actor=players[seat];
    const view=await state(actor,id);
    await revision(actor,view.rev);
    const moves=view.game.moves;
    let m=moves.find(x=>x.kind==='defend')||moves.find(x=>x.kind==='transfer')||
          moves.find(x=>x.kind==='attack')||moves.find(x=>x.kind==='pass')||moves.find(x=>x.kind==='take');
    assert.ok(m,`No actionable control for ${view.game.phase}`);
    const hand=actor.locator(`[data-hand="${m.card}"]`);
    if(m.kind==='attack'&&!didDrag){
      const a=await hand.boundingBox(),b=await actor.locator('.dk-felt').boundingBox();
      await actor.mouse.move(a.x+a.width/2,a.y+a.height/2);await actor.mouse.down();
      await actor.mouse.move(b.x+b.width/2,b.y+b.height*.68,{steps:8});await actor.mouse.up();didDrag=true;
    }else{
      if(m.card!==undefined)await hand.click({force:true});
      if(m.kind==='defend')await actor.locator(`.dk-pair[data-slot="${m.slot}"] .dk-tablecard`).first().click({force:true});
      else await actor.locator(`[data-dk="${m.kind}"]`).click({force:true});
    }
    await revision(actor,view.rev+1);
    v=await state(actor,id);
  }
  assert.ok(didDrag&&count<800);
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
  await a.locator(`[data-hand="${group[0]}"]`).click();await clicks(a,'batch');
  await a.locator(`[data-hand="${group[1]}"]`).click();await clicks(a,'attack-group');
  await revision(b,table.rev+1);
  const same=hands[def].find(c=>(c>>2)===(group[0]>>2));
  await b.locator(`[data-hand="${same}"]`).click();await clicks(b,'transfer');await revision(a,table.rev+2);
  const view=await state(a,id),trump=view.game.trump,attack=view.game.table[0][0];
  const invalid=view.game.hand.find(c=>c%4===attack%4?c<attack:c%4!==trump);
  assert.notEqual(invalid,undefined);
  await a.locator(`[data-hand="${invalid}"]`).click();await a.locator('.dk-pair[data-slot="0"] .dk-tablecard').click();
  await revision(b,table.rev+3);await shot(b,'durak-midround');
  await clicks(b,'challenge-mode');await b.locator(`[data-dk=report][data-card="${invalid}"]`).click();
  await revision(a,table.rev+4);
  const after=await state(a,id);assert.ok(after.game.marked.includes(lead));
  assert.ok(after.game.hand.includes(invalid));assert.equal(after.game.table[0][1],null);
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
    await groupedTransferAndChallenge([a,b],privateId);
    await clicks(b,'game-info');await b.locator('#dk-surrender').click();await b.locator('#dk-confirm-leave').click();
    await ready(a,'.dk-result');await ready(b,'.dk-result');
    await clicks(a,'again');await choose(a,'speed','normal');await choose(a,'honesty','fair');await choose(a,'variant','throw');
    await a.locator('#dk-private').uncheck();await clicks(a,'create');await ready(a,'[data-dk=friends]');
    const played=await tableId(a);await clicks(b,'back');await enterOpen(b,2,played);
    await ready(a,'.dk-gamehead');await a.setViewportSize({width:390,height:844});await bounds(a);
    const turns=await throughTable([a,b],played);
    await shot(a,'durak-result');
    await clicks(a,'again');await choose(a,'deck',52);await choose(a,'players',6);await choose(a,'scope','all');
    await clicks(a,'create');await ready(a,'[data-dk=friends]');const six=await tableId(a);
    for(let i=1;i<players.length;i++){
      const p=players[i];
      if(i===1)await clicks(p,'back');
      if(i===5){await openGame(p,i+1);await p.locator(`[data-dk=quick][data-id="${six}"]`).click();await ready(p,'.dk-gamehead')}
      else await enterOpen(p,i+1,six);
    }
    await Promise.all(players.map(p=>ready(p,'.dk-gamehead')));
    for(const p of players){
      const v=await state(p,six);assert.equal(v.members.length,6);assert.equal(v.game.hand.length,6);
    }
    await a.setViewportSize({width:320,height:568});await bounds(a);await shot(a,'durak-six-320');
    await a.setViewportSize({width:412,height:915});await bounds(a);await shot(a,'durak-six-android');
    await a.setViewportSize({width:844,height:390});await bounds(a);await shot(a,'durak-six-wide');
    assert.deepEqual(errors,[]);
    console.log(`Playwright passed: invitation, link, reload, real pointer drag, ${turns} table actions, payout, six authenticated clients and mobile geometry.`);
  }finally{await Promise.all([browser.close(),safari?.close()])}
}
main().catch(err=>{console.error(err.stack);process.exitCode=1});
