// Isolated audio graph test: no browser, device, network, or sound output.
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';
const code=await readFile(new URL('../community_bot/web/nora-game.js',import.meta.url),'utf8');
const begin=code.indexOf('  function createMusic()'),end=code.indexOf('\n  function close() {',begin);
const nodes=[];
const param=()=>({value:0,setTargetAtTime(value){this.value=value;},cancelScheduledValues(){},setValueAtTime(value){this.value=value;},linearRampToValueAtTime(value){this.value=value;}});
function node(type){const n={type,outputs:[],connect(to){this.outputs.push(to);},disconnect(){},gain:param(),frequency:param(),pan:param(),Q:param(),playbackRate:param(),start(){},stop(){}};nodes.push(n);return n;}
class AudioContext {
  state='running';currentTime=0;destination=node('destination');
  createGain(){return node('gain');}createBiquadFilter(){return node('filter');}createStereoPanner(){return node('pan');}createBufferSource(){return node('source');}
  async resume(){} async close(){} async decodeAudioData(){return {duration:30};}
}
const context=vm.createContext({settings:{music:100,effects:100},window:{AudioContext},fetch:async()=>({ok:true,arrayBuffer:async()=>new ArrayBuffer(1)}),setTimeout:fn=>fn()});
const audio=vm.runInContext(code.slice(begin,end)+';createMusic()',context);
await audio.start();
const master=nodes.find(n=>n.type==='gain'),filter=nodes.find(n=>n.type==='lowpass'),panner=nodes.find(n=>n.type==='pan');
const musicGain=nodes.find(n=>n.outputs.includes(filter));
const effects=audio.worldAudio();for(let i=0;i<30;i++)await Promise.resolve();
effects.spatial({gain:.15,cutoff:750,pan:-.4});
assert.equal(musicGain.gain.value,.15);assert.equal(filter.frequency.value,750);assert.equal(panner.pan.value,-.4);
assert.equal(master.gain.value,.4,'world attenuation preserves common volume');
assert.ok(nodes.filter(n=>n.type==='source').slice(0,2).every(n=>n.outputs[0].outputs[0]===musicGain),'theme sources use spatial bus');
effects.jump(false);
const effectBus=nodes.at(-1).outputs[0],musicBus=panner.outputs[0];
assert.equal(effectBus.outputs[0],master,'effects connect to master');
assert.equal(musicBus.outputs[0],master,'music connects to master');
audio.setLevel('music',25);audio.setLevel('effects',70);
assert.equal(musicBus.gain.value,.25,'music level is independent');
assert.equal(effectBus.gain.value,.7,'effects level is independent');
effects.playing(false);assert.equal(musicGain.gain.value,0,'switch stops only record music');
effects.spatial({gain:.5,cutoff:3000,pan:.2});assert.equal(musicGain.gain.value,0,'walking outside does not restart record');
assert.equal(master.gain.value,.4,'effects retain common volume while record is off');
effects.playing(true);assert.equal(musicGain.gain.value,.5,'switch resumes at current spatial level');
// Changing a record clears both scheduled loops; effects keep their own bus.
const oldTheme=nodes.filter(n=>n.type==='source').slice(0,2),stopped=[];
for(const source of oldTheme)source.stop=()=>stopped.push(source);
const beforeSwap=nodes.length;
await effects.record('/game/dedzytwo-s1.mp3');
assert.ok(oldTheme.every(source=>stopped.includes(source)),'both previous theme sources stopped');
assert.ok(oldTheme.every(source=>source.onended===null),'old loops cannot reschedule');
const newTheme=nodes.slice(beforeSwap).filter(n=>n.type==='source');
assert.equal(newTheme.length,2,'new record schedules exactly two loops');
assert.ok(newTheme.every(n=>n.outputs[0].outputs[0]===musicGain),'new record retains spatial bus');
await effects.record(null);
assert.ok(newTheme.every(source=>source.onended===null),'eject clears active loops');
const beforeLobby=nodes.length;
await effects.record('/game/dedzytwo-s1.mp3',true);
const lobbySources=nodes.slice(beforeLobby).filter(n=>n.type==='source');
assert.equal(lobbySources.length,1,'lobby record schedules one playback');
lobbySources[0].onended();
assert.equal(nodes.slice(beforeLobby).filter(n=>n.type==='source').length,1,'lobby record does not repeat');
await effects.record(null);
let resolveFetch;
context.fetch=()=>new Promise(resolve=>{resolveFetch=resolve;});
const pending=effects.record('/slow-record.mp3'),beforeSlow=nodes.length;
await effects.record(null);
resolveFetch({ok:true,arrayBuffer:async()=>new ArrayBuffer(1)});
await pending;
assert.equal(nodes.length,beforeSlow,'late download cannot play after eject');
await effects.record('/game/nora-theme.mp3');
assert.equal(nodes.slice(beforeSlow).filter(n=>n.type==='source').length,2,'standard record can be reinserted from cache');
effects.stop();assert.equal(musicGain.gain.value,1,'editor restores full music');
audio.close();
const count=nodes.length;
await effects.record('/game/dedzytwo-s1.mp3');
assert.equal(nodes.length,count,'disposed world cannot start a new track');
console.log('NORA music: spatial bus, effects, volume, record swap/eject, stale downloads and cleanup passed.');
