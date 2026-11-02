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
const context=vm.createContext({window:{AudioContext},fetch:async()=>({ok:true,arrayBuffer:async()=>new ArrayBuffer(1)}),setTimeout:fn=>fn()});
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
assert.equal(nodes.at(-1).outputs[0],master,'footstep effect bypasses music lowpass and panning');
effects.stop();assert.equal(musicGain.gain.value,1,'editor restores full music');
audio.close();console.log('NORA music: spatial bus, lowpass, stereo, common volume and independent effects passed.');
