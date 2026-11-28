import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const script = readFileSync(new URL('../community_bot/web/profile-track.js', import.meta.url), 'utf8');
const cache = script.slice(script.indexOf('  const musicCache ='), script.indexOf('  // Analyse'));
const playback = script.slice(script.indexOf('  function waitMediaEvent('), script.indexOf('  function stop() {'));

function harness({progressive = false, failAppend = false} = {}) {
  const urls = new Map();
  let urlId = 0, plays = 0;
  const requests = [];
  class Media extends EventTarget {
    static isTypeSupported(mime) { return mime === 'audio/mpeg'; }
    readyState = 'closed';
    addSourceBuffer() {
      const buffer = new EventTarget();
      buffer.appendBuffer = () => {
        if (failAppend) throw Error('Unsupported bytes');
        queueMicrotask(() => buffer.dispatchEvent(new Event('updateend')));
      };
      return buffer;
    }
    endOfStream() { this.readyState = 'ended'; }
  }
  const context = vm.createContext({
    auth: 'session-1', active: null, Date, Blob, setTimeout, clearTimeout,
    window: progressive ? {MediaSource:Media} : {},
    URL: {
      createObjectURL(value) { const url = 'blob:' + (++urlId); urls.set(url,value); return url; },
      revokeObjectURL(url) { urls.delete(url); }
    },
    fetch: async (src, options) => {
      requests.push({src,options});
      return context.respond(src);
    },
    paint() {},
    async toggleActive(state) { plays++; state.wantsPlayback = true; state.audio.paused = false; }
  });
  vm.runInContext(cache + playback + '\nthis.load = loadTrack; this.remember = rememberTrack; this.cached = cachedTrack;', context);
  function state(src = '/api/profile/track?v=one') {
    const audio = new EventTarget();
    audio.paused = true;
    audio.currentTime = 0;
    audio.pause = () => { audio.paused = true; };
    Object.defineProperty(audio, 'src', {
      set(url) {
        const media = urls.get(url);
        if (media instanceof Media) {
          media.readyState = 'open';
          queueMicrotask(() => media.dispatchEvent(new Event('sourceopen')));
        }
      }
    });
    return context.active = {src, audio, loading:true, controller:new AbortController()};
  }
  return {context, state, requests, plays:() => plays};
}

test('session cache rechecks access and avoids another audio download', async () => {
  const h = harness();
  h.context.respond = src => src.endsWith('&check=1')
    ? new Response(null,{status:204})
    : new Response(new Blob(['first'],{type:'audio/mpeg'}));
  await h.context.load(h.state());
  await h.context.load(h.state());
  assert.equal(h.requests.length,2);
  assert.match(h.requests[1].src,/&check=1$/);
  assert.equal(h.plays(),2);
  h.context.respond = () => new Response(null,{status:404});
  await assert.rejects(h.context.load(h.state()));
  assert.equal(h.context.cached('/api/profile/track?v=one'),null);
});

test('bounded LRU and auth changes clear cached tracks', () => {
  const h = harness();
  for (let i=0;i<9;i++) h.context.remember('track'+i,new Blob(['x']));
  assert.equal(h.context.cached('track0'),null);
  assert.equal(h.context.cached('track8').size,1);
  h.context.auth = 'session-2';
  assert.equal(h.context.cached('track8'),null);
});

test('progressive MP3 starts before response completes and uses same bytes for analysis', async () => {
  const h = harness({progressive:true});
  let controller;
  const stream = new ReadableStream({start(c){controller=c;c.enqueue(new Uint8Array([1,2]));}});
  h.context.respond = () => new Response(stream,{headers:{'Content-Type':'audio/mpeg'}});
  const state = h.state();
  const loading = h.context.load(state);
  for (let i=0;i<30 && h.plays()===0;i++) await new Promise(r=>setTimeout(r,5));
  assert.equal(h.plays(),1);
  assert.equal(state.loading,false);
  assert.equal(state.blob,undefined);
  controller.enqueue(new Uint8Array([3,4])); controller.close();
  await loading;
  assert.equal(state.blob.size,4);
  assert.equal(h.requests.length,1);
});

