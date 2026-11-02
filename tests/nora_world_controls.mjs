// Run with node tests/nora_world_controls.mjs. No browser, network or GPU required.
import assert from 'node:assert/strict';
import {readFile, writeFile, mkdtemp, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {setMaxListeners} from 'node:events';
import vm from 'node:vm';

setMaxListeners(0);
const web = new URL('../community_bot/web/', import.meta.url);
const temp = await mkdtemp(join(tmpdir(), 'nora-controls-'));
try {
  await writeFile(join(temp, 'three.core.mjs'), await readFile(new URL('vendor/three.core.js', web)));
  const module = (await readFile(new URL('vendor/three.module.js', web), 'utf8')).replaceAll('./three.core.js', './three.core.mjs');
  await writeFile(join(temp, 'three.module.mjs'), module);
  const Three = await import(pathToFileURL(join(temp, 'three.module.mjs')).href);
  const world = (await readFile(new URL('nora-world.js', web), 'utf8')).replace("await import('/vendor/three.module.js')", 'THREE');
  const voxel = await readFile(new URL('nora-voxel.js', web), 'utf8');
  class Element extends EventTarget {
    style = {}; clientWidth = 390; clientHeight = 780; isConnected = true;
    children = new Map();
    querySelector(selector) { if (!this.children.has(selector)) this.children.set(selector, new Element()); return this.children.get(selector); }
    setAttribute() {} setPointerCapture() {} blur() {}
    getBoundingClientRect() { return {left:0, top:0, width:120, height:120}; }
    getContext() { return {createRadialGradient:()=>({addColorStop(){}}), fillRect(){}}; }
    emit(type, values = {}) { const e = new Event(type, {cancelable:true}); Object.assign(e, values); this.dispatchEvent(e); }
  }
  async function setup(view = 0, fps = 60) {
    const window = new Element(), document = new Element(), root = new Element(), canvas = new Element();
    document.createElement = () => new Element();
    let frame, player, camera, scene, time = 0, now = Date.UTC(2026,10,2,0);
    const renderer = {setPixelRatio(){}, setSize(){}, dispose(){}, render(s,c){camera=c;scene=s;}};
    const zone = {limit:100, boxes:[], cameraBoxes:[]};
    window.NoraScenery = {create:()=>({outdoor:new Three.Group(), indoor:new Three.Group(), outdoorZone:zone, indoorZone:zone, dispose(){}})};
    const context = vm.createContext({window, document, THREE:{...Three, WebGLRenderer:function(){return renderer;}},
      Date:{now:()=>now}, AbortController, ResizeObserver:class {observe(){} disconnect(){}},
      requestAnimationFrame:fn=>{frame=fn;return 1;}, cancelAnimationFrame(){}});
    vm.runInContext(voxel, context);
    const createCharacter = window.NoraVoxel.createCharacter;
    window.NoraVoxel.createCharacter = (...args) => {const result=createCharacter(...args);player=result.group;return result;};
    vm.runInContext(world, context);
    const stop = await window.NoraWorld.mount(canvas, root, {shirt:'white',pants:'blue_slim',shoes:'white_stripes'});
    for(let i=0;i<view;i++)root.querySelector('.nora-world-view').emit('click');
    const frames = count => {for(let i=0;i<count;i++)frame(time+=1000/fps);};
    frames(30);
    const key = (code, down=true) => window.emit(down?'keydown':'keyup',{code});
    const joystick = root.querySelector('.nora-world-joystick');
    const stick = (x,z,down=false) => joystick.emit(down?'pointerdown':'pointermove',{pointerId:1,clientX:60+x*36,clientY:60+z*36});
    const delta = count => {const before=player.position.clone();frames(count);return player.position.clone().sub(before);};
    return {window,canvas,root,joystick,player,zone,frames,key,stick,delta,stop,camera:()=>camera,scene:()=>scene,world:window.NoraWorld,setNow:value=>{now=value;}};
  }
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
