// Run with node tests/nora_world_controls.mjs. No browser, network or GPU required.
import assert from 'node:assert/strict';
import {readFile, writeFile, mkdtemp, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {setMaxListeners} from 'node:events';
import vm from 'node:vm';
import {webcrypto} from 'node:crypto';

setMaxListeners(0);
const web = new URL('../community_bot/web/', import.meta.url);
const temp = await mkdtemp(join(tmpdir(), 'nora-controls-'));
try {
  await writeFile(join(temp, 'three.core.mjs'), await readFile(new URL('vendor/three.core.js', web)));
  const module = (await readFile(new URL('vendor/three.module.js', web), 'utf8')).replaceAll('./three.core.js', './three.core.mjs');
  await writeFile(join(temp, 'three.module.mjs'), module);
  const Three = await import(pathToFileURL(join(temp, 'three.module.mjs')).href);
  const world = (await readFile(new URL('nora-world.js', web), 'utf8')).replace("await import('/vendor/three.module.js')", 'THREE');
  const wings = await readFile(new URL('nora-wings.js', web), 'utf8');
  const voxel = await readFile(new URL('nora-voxel.js', web), 'utf8');
  const companion = await readFile(new URL('nora-companion.js', web), 'utf8');
  class Element extends EventTarget {
    open=false; dataset = {}; style = {}; clientWidth = 390; clientHeight = 780; isConnected = true;
    children = new Map();
    querySelector(selector) { if(selector==='.nora-settings[open]')return null; if (!this.children.has(selector)) this.children.set(selector, new Element()); return this.children.get(selector); }
    setAttribute() {} setPointerCapture() {} blur() {}
    showModal(){this.open=true;} close(){this.open=false;this.emit('close');}
    getBoundingClientRect() { return {left:0, top:0, width:120, height:120}; }
    getContext() { return {createRadialGradient:()=>({addColorStop(){}}), fillRect(){}, fillText(){}}; }
    emit(type, values = {}) { const e = new Event(type, {cancelable:true}); Object.assign(e, values); this.dispatchEvent(e); }
  }
  const sceneryCode=await readFile(new URL('nora-scenery.js',web),'utf8');
  const sceneryWindow={matchMedia:()=>({matches:false})};
  vm.runInNewContext(sceneryCode,{window:sceneryWindow});
  const sharedGeometry=new Three.BoxGeometry(),sharedMaterial=new Three.MeshLambertMaterial();
  const tavern=sceneryWindow.NoraScenery.create(Three,sharedGeometry,sharedMaterial);
  const record=tavern.indoor.getObjectByName('nora-record'),notes=tavern.indoor.getObjectByName('nora-music-notes');
  assert.ok(record&&notes,'record player and notes are present');
  assert.equal(tavern.outdoor.getObjectByName('nora-tavern-windows').count,8,'windows on all four facades');
  const blocked={x:0,y:0,z:1.5};
  const acousticContext={window:{}};vm.runInNewContext(world,acousticContext);
  acousticContext.window.NoraWorld.move(blocked,0,-2,tavern.indoorZone);
  assert.ok(blocked.z>.7,'console blocks walking through its cabinet');
  const lobbyWalk={x:0,z:0};
  acousticContext.window.NoraWorld.move(lobbyWalk,20,0,tavern.lobbyZone);
  assert.equal(lobbyWalk.x,16.35,'the lobby is traversable across its wide central path');
  const movedHouse={x:0,z:0};
  acousticContext.window.NoraWorld.move(movedHouse,0,-5,tavern.outdoorZone);
  assert.ok(movedHouse.z < -2 && movedHouse.z > -2.6,'house collision follows its move to the back wall');
  const camera=new Three.PerspectiveCamera();camera.position.set(2,2,3);camera.lookAt(0,1,0);
  tavern.update(.5,true,0,camera);assert.ok(record.rotation.y<0,'record rotates');
  const noteMatrix=new Three.Matrix4();notes.getMatrixAt(0,noteMatrix);const beforeNote=noteMatrix.clone();
  tavern.update(.5,true,0,camera);notes.getMatrixAt(0,noteMatrix);assert.notDeepEqual(noteMatrix.elements,beforeNote.elements,'notes rise and change scale');
  const stoppedAngle=record.rotation.y;
  tavern.update(.5,true,0,camera,false);assert.equal(record.rotation.y,stoppedAngle,'switched-off record stops rotating');
  assert.equal(notes.visible,false,'off switch hides notes');
  tavern.update(.5,true,0,camera,true);assert.ok(record.rotation.y<stoppedAngle&&notes.visible,'switch resumes animation');
  tavern.update(.5,false,0,camera);
  const lobbyRecord=tavern.lobby.getObjectByName('nora-record');
  const lobbyNotes=tavern.lobby.getObjectByName('nora-music-notes');
  assert.equal(lobbyRecord.visible,false,'lobby deck starts empty');
  tavern.setLobbyRecord('dedzytwo');
  tavern.update(.5,false,0,camera,true,true);
  assert.ok(lobbyRecord.visible&&lobbyRecord.rotation.y<0&&lobbyNotes.visible,'lobby deck shows and spins its own disc');
  const lobbyAngle=lobbyRecord.rotation.y;
  tavern.update(.5,false,0,camera,false,true);
  assert.equal(lobbyRecord.rotation.y,lobbyAngle);
  assert.equal(lobbyNotes.visible,false);
  tavern.setLobbyRecord(null);
  assert.equal(lobbyRecord.visible,false,'ejecting clears the lobby deck');
  const lobbyDeckPosition=sceneryWindow.NoraScenery.lobbyDeck;
  const lobbyDeckApproach={x:lobbyDeckPosition.x,z:lobbyDeckPosition.z+1.5};
  acousticContext.window.NoraWorld.move(lobbyDeckApproach,0,-2,tavern.lobbyZone);
  assert.ok(lobbyDeckApproach.z>lobbyDeckPosition.z+.5,'the duplicated cabinet blocks walking through it');
  const acoustics=acousticContext.window.NoraWorld.tavernAcoustics;
  const doorway=acoustics(false,0,3.6),rear=acoustics(false,0,-3.6),far=acoustics(false,0,7);
  assert.ok(doorway.gain>far.gain&&far.gain>rear.gain,'doorway louder than distance and back wall');
  assert.ok(doorway.cutoff>rear.cutoff,'walls remove high frequencies');
  assert.ok(acoustics(true,0,2).gain>doorway.gain,'inside louder than outside');
  assert.ok(acoustics(false,-4,4).pan>0&&acoustics(false,4,4).pan<0,'stereo follows building direction');
  let geometryDisposed=false;sharedGeometry.addEventListener('dispose',()=>{geometryDisposed=true;});
  tavern.dispose();assert.equal(geometryDisposed,false,'scenery retains shared geometry ownership');
  sharedGeometry.dispose();sharedMaterial.dispose();
  console.log('NORA tavern: console collision, spinning record, animated notes, 8 windows, spatial music and cleanup passed.');
  async function setup(view = 0, fps = 60, petApi=async()=>({pet:null}), sounds, mobile=false, realScenery=false, equipped=null) {
    const window = new Element(), document = new Element(), root = new Element(), canvas = new Element();
    document.createElement = () => new Element();
    window.matchMedia=()=>({matches:mobile});window.devicePixelRatio=3;
    let resizeCallback;
    let frame, player, camera, scene, time = 0, now = Date.UTC(2026,10,2,0);
    const renderer = {ratio:1,resizes:0,setPixelRatio(value){this.ratio=value;}, setSize(w,h){this.width=w;this.height=h;this.resizes++;}, dispose(){}, render(s,c){camera=c;scene=s;}};
    const zone = {limit:100, boxes:[], cameraBoxes:[]};
    window.NoraScenery = {create:()=>({outdoor:new Three.Group(), indoor:new Three.Group(), outdoorZone:zone, indoorZone:zone, dispose(){}})};
    let randomSeed=42;const seededMath=Object.create(Math);seededMath.random=()=>((randomSeed=(randomSeed*1664525+1013904223)>>>0)/4294967296);
    const context = vm.createContext({window, document, Math:seededMath, THREE:{...Three, WebGLRenderer:function(){return renderer;}},
      auth:'test-auth',location:{protocol:'https:',host:'nora.invalid'},crypto:webcrypto, Date:class extends Date {static now(){return now;}}, api:petApi, esc:value=>String(value??'').replaceAll('<','&lt;'), AbortController, AbortSignal, ResizeObserver:class {constructor(callback){resizeCallback=callback;} observe(){} disconnect(){}},
      performance:{now:()=>time}, requestAnimationFrame:fn=>{frame=fn;return 1;}, cancelAnimationFrame(){}});
    if(realScenery)vm.runInContext(sceneryCode, context);
    vm.runInContext(wings, context);
    vm.runInContext(voxel, context);
    const createCharacter = window.NoraVoxel.createCharacter;
    window.NoraVoxel.createCharacter = (...args) => {const result=createCharacter(...args);player??=result.group;return result;};
    vm.runInContext(companion, context);
    vm.runInContext(world, context);
    const stop = await window.NoraWorld.mount(canvas, root, {shirt:'white',pants:'blue_slim',shoes:'white_stripes',wings:equipped}, sounds);
    for(let i=0;i<view;i++)root.querySelector('.nora-world-view').emit('click');
    const frames = count => {for(let i=0;i<count;i++)frame(time+=1000/fps);};
    frames(30);
    const key = (code, down=true) => window.emit(down?'keydown':'keyup',{code});
    const joystick = root.querySelector('.nora-world-joystick');
    const stick = (x,z,down=false) => joystick.emit(down?'pointerdown':'pointermove',{pointerId:1,clientX:60+x*36,clientY:60+z*36});
    const delta = count => {const before=player.position.clone();frames(count);return player.position.clone().sub(before);};
    return {window,canvas,root,joystick,player,zone,frames,key,stick,delta,stop,renderer,resize:resizeCallback,setFps:value=>{fps=value;},camera:()=>camera,scene:()=>scene,world:window.NoraWorld,setNow:value=>{now=value;}};
  }
  const povWorld=await setup();
  const fullDistance=povWorld.camera().position.distanceTo(povWorld.player.position);
  povWorld.root.emit('nora-pov',{detail:40});povWorld.frames(180);
  assert.ok(povWorld.camera().position.distanceTo(povWorld.player.position)<fullDistance*.7,'perspective slider changes camera distance');
  povWorld.root.emit('nora-pov',{detail:0});povWorld.frames(1);
  assert.equal(povWorld.player.visible,false,'zero perspective selects first person');
  povWorld.root.emit('nora-pov',{detail:100});povWorld.frames(180);
  assert.equal(povWorld.player.visible,true,'perspective restores third person');povWorld.stop();
  const mobileWorld=await setup(0,30,undefined,undefined,true);
  const r=mobileWorld.renderer;
  assert.ok(r.width*r.height*r.ratio**2<=420001,'Retina mobile buffer has a pixel budget');
  const initial=r.ratio, resizeCount=r.resizes;
  mobileWorld.resize();assert.equal(r.resizes,resizeCount,'unchanged resize does not reallocate canvas');
  mobileWorld.frames(180);assert.ok(r.ratio<initial,'sustained low FPS reduces drawing resolution');
  const low=r.ratio;mobileWorld.setFps(60);mobileWorld.frames(600);
  assert.ok(r.ratio>low&&r.ratio<=initial,'stable fast frames recover quality within the cap');
  mobileWorld.canvas.clientWidth=780;mobileWorld.canvas.clientHeight=390;mobileWorld.resize();
  mobileWorld.frames(1);assert.equal(mobileWorld.camera().aspect,2,'rotation updates projection');
  assert.ok(r.width*r.height*r.ratio**2<=420001,'landscape retains mobile pixel budget');
  mobileWorld.stop();
  console.log('NORA mobile rendering: Retina budget, resize deduplication, low-FPS adaptation, recovery and rotation passed.');
  for(const fps of [30,60,120]){
    const c=await setup(0,fps),meshes=[];c.player.traverse(m=>{if(m.isInstancedMesh)meshes.push(m);});
    c.zone.cameraBoxes.push([-100,100,-100,100,-100,100]);c.frames(1);
    assert.ok(meshes.every(m=>!m.visible&&m.material.opacity===0),'camera inside body hides all layers immediately');
    const distance=()=>c.camera().position.distanceTo(new Three.Vector3(c.player.position.x,1.1,c.player.position.z));
    assert.ok(distance()<=.551,'camera obeys obstruction');
    for(let i=0;i<5;i++){c.zone.cameraBoxes.length=0;c.frames(1);assert.ok(distance()<=.551,'single clear frame does not pump camera');c.zone.cameraBoxes.push([-100,100,-100,100,-100,100]);c.frames(1);}
    c.zone.cameraBoxes.length=0;let previousDistance=distance(),previousOpacity=0;
    for(let i=0;i<fps*4;i++){
      c.frames(1);const current=distance(),alpha=meshes[0].material.opacity;
      assert.ok(current>=previousDistance-1e-6&&current-previousDistance<=3/fps+.001,'camera returns monotonically at bounded speed');
      assert.ok(alpha>=previousOpacity-1e-6,'model fades back without layer popping');
      if(current<=1.4)assert.equal(alpha,0,'background fully clear inside body');
      assert.ok(meshes.every(m=>!m.material.transparent&&m.material.depthWrite),'depth retained throughout fade');
      previousDistance=current;previousOpacity=alpha;
    }
    assert.ok(previousDistance>5&&previousOpacity===1,'camera and opaque character fully recover');c.stop();
  }
  console.log('NORA close camera: full hide, stable corners, bounded smooth return and depth-safe recovery at 30/60/120 FPS passed.');
  const soundEvents=[];
  const sounds={playing:value=>soundEvents.push(['playing',value]),spatial:()=>{},update:(...args)=>soundEvents.push(['update',...args]), jump:inside=>soundEvents.push(['jump',inside]),
    land:inside=>soundEvents.push(['land',inside]), door:inside=>soundEvents.push(['door',inside]), stop:()=>soundEvents.push(['stop'])};
  const audioWorld=await setup(0,60,undefined,sounds);
  audioWorld.key('Space'); audioWorld.frames(60);
  assert.ok(soundEvents.some(e=>e[0]==='jump'&&!e[1]));
  assert.ok(soundEvents.some(e=>e[0]==='land'&&!e[1]));
  audioWorld.player.position.set(0,.017,3.6);audioWorld.root.querySelector('.nora-world-action').emit('click');
  audioWorld.frames(2);audioWorld.key('Space');audioWorld.frames(60);
  assert.ok(soundEvents.some(e=>e[0]==='door'&&e[1]));
  assert.ok(soundEvents.some(e=>e[0]==='update'&&e[1]));
  assert.ok(soundEvents.some(e=>e[0]==='jump'&&e[1]));
  assert.ok(soundEvents.some(e=>e[0]==='land'&&e[1]));
  const recordButton=audioWorld.root.querySelector('.nora-record-toggle');
  assert.equal(recordButton.hidden,true,'record control hidden far away');
  audioWorld.player.position.set(0,.017,1.3);audioWorld.frames(2);
  assert.equal(recordButton.hidden,false,'record control shown beside console');
  recordButton.emit('click');assert.equal(recordButton.textContent,'Включить проигрыватель');
  assert.ok(soundEvents.some(e=>e[0]==='playing'&&e[1]===false));
  audioWorld.player.position.set(0,.017,3.7);audioWorld.root.querySelector('.nora-world-action').emit('click');audioWorld.frames(2);
  assert.equal(recordButton.hidden,true,'record control hidden outside');
  const countPlaying=soundEvents.filter(e=>e[0]==='playing').length;
  recordButton.emit('click');assert.equal(soundEvents.filter(e=>e[0]==='playing').length,countPlaying,'cannot toggle from outside');
  audioWorld.root.querySelector('.nora-world-action').emit('click');audioWorld.player.position.set(0,.017,1.3);audioWorld.frames(2);
  assert.equal(recordButton.textContent,'Включить проигрыватель','door transition preserves off state');
  recordButton.emit('click');assert.equal(recordButton.textContent,'Выключить проигрыватель');
  audioWorld.stop();assert.equal(soundEvents.at(-1)[0],'stop');
  function screenDelta(h, delta) {
    const forward = h.camera().getWorldDirection(new Three.Vector3()); forward.y=0; forward.normalize();
    const right = new Three.Vector3(-forward.z,0,forward.x);
    return {x:delta.dot(right), z:-delta.dot(forward)};
  }
  function aligned(actual,x,z,label) {
    const length=Math.hypot(actual.x,actual.z), input=Math.hypot(x,z);
    assert.ok(length>.1, label+': moved');
    assert.ok((actual.x*x+actual.z*z)/(length*input)>.995, label+': screen direction');
  }
  // Sustained and repeated inputs must stay screen-relative, not merely move
  // in a fixed world direction while the camera swings away underneath them.
  for(const view of [0,1,2])for(const device of ['keyboard','touch']) {
    const h=await setup(view);
    const speeds=[];
    for(const [x,z] of [[-1,0],[1,0],[0,-1],[0,1],[-1,-1],[1,-1],[-1,1],[1,1]]) {
      const codes=[x<0?'KeyA':x>0?'KeyD':null,z<0?'KeyW':z>0?'KeyS':null].filter(Boolean);
      if(device==='keyboard')codes.forEach(c=>h.key(c));else h.stick(x,z,true);
      h.frames(20);
      const d=h.delta(60);aligned(screenDelta(h,d),x,z,`${device}/${view}/${x},${z}`);speeds.push(d.length());
      const facing=new Three.Vector3(Math.sin(h.player.rotation.y),0,Math.cos(h.player.rotation.y));
      assert.ok(facing.dot(d.clone().normalize())>.999,'character faces travel in every view/direction');
      if(device==='keyboard')codes.forEach(c=>h.key(c,false));else h.joystick.emit('pointerup',{pointerId:1});
      h.frames(20);
    }
    assert.ok(Math.max(...speeds)-Math.min(...speeds)<.01,'no diagonal speed boost');
    h.stop();
  }
  const h=await setup();
  const startHeading=h.player.rotation.y;
  h.key('KeyA');h.frames(1);
  const firstTurn=Math.abs(Math.atan2(Math.sin(h.player.rotation.y-startHeading),Math.cos(h.player.rotation.y-startHeading)));
  assert.ok(firstTurn>.01&&firstTurn<.5,'turn starts smoothly instead of snapping');
  h.frames(60);h.key('KeyA',false);h.frames(30);
  const idleHeading=h.player.rotation.y;
  h.frames(60);assert.equal(h.player.rotation.y,idleHeading,'idle preserves facing');
  h.key('KeyA');h.frames(60);h.key('KeyA',false);h.frames(20);
  h.key('KeyA');aligned(screenDelta(h,h.delta(60)),-1,0,'repeated left');h.key('KeyA',false);
  h.key('KeyW');h.frames(20);h.key('KeyD');h.frames(20);
  aligned(screenDelta(h,h.delta(30)),1,-1,'W then W+D');
  h.key('KeyW',false);h.frames(20);aligned(screenDelta(h,h.delta(30)),1,0,'release W, hold D');
  h.key('KeyD',false);h.frames(20);
  h.stick(0,-1,true);
  for(const angle of [Math.PI/4,Math.PI/2,Math.PI,Math.PI*1.5,Math.PI*2]) {
    const x=Math.cos(angle),z=Math.sin(angle);h.stick(x,z);h.frames(20);
    aligned(screenDelta(h,h.delta(20)),x,z,'continuous joystick turn');
  }
  h.stick(-1,0);
  h.canvas.emit('pointerdown',{pointerId:2,clientX:0,clientY:0});
  h.canvas.emit('pointermove',{pointerId:2,clientX:200,clientY:0});
  h.frames(40);aligned(screenDelta(h,h.delta(30)),-1,0,'left after manual camera turn while holding');
  h.joystick.emit('pointercancel',{pointerId:1});h.frames(25);assert.ok(h.delta(30).length()<.001,'touch cancel stops');
  h.key('KeyW');h.frames(20);h.window.emit('blur');assert.ok(h.delta(30).length()<.001,'blur stops');
  h.key('Space');h.frames(10);assert.ok(h.player.position.y>.1,'jump');h.frames(60);assert.equal(h.player.position.y,.017,'lands');
  h.stop();
  for (const fps of [30,60,120]) {
    const peaks=[];
    let normalPeak=0;
    for (const id of [null,'raven','flame','frost']) {
      const w=await setup(0,fps,undefined,undefined,fps===30,false,id);
      const model=w.player.getObjectByName('wings');
      assert.equal(Boolean(model),Boolean(id));
      if (model) {
        assert.equal(model.parent.name,'torso');
        assert.ok(Math.abs(model.scale.x/model.scale.z-1.5)<1e-9);
        assert.ok(Math.abs(model.scale.y/model.scale.z-1.5)<1e-9);
        const meshes=[];
        model.traverse(mesh=>{if(mesh.isMesh)meshes.push(mesh);});
        assert.equal(meshes.length,4);
        assert.equal(meshes[0].material.map.magFilter,Three.NearestFilter);
        assert.equal(meshes[0].geometry,meshes[2].geometry);
        assert.equal(meshes[0].material.emissiveMap.magFilter,Three.NearestFilter);
        const sparks=model.getObjectByName('wing-sparks');
        assert.equal(sparks.geometry.attributes.position.count,12);
        assert.equal(sparks.material.transparent,true);
        assert.equal(sparks.material.depthWrite,false);
        const beforeSparks=sparks.geometry.attributes.position.array.slice();
        const idle=model.children[0].rotation.y;
        w.frames(3);
        assert.notEqual(model.children[0].rotation.y,idle);
        assert.notDeepEqual(sparks.geometry.attributes.position.array,beforeSparks);
      }
      const jump=()=>{
        if(fps!==30){w.key('Space');return;}
        const button=w.root.querySelector('.nora-world-jump');
        button.emit('pointerdown',{button:0,pointerType:'touch'});
        w.frames(1);
        button.emit('click',{detail:1,pointerType:'touch'});
      };
      function flight(seconds) {
        let peak=0, fastestFall=0;
        for(let i=0;i<fps*seconds;i++){
          const before=w.player.position.y;
          w.frames(1);
          peak=Math.max(peak,w.player.position.y-.017);
          fastestFall=Math.max(fastestFall,(before-w.player.position.y)*fps);
        }
        assert.equal(w.player.position.y,.017);
        return {peak,fastestFall};
      }
      jump();
      const single=flight(1);
      if(!id)normalPeak=single.peak;
      else assert.equal(single.peak,normalPeak,'one tap retains ordinary jump');
      jump();w.frames(Math.round(fps*.25));jump();
      w.frames(Math.round(fps*.12));jump(); // A third press cannot add another impulse.
      const {peak,fastestFall}=flight(2);
      if (id) {
        assert.ok(peak>2.2&&peak<2.56);
        assert.ok(fastestFall<=3.401,'second jump caps descending speed');
        jump();w.frames(Math.round(fps*.25));jump();
        assert.ok(flight(2).peak>2.2,'landing recharges the wing boost');
      } else assert.ok(peak<=normalPeak,'unequipped players cannot double jump');
      peaks.push(peak);
      w.stop();
    }
    assert.equal(peaks[1],peaks[2]);assert.equal(peaks[2],peaks[3]);
  }
  const ceiling=await setup(0,60,undefined,undefined,false,true,'flame');
  ceiling.player.position.set(0,.017,3.6+ceiling.window.NoraScenery.tavernOffset);
  ceiling.root.querySelector('.nora-world-action').emit('click');
  ceiling.key('Space');ceiling.frames(15);ceiling.key('Space');
  let indoorPeak=0;
  for(let i=0;i<120;i++){
    ceiling.frames(1);
    indoorPeak=Math.max(indoorPeak,ceiling.player.position.y);
  }
  assert.equal(indoorPeak,1.517,'tavern ceiling stops the second jump');
  assert.equal(ceiling.player.position.y,.017);
  ceiling.stop();
  const env=await setup();
  const api=env.world;
  assert.equal(api.timeOfDay(Date.UTC(2026,10,2,0)).hour,3,'Moscow UTC+3');
  assert.equal(api.timeOfDay(Date.UTC(2026,10,2,22)).hour,1,'Moscow date rollover');
  assert.equal(api.timeOfDay(Date.UTC(2026,10,2,9)).daylight,1,'Moscow noon');
  assert.equal(api.timeOfDay(Date.UTC(2026,10,2,21)).daylight,0,'Moscow midnight');
  let previousDay=api.timeOfDay(Date.UTC(2026,10,2,0)).daylight;
  for(let minute=1;minute<=1440;minute++){
    const phase=api.timeOfDay(Date.UTC(2026,10,2,0,minute));
    assert.ok(Math.abs(phase.daylight-previousDay)<.015,'smooth day/night transition');previousDay=phase.daylight;
  }
  const scene=env.scene(),stars=scene.getObjectByName('nora-stars'),leaves=scene.getObjectByName('nora-leaves');
  assert.equal(stars.count,112);assert.equal(leaves.count,128);
  const nightLight=scene.children.find(o=>o.isHemisphereLight).intensity;
  assert.ok(stars.visible&&stars.material.opacity>.5,'stars at night');
  const beforeStars=stars.instanceMatrix.array.slice(),beforeLeaves=leaves.instanceMatrix.array.slice();
  env.frames(90);
  assert.notDeepEqual(stars.instanceMatrix.array,beforeStars,'stars twinkle individually');
  assert.notDeepEqual(leaves.instanceMatrix.array,beforeLeaves,'leaves drift and fragment');
  assert.ok([...leaves.instanceMatrix.array].every(Number.isFinite),'finite particle transforms');
  let vanished=0;
  for(let i=0;i<leaves.count;i++)if(leaves.instanceMatrix.array[i*16]===0)vanished++;
  assert.ok(vanished>0&&vanished<128,'some voxel fragments dissolve in flight');
  env.setNow(Date.UTC(2026,10,2,9));env.frames(1);
  assert.equal(stars.visible,false,'no daytime stars');
  assert.ok(scene.children.find(o=>o.isHemisphereLight).intensity>nightLight,'day brighter, night remains playable');
  env.player.position.set(0,.017,3.6);env.root.querySelector('.nora-world-action').emit('click');env.frames(1);
  assert.equal(leaves.visible,false,'no outdoor leaves in tavern');assert.equal(stars.visible,false);
  let disposed=0;
  stars.material.addEventListener('dispose',()=>disposed++);leaves.material.addEventListener('dispose',()=>disposed++);
  env.stop();assert.equal(disposed,2,'effect materials released');assert.equal(scene.getObjectByName('nora-stars'),undefined);
  const motionWorld=await setup();
  const joint=name=>motionWorld.player.getObjectByName(name);
  const footY=side=>joint('foot'+side).getWorldPosition(new Three.Vector3()).y;
  const standingFoot=footY('Left');
  const thighSplit=()=>Math.abs(joint('thighLeft').rotation.x-joint('thighRight').rotation.x);
  motionWorld.key('Space');motionWorld.frames(12);
  assert.ok(motionWorld.player.position.y>.4&&joint('shinLeft').rotation.x>.75,'standing jump tucks both knees');
  assert.ok(thighSplit()<.01&&joint('armLeft').rotation.x<-.65,'standing jump lifts both arms symmetrically');
  const tuckedKnee=joint('shinLeft').rotation.x;
  motionWorld.frames(25);
  assert.ok(motionWorld.player.position.y>.017&&joint('shinLeft').rotation.x<tuckedKnee-.2,'legs extend during descent');
  motionWorld.frames(35);
  assert.ok(Math.abs(joint('shinLeft').rotation.x)<.001,'landing returns to standing');
  motionWorld.key('KeyW');motionWorld.frames(30);
  for(const [sprinting,clearance] of [[false,.13],[true,.20]]){
    motionWorld.key('ShiftLeft',sprinting);motionWorld.frames(45);
    const lifted=new Set();
    for(let frame=0;frame<60;frame++){
      motionWorld.frames(1);
      for(const [swing,stance] of [['Left','Right'],['Right','Left']]){
        if(footY(swing)-standingFoot>clearance&&Math.abs(footY(stance)-standingFoot)<.005)lifted.add(swing);
      }
    }
    assert.equal(lifted.size,2,'both feet clear the ground in turn while the other foot supports the avatar');
  }
  const beforeJumpZ=motionWorld.player.position.z;
  motionWorld.key('Space');motionWorld.frames(12);
  assert.ok(motionWorld.player.position.y>.4&&beforeJumpZ-motionWorld.player.position.z>.55,'running jump travels forward');
  assert.ok(thighSplit()>.8&&joint('torso').rotation.x>.22,'moving jump splits the legs and leans into travel');
  motionWorld.frames(60);
  assert.equal(motionWorld.player.position.y,.017);
  assert.ok(joint('armLeft').rotation.x>.6,'landing resumes the running pose');
  motionWorld.stop();

  const runner=await setup();runner.key('KeyD');runner.frames(30);
  const walking=runner.delta(30).length();runner.key('ShiftLeft');runner.frames(30);
  assert.ok(runner.delta(30).length()>walking*1.65,'Shift accelerates');
  assert.ok(runner.player.getObjectByName('torso').rotation.x>.2,'running leans forward');
  assert.ok(runner.player.getObjectByName('armLeft').rotation.x>.6,'arms trail behind');
  assert.ok(Math.abs(runner.player.getObjectByName('forearmLeft').rotation.x)<.03,'running elbows straighten');
  runner.key('ShiftLeft',false);runner.frames(60);
  assert.ok(runner.player.getObjectByName('torso').rotation.x<.04,'walk pose returns smoothly');
  runner.root.querySelector('.nora-world-sprint').emit('click');runner.frames(30);
  assert.ok(runner.delta(30).length()>walking*1.65,'touch sprint accelerates');runner.stop();
  const flush=()=>new Promise(resolve=>setImmediate(resolve));
  for(const species of ['cat','dog','fox','raccoon','dragon']) {
    let current={name:'<Друг>',species,species_label:species,hunger:72,thirst:83,enabled:true,expedition_until:null};
    const calls=[];
    const petApi=async(path,body)=>{calls.push([path,body]);if(path==='pet/prepare')return {token:'owner-token'};
      if(path==='pet/action'){current={...current,expedition_until:'2026-11-03T12:00:00Z'};return {ok:true,message:'В походе'};}
      return {pet:current};};
    const h=await setup(0,60,petApi);await flush();h.frames(1);
    const pet=h.scene().getObjectByName('nora-companion');assert.ok(pet,'existing '+species+' appears');
    assert.ok(pet.children[0].count<1500,'bounded voxel model');
    const actions=h.root.querySelector('.nora-pet-actions');assert.equal(actions.hidden,false,'nearby actions');
    h.root.querySelector('.nora-pet-stroke').emit('click');h.frames(1);
    const hearts=h.scene().getObjectByName('nora-pet-hearts');assert.equal(hearts.visible,true,'petting hearts');
    const alpha=hearts.material.opacity;h.frames(40);assert.ok(hearts.material.opacity<alpha,'hearts fade');
    h.frames(80);assert.equal(hearts.visible,false,'hearts expire');
    h.zone.boxes.push([1,2,3,4]);
    for(const [key,count] of [['KeyD',120],['KeyW',130],['KeyA',100]]){
      h.key(key);
      for(let i=0;i<count;i++){h.frames(1);assert.ok(!(pet.position.x>.66&&pet.position.x<2.34&&pet.position.z>2.66&&pet.position.z<4.34),'follower avoids furniture');}
      h.key(key,false);
    }
    h.frames(300);assert.ok(pet.position.distanceTo(h.player.position)<3.5,`follows around corners: ${pet.position.toArray()} / ${h.player.position.toArray()}`);
    h.player.position.copy(pet.position);h.player.position.x-=.5;h.frames(1);
    h.root.querySelector('.nora-pet-open').emit('click');await flush();
    const panel=h.root.querySelector('.nora-pet-panel'),body=panel.querySelector('.nora-pet-content');
    assert.ok(panel.open);assert.ok(body.innerHTML.includes('72 / 100'));assert.ok(body.innerHTML.includes('&lt;Друг>'),'name escaped');
    h.key('KeyW');assert.ok(h.delta(40).length()<.001,'panel blocks movement');
    body.closest=()=>true;body.emit('click');body.emit('click');await flush();
    assert.equal(calls.filter(([path])=>path==='pet/action').length,1,'one expedition request');
    assert.equal(h.scene().getObjectByName('nora-companion'),undefined,'away pet disappears');
    panel.close();current={...current,expedition_until:null};h.frames(1900);await flush();h.frames(1);
    assert.ok(h.scene().getObjectByName('nora-companion'),'pet returns after server sync');
    h.player.position.set(0,.017,3.6);h.root.querySelector('.nora-world-action').emit('click');h.frames(1);
    assert.ok(h.scene().getObjectByName('nora-companion').position.distanceTo(h.player.position)<1,'follows into tavern');
    h.stop();assert.equal(h.scene().getObjectByName('nora-companion'),undefined,'pet disposed');
  }
  const wander=await setup(0,60,async()=>({pet:{name:'Лис',species:'fox',species_label:'лиса',hunger:80,thirst:80,enabled:true,expedition_until:null}}));
  await flush();wander.frames(1);const wanderingPet=wander.scene().getObjectByName('nora-companion'),start=wanderingPet.position.clone();
  wander.key('KeyW');wander.frames(30);wander.key('KeyW',false);wander.frames(20);
  assert.ok(wanderingPet.position.distanceTo(start)<.01,'pet does not follow small owner movement');
  const idleStart=wanderingPet.position.clone();wander.frames(600);
  assert.ok(wanderingPet.position.distanceTo(idleStart)>.1,'pet ambles while owner waits');
  assert.ok(wanderingPet.position.distanceTo(wander.player.position)<3.5,'ambling stays nearby');
  wander.key('KeyW');wander.frames(160);wander.key('KeyW',false);wander.frames(260);
  const separation=wanderingPet.position.distanceTo(wander.player.position);
  assert.ok(separation<3.5&&separation>1.3,'pet catches up from far away but keeps a comfortable distance');
  wander.stop();console.log('NORA companion: relaxed wandering, delayed following and distance passed.');
  let resolvePet;
  const late=await setup(0,60,()=>new Promise(resolve=>{resolvePet=resolve;}));late.stop();resolvePet({pet:{species:'cat'}});await flush();
  assert.equal(late.scene().getObjectByName('nora-companion'),undefined,'late response cannot recreate disposed pet');
  console.log('NORA companion: 5 species, collision-aware following, panel, expedition, return, hearts and disposal passed.');
  const exchanges=[];
  let remoteTime=0,dropReply=false,remoteOffset=0,remoteTakeoff=Infinity;
  const lobbyWorld=await setup(0,60,async(path,body)=>{
    if(path!=='nora-game/lobby')return {pet:null};
    exchanges.push(body);
    if(dropReply&&!body.leave)throw Error('temporary loss');
    const jumpTime=(remoteTime-remoteTakeoff)/1000;
    const height=jumpTime>0?Math.max(0,4.4*jumpTime-6.5*jumpTime**2):0;
    return {time:remoteTime,players:body.leave?[]:[{
      nickname:'Robin',outfit:{shirt:'white',pants:'blue_slim',shoes:'white_stripes'},
      x:2+remoteTime*.003+remoteOffset,y:.017+height,z:4,heading:remoteTime<750?3.13:-3.13,grounded:height===0,time:remoteTime,
    }]};
  },undefined,false,true);
  const lobbyAction=lobbyWorld.root.querySelector('.nora-world-action');
  assert.equal(lobbyAction.hidden,true,'portal button only appears nearby');
  lobbyWorld.player.position.set(0,.017,5.6);lobbyWorld.frames(1);
  assert.equal(lobbyAction.textContent,'ЛОББИ');assert.equal(lobbyAction.hidden,false);
  lobbyAction.emit('click');remoteTime=1000/60*32;lobbyWorld.frames(1);await flush();
  const hasPeer=()=>lobbyWorld.scene().children.find(node=>node.children.some(child=>child.isSprite));
  assert.ok(hasPeer(),'authenticated lobby snapshot creates a labeled avatar');
  let previousX=hasPeer().position.x;
  for(let i=0;i<34;i++){
    remoteTime+=1000/60;lobbyWorld.frames(1);await flush();
    const peer=hasPeer();
    if(i>12){
      assert.ok(Math.abs(peer.position.x-previousX-.05)<.001,'steady running has constant frame-to-frame speed');
      assert.ok(Math.abs(2+remoteTime*.003-peer.position.x-.45)<.001,'steady playback trails the sender by 150 ms');
      assert.ok(Math.abs(peer.rotation.y)>3,'turning across pi uses the short arc');
    }
    previousX=peer.position.x;
  }
  assert.ok(exchanges.length>=7,'movement is exchanged more often than every 400 ms');
  dropReply=true;
  for(let i=0;i<30;i++){
    remoteTime+=1000/60;lobbyWorld.frames(1);await flush();
  }
  assert.ok(hasPeer(),'temporary packet loss preserves the remote avatar');
  assert.ok(hasPeer().position.x-previousX<.8,'prediction stops during a connection gap');
  dropReply=false;
  for(let i=0;i<18;i++){
    previousX=hasPeer().position.x;
    remoteTime+=1000/60;lobbyWorld.frames(1);await flush();
    assert.ok(Math.abs(hasPeer().position.x-previousX)<=.081,'recovering after delayed data does not snap');
  }
  assert.ok(hasPeer().position.x>previousX,'movement resumes after the connection recovers');
  remoteOffset=8;
  for(let i=0;i<6;i++){
    remoteTime+=1000/60;lobbyWorld.frames(1);await flush();
  }
  assert.ok(hasPeer().position.x>10,'remote teleport discards the old movement samples');
  remoteTakeoff=remoteTime;
  for(let i=0;i<25;i++){
    remoteTime+=1000/60;lobbyWorld.frames(1);await flush();
  }
  const peer=hasPeer();
  const remoteSplit=peer.getObjectByName('thighRight').rotation.x-peer.getObjectByName('thighLeft').rotation.x;
  assert.ok(peer.position.y>.4&&remoteSplit>.8,'remote movement snapshots drive the forward jump pose');
  lobbyWorld.player.position.set(0,.017,8.6);lobbyWorld.frames(1);
  assert.equal(lobbyAction.textContent,'НА ОСТРОВ');
  lobbyAction.emit('click');await flush();
  assert.ok(exchanges.at(-1).leave,'returning to the island leaves the shared lobby');
  assert.ok(!hasPeer(),'remote avatars are removed from the island');
  lobbyWorld.stop();
  console.log('NORA lobby: portals, smooth movement, short-arc turning, packet loss and recovery passed.');
  // Delay all server replies: outgoing poses must still stream at 80 ms.
  const sockets=[],fallback=[];
  const streamed=await setup(0,60,async(path,body)=>{
    if(path==='nora-game/lobby')fallback.push(body);
    return {players:[]};
  },undefined,false,true);
  streamed.window.WebSocket=class {
    readyState=0;bufferedAmount=0;sent=[];
    constructor(url){assert.equal(url,'wss://nora.invalid/nora-game/socket');sockets.push(this);}
    send(raw){this.sent.push(JSON.parse(raw));}
    close(){this.readyState=3;this.onclose?.();}
  };
  streamed.player.position.set(0,.017,5.6);streamed.frames(1);
  streamed.root.querySelector('.nora-world-action').emit('click');streamed.frames(1);await flush();
  const ws=sockets[0];ws.readyState=1;ws.onopen();
  assert.deepEqual(ws.sent[0],{auth:'test-auth'},'credentials are in the first frame, never the URL');
  streamed.frames(60);
  const poses=ws.sent.filter(body=>body.session);
  assert.ok(poses.length>=11,'stream sends poses without waiting for delayed replies');
  const beforeCongestion=ws.sent.length;ws.bufferedAmount=20000;streamed.frames(12);
  assert.equal(ws.sent.length,beforeCongestion,'congested socket does not queue obsolete poses');
  ws.bufferedAmount=0;
  ws.close();streamed.frames(6);await flush();
  assert.ok(fallback.length>=2,'closed WebSocket falls back to HTTP');
  streamed.stop();

  let slowTime=0;
  const slow=await setup(0,60,async(path,body)=>({time:slowTime,players:path==='nora-game/lobby'&&!body.leave?[{
    nickname:'Slow',outfit:{shirt:'white',pants:'blue_slim',shoes:'white_stripes'},
    x:slowTime*.0017,y:.017,z:4,heading:0,grounded:true,time:Math.floor(slowTime/1100)*1100,
  }]:[]}),undefined,false,true);
  slow.player.position.set(0,.017,5.6);slow.frames(1);slow.root.querySelector('.nora-world-action').emit('click');
  let previous=null,movingFrames=0,maxStep=0,legMin=Infinity,legMax=-Infinity;
  for(let i=0;i<240;i++){
    slowTime+=1000/60;slow.frames(1);await flush();
    const avatar=slow.scene().children.find(node=>node.children.some(child=>child.isSprite));
    if(!avatar)continue;
    if(previous!==null){const step=Math.abs(avatar.position.x-previous);maxStep=Math.max(maxStep,step);if(step>.001)movingFrames++;}
    previous=avatar.position.x;
    const leg=avatar.getObjectByName('thighRight').rotation.x;legMin=Math.min(legMin,leg);legMax=Math.max(legMax,leg);
  }
  assert.ok(maxStep<=.081,'1.1 second snapshot gaps do not teleport the remote avatar');
  assert.ok(movingFrames>100,'rare snapshots animate movement across many frames');
  assert.ok(legMax-legMin>.2,'remote legs keep walking when snapshots arrive once a second');
  slow.stop();
  console.log('NORA realtime: delayed replies, congestion, HTTP fallback and one-second snapshot animation passed.');

  const parkour=await setup(0,60,undefined,undefined,false,true);
  const parkourAction=parkour.root.querySelector('.nora-world-action');
  parkour.player.position.set(0,.017,5.6);parkour.frames(1);parkourAction.emit('click');
  const plate=parkour.scene().getObjectByName('nora-parkour-plate');
  const finish=parkour.scene().getObjectByName('nora-parkour-finish');
  const raisedY=plate.position.y;
  const jump=()=>{parkour.key('Space');parkour.key('Space',false);};
  const jumpToPenultimate=()=>{
    parkour.player.position.set(8.6,.017,10.55);
    parkour.frames(1);
    for(const [z,top] of [[9.15,.34],[7.45,.68],[5.8,1.02],[4.15,1.36]]){
      parkour.key('ShiftLeft');parkour.key('KeyW');jump();
      for(let i=0;i<42&&parkour.player.position.z>z+.08;i++)parkour.frames(1);
      parkour.key('KeyW',false);parkour.key('ShiftLeft',false);parkour.frames(24);
      assert.equal(parkour.player.position.y,top+.017,'each platform is reachable without wings');
    }
  };
  parkour.player.position.set(8.2,.017,1.23);parkour.frames(12);
  assert.equal(plate.position.y,raisedY,'the finish does not activate on ground level');
  jumpToPenultimate();
  parkour.key('KeyW');
  for(let i=0;i<40&&parkour.player.position.z>3.48;i++)parkour.frames(1);
  assert.equal(parkour.player.position.y,1.36+.017,'the walking jump starts on the edge');
  jump();parkour.frames(64);parkour.key('KeyW',false);
  assert.equal(parkour.player.position.y,.017,'a walking jump from the lip falls short');
  assert.equal(plate.position.y,raisedY);
  parkour.frames(24);
  for(let lap=0;lap<2;lap++){
    jumpToPenultimate();
    parkour.key('ShiftLeft');parkour.key('KeyW');
    for(let i=0;i<25&&parkour.player.position.z>3.55;i++)parkour.frames(1);
    jump();
    for(let i=0;i<44&&plate.position.y===raisedY;i++)parkour.frames(1);
    assert.equal(parkour.player.position.y,1.7+.017,'a sprint jump lands on the finish');
    assert.ok(plate.position.y<raisedY,'landing depresses the plate automatically');
    assert.equal(finish.material.color.getHexString(),'42d76b','the whole finish changes to green');
    assert.equal(parkourAction.hidden,true,'the finish needs no manual action');
    parkour.frames(5);
    assert.ok(Math.abs(plate.position.y-(raisedY-.06))<1e-8,'the plate finishes depressing before teleport');
    parkour.frames(8);
    assert.deepEqual(parkour.player.position.toArray(),[8.2,.017,10.55],'the flash is followed by teleport to start');
    assert.equal(plate.position.y,raisedY,'the plate rises again');
    assert.equal(plate.material.color.getHexString(),'d1d4da');
    assert.equal(finish.material.color.getHexString(),'777b83');
  }
  parkour.stop();
  console.log('NORA parkour: sprint-only ordinary jump, automatic pressure plate, teleport and reset passed.');
  const recordsCode=await readFile(new URL('nora-records.js',web),'utf8');
  function widget(){
    const children=[],listeners={};
    return {children,listeners,dataset:{},append(...nodes){children.push(...nodes);},setAttribute(){},
      addEventListener(type,fn){listeners[type]=fn;},querySelectorAll(){return [];},
      querySelector(){return null;},showModal(){this.open=true;},close(){this.open=false;},remove(){}};
  }
  const recordsRoot=widget(),recordsBar=widget(),recordsContext=widget();
  recordsRoot.querySelector=selector=>selector==='.nora-world-bar'?recordsBar:recordsContext;
  const collection={hand:'dedzytwo',player:'standard',shelf:[],inventory:Array(8).fill(null),revision:0};
  let shared={record:null,mine:false,playing:false,revision:0};
  const moves=[],tracks=[];
  const recordsWindow={};
  vm.runInNewContext(recordsCode,{window:recordsWindow,Image:class {},document:{createElement:widget},
    AbortController,AbortSignal,api:async(path,body)=>{
      if(path.includes('?'))return {...shared};
      if(body){
        moves.push(body.action);
        if(body.action==='pack'){collection.inventory[body.slot]=collection.hand;collection.hand=null;}
        if(body.action==='unpack'){collection.hand=collection.inventory[body.slot];collection.inventory[body.slot]=null;}
        if(body.action==='lobby_insert'){
          shared={record:collection.hand,mine:true,playing:true,revision:1};collection.hand=null;
          return {...collection,revision:++collection.revision,lobby_deck:shared};
        }
        collection.revision++;
      }
      return {...collection};
    }});
  const recordsController=recordsWindow.NoraRecords.mount(recordsRoot,{setLobbyRecord(){}},
    {record:url=>tracks.push(url)},()=>{});
  await flush();
  const inventoryPanel=recordsRoot.children[0],contextActions=recordsContext.children[0];
  const recordClick=(attr,dataset={})=>recordsRoot.listeners.click({
    target:{closest:()=>({hasAttribute:key=>key===attr,dataset})},
  });
  await recordClick('data-record-inventory');
  assert.equal([...inventoryPanel.innerHTML.matchAll(/data-record-slot=/g)].length,8);
  await recordClick('data-record-slot',{recordSlot:'2'});
  assert.equal(collection.inventory[2],'dedzytwo');
  await recordClick('data-record-close');
  recordsController.update(false,0,-3,true,false,true,true);
  await flush();
  await recordClick('data-record-inventory');
  await recordClick('data-record-slot',{recordSlot:'2'});
  await recordClick('data-record-close');
  assert.match(contextActions.innerHTML,/data-record-insert/);
  await recordClick('data-record-insert');
  assert.deepEqual(moves,['pack','unpack','lobby_insert']);
  assert.equal(tracks.at(-1),'/game/dedzytwo-s1.mp3');
  assert.ok(recordsController.lobbyPlaying());
  recordsController.update(false,0,0,true,false,false,false);
  assert.equal(tracks.at(-1),'/game/nora-theme.mp3');
  recordsController.dispose();
  console.log('NORA inventory: eight cells, pack, unpack, lobby insert and room audio passed.');
  const distances=[];
  for(const fps of [30,60,120]) {
    const h=await setup(0,fps);h.key('KeyA');h.frames(fps/2);distances.push(h.delta(fps).length());h.stop();
  }
  assert.ok(Math.max(...distances)-Math.min(...distances)<.01,'frame-rate independent speed');
  console.log('NORA atmosphere: Moscow time, smooth cycle, night stars, twinkle, leaf fragments, indoor visibility and disposal passed.');
  console.log('NORA controls: 8 directions, 3 views, keyboard/touch, chords, repeat, camera turn, stop, jump and 30/60/120 FPS passed.');
} finally {
  await rm(temp, {recursive:true, force:true});
}