test('append failure falls back to complete blob without a second request', async () => {
  const h = harness({progressive:true,failAppend:true});
  h.context.respond = () => new Response(new Uint8Array([1,2,3]),{headers:{'Content-Type':'audio/mpeg'}});
  const state = h.state();
  await h.context.load(state);
  assert.equal(state.blob.size,3);
  assert.equal(state.loading,false);
  assert.equal(h.requests.length,1);
  assert.equal(h.plays(),1);
});

test('music mini player moves into modal, preserves scrolling and returns the same element', () => {
  const code = script.slice(script.indexOf('  function syncMiniHost()'),script.indexOf('  function paintMini()'));
  const classes = new Set(), panel = {focus() {}};
  const content = {scrollTop:125,replaceChildren(node){assert.equal(node,panel); dialog.library=panel;dialog.full=null;}};
  const mini = {parentElement:null, hidden:true,animate() {}};
  const home = {insertBefore(node){node.parentElement=this;}};
  mini.parentElement=home;
  const dialog = {open:true,library:panel,full:null,scrollTop:125,append(node){node.parentElement=this;},
    querySelector(s){return s==='#music-library-profile'?this.library:this.full;},
    classList:{contains(v){return classes.has(v);},toggle(v,on){if(on) classes.add(v);else classes.delete(v);}}};
  const context = vm.createContext({mini,miniHome:home,miniNext:null,miniMotion:{matches:true},
    $:s=>s==='#sheet'?dialog:content,active:{},playerReturn:null,libraryReturn:null,window:{},paint() {}});
  vm.runInContext(code+'\nthis.sync=syncMiniHost;this.closeFull=closeNowPlaying;',context);
  assert.equal(context.sync(),true);
  assert.equal(mini.parentElement,dialog);
  assert.equal(mini.hidden,false);
  assert.equal(content.scrollTop,125);
  context.playerReturn={panel,libraryReturn:7,scrollTop:88};
  dialog.library=null;dialog.full={};
  assert.equal(context.sync(),false);
  assert.equal(mini.parentElement,dialog); // preserve the touch target during the swipe
  assert.equal(context.closeFull(),true);
  assert.equal(dialog.library,panel);
  assert.equal(content.scrollTop,88);
  assert.equal(context.libraryReturn,7);
  assert.equal(mini.parentElement,dialog);
  dialog.open=false;
  context.sync();
  assert.equal(mini.parentElement,home);
});

test('music mini is a viewport overlay and modal gestures do not depend on main nav', () => {
  const css = readFileSync(new URL('../community_bot/web/style.css', import.meta.url), 'utf8');
  const app = readFileSync(new URL('../community_bot/web/app.js', import.meta.url), 'utf8');
  const rule = css.match(/#sheet\[open\]\.music-mini-docked > #nora-mini-player:not\(\[hidden\]\) \{([^}]+)\}/)?.[1];
  assert.ok(rule);
  assert.match(rule, /position:absolute/);
  assert.match(rule, /bottom:calc\(/);
  assert.match(rule, /z-index:20/);
  assert.match(rule, /touch-action:none/);
  const ready = app.slice(app.indexOf('  const miniReady ='), app.indexOf('  const pageReady ='));
  const player = {open:true,classList:{contains:()=>true}};
  const mini = {hidden:false,parentElement:player};
  const context = vm.createContext({player,mini,blocked:()=>true,document:{querySelector:()=>player}});
  vm.runInContext(ready + '\nthis.ready=miniReady;',context);
  assert.equal(context.ready(),true);
  mini.hidden=true;
  assert.equal(context.ready(),false);
  mini.hidden=false; player.open=false;
  assert.equal(context.ready(),false);
});
