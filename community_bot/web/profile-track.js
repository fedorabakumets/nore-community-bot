'use strict';

// Pattern Waves (Silk/dot preset), adapted from React Bits to native WebGL2.
// https://github.com/DavidHDev/react-bits
/*
MIT + Commons Clause License Condition v1.0

Copyright (c) 2026 David Haz

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, and distribute the Software **as part of an application, website, or product**, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

## Commons Clause Restriction

You may use this Software, including for any commercial purpose, **so long as you do not sell, sublicense, or redistribute the components themselves-whether alone, in a bundle, or as a ported version.**

The same restriction covers the React Bits tools (Background Studio, Texture Lab, Shape Magic, Center Stage, Sound Lab and any tools added later) and the sounds in the sound library. **You may not sell, sublicense, or redistribute the tools or the sounds themselves, or offer the tools or a substantially similar copy of them as a hosted service-whether alone, in a bundle, or as a ported version.**

What you make with the tools is yours to use. You can use exported code, images, videos, and audio files in any personal or commercial application, website, or product, including paid ones. **You may not sell or redistribute the exports on their own, either individually or as the product itself, such as a sound, texture, background, or template pack.**

## No Warranty

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

*/
const NoraProfileWaves = (() => {
  const vertex = "#version 300 es\nin vec2 position;\nvoid main() {\n  gl_Position = vec4(position, 0.0, 1.0);\n}\n";
  const field = "#version 300 es\nprecision highp float;\nprecision highp int;\nuniform vec2 uSize;\nuniform float uDpr;\nuniform vec2 uOrigin;\nuniform vec2 uPitch;\nuniform int uWave;\nuniform float uTime;\nuniform float uUnit;\nuniform vec2 uHeading;\nuniform float uAmp;\nuniform float uDepth;\nuniform vec3 uLight;\nuniform float uShine;\nuniform float uContrast;\nuniform float uInk;\nuniform float uOpacity;\nuniform int uFade;\nuniform float uFadeSize;\nuniform float uAppear;\nuniform sampler2D tRipple;\nuniform float uRipple;\nuniform vec4 uTap0;\nuniform vec4 uTap1;\nuniform vec4 uTap2;\nout vec4 fragColor;\n\nconst float FOLDS = 5.5;\n\nuvec3 scramble(uvec3 v) {\n  v = v * 1664525u + 1013904223u;\n  v.x += v.y * v.z;\n  v.y += v.z * v.x;\n  v.z += v.x * v.y;\n  v ^= v >> 16u;\n  v.x += v.y * v.z;\n  v.y += v.z * v.x;\n  v.z += v.x * v.y;\n  return v;\n}\n\nvec3 lattice(vec3 corner) {\n  uvec3 h = scramble(uvec3(ivec3(corner) + 4096));\n  return vec3(h & 65535u) / 32767.5 - 1.0;\n}\n\nfloat gradientNoise(vec3 p) {\n  vec3 i = floor(p);\n  vec3 f = p - i;\n  vec3 u = f * f * f * (f * (f * 6.0 - 15.0) + 10.0);\n  float n000 = dot(lattice(i), f);\n  float n100 = dot(lattice(i + vec3(1.0, 0.0, 0.0)), f - vec3(1.0, 0.0, 0.0));\n  float n010 = dot(lattice(i + vec3(0.0, 1.0, 0.0)), f - vec3(0.0, 1.0, 0.0));\n  float n110 = dot(lattice(i + vec3(1.0, 1.0, 0.0)), f - vec3(1.0, 1.0, 0.0));\n  float n001 = dot(lattice(i + vec3(0.0, 0.0, 1.0)), f - vec3(0.0, 0.0, 1.0));\n  float n101 = dot(lattice(i + vec3(1.0, 0.0, 1.0)), f - vec3(1.0, 0.0, 1.0));\n  float n011 = dot(lattice(i + vec3(0.0, 1.0, 1.0)), f - vec3(0.0, 1.0, 1.0));\n  float n111 = dot(lattice(i + vec3(1.0, 1.0, 1.0)), f - vec3(1.0, 1.0, 1.0));\n  return mix(\n    mix(mix(n000, n100, u.x), mix(n010, n110, u.x), u.y),\n    mix(mix(n001, n101, u.x), mix(n011, n111, u.x), u.y),\n    u.z\n  );\n}\n\nvec2 turn(vec2 v, float angle) {\n  float c = cos(angle);\n  float s = sin(angle);\n  return vec2(c * v.x - s * v.y, s * v.x + c * v.y);\n}\n\nfloat surface(vec2 p, float t) {\n  if (uWave == 0) {\n    vec2 side = vec2(-uHeading.y, uHeading.x);\n    float u = dot(p, uHeading);\n    float v = dot(p, side);\n    float bend = gradientNoise(vec3(v * 0.85, u * 0.3, t * 0.05)) * 1.7 + 0.4 * sin(v * 1.6 + t * 0.2);\n    float phase = u * FOLDS + bend - t * 0.45;\n    float swell = 0.6 + 0.4 * gradientNoise(vec3(u * 0.55 + 3.0, v * 0.45, t * 0.04));\n    float fold = sin(phase) + 0.32 * sin(2.0 * phase + 1.3);\n    float ripple = 0.16 * sin(u * FOLDS * 2.5 + bend * 1.9 - t * 0.9 + 2.1);\n    return (fold + ripple) * swell;\n  }\n  if (uWave == 1) {\n    float bend = gradientNoise(vec3(p * 0.6, t * 0.05)) * 0.6;\n    float phase = dot(p, uHeading) * 15.0 + bend * 2.2 - t * 1.4;\n    float swell = sin(phase) + 0.3 * sin(2.0 * phase - 0.8);\n    float roll = 0.75 + 0.25 * gradientNoise(vec3(p * 0.9 + 11.0, t * 0.05));\n    return 0.8 * swell * roll;\n  }\n  float r = length(p + uHeading * 1.2);\n  float bend = gradientNoise(vec3(p * 1.2, t * 0.05)) * 0.1;\n  return sin((r + bend) * 9.0 - t * 1.8) * (0.45 + 0.55 * exp(-(r - 0.6) * 0.8));\n}\n\nfloat touchWave(vec2 css, vec4 tap) {\n  if (tap.w <= 0.0 || tap.z > 1.6) return 0.0;\n  float distanceToTap = length(css - tap.xy);\n  float front = distanceToTap - tap.z * 270.0;\n  float envelope = exp(-front * front / 5200.0) * exp(-tap.z * 2.7);\n  return sin(front * 0.065) * envelope * tap.w * 0.30;\n}\nfloat heightAt(vec2 css) {\n  float h = surface((css - 0.5 * uSize) / uUnit, uTime) * uAmp;\n  if (uRipple > 0.0) h += texture(tRipple, css / uSize).r * uRipple;\n  h += touchWave(css,uTap0) + touchWave(css,uTap1) + touchWave(css,uTap2);\n  return h;\n}\n\nvoid main() {\n  vec2 cell = floor(gl_FragCoord.xy);\n  vec2 center = uOrigin + (cell + 0.5) * uPitch;\n  vec2 css = center / uDpr;\n  vec2 uv = css / uSize;\n  float e = max(uPitch.y / uDpr, 4.0);\n  float h = heightAt(css);\n  float hx = (heightAt(css + vec2(e, 0.0)) - heightAt(css - vec2(e, 0.0))) / (2.0 * e);\n  float hy = (heightAt(css + vec2(0.0, e)) - heightAt(css - vec2(0.0, e))) / (2.0 * e);\n  vec2 grad = vec2(hx, hy) * uUnit * uDepth * 0.4;\n  vec3 n = normalize(vec3(-grad, 1.0));\n\n  float diffuse = clamp(dot(n, uLight), 0.0, 1.0);\n  vec3 halfway = normalize(uLight + vec3(0.0, 0.0, 1.0));\n  float spec = pow(clamp(dot(n, halfway), 0.0, 1.0), 160.0) * uShine * 1.15;\n  float hollow = 0.7 + 0.3 * clamp(h * 0.5 + 0.5, 0.0, 1.0);\n  float tone = clamp(diffuse * hollow * 0.78 + spec, 0.0, 1.0);\n  tone = clamp((tone - 0.42) * uContrast + 0.42, 0.0, 1.0);\n\n  float level = uInk > 0.5 ? pow(clamp(1.0 - tone / 0.46, 0.0, 1.0), 2.4) * 0.72 : pow(tone, 2.2);\n  float emphasis = uInk > 0.5 ? smoothstep(0.55, 0.95, level) : clamp(spec * 1.6, 0.0, 1.0);\n\n  float fade = 1.0;\n  vec2 c = uv * 2.0 - 1.0;\n  if (uFade == 1) {\n    fade = 1.0 - smoothstep(1.0 - uFadeSize, 1.18, length(c));\n  } else if (uFade == 2) {\n    fade = mix(0.05, 1.0, smoothstep(0.08, 0.08 + uFadeSize, length(c * vec2(1.0, 1.35))));\n  } else if (uFade == 3) {\n    fade = smoothstep(0.0, uFadeSize, uv.y);\n  } else if (uFade == 4) {\n    fade = smoothstep(0.0, uFadeSize, 1.0 - uv.y);\n  }\n\n  float reach = length(css - 0.5 * uSize) / max(0.5 * length(uSize), 1.0);\n  float appear = smoothstep(reach - 0.05, reach + 0.3, uAppear * 1.35);\n\n  float alpha = uOpacity * fade * appear * (0.22 + 0.78 * level);\n  float lift = clamp(h * uDepth * 0.42, -0.48, 0.48);\n  fragColor = vec4(level, alpha, emphasis, lift + 0.5);\n}\n";
  const marks = "#version 300 es\nprecision highp float;\nprecision highp int;\nuniform sampler2D tField;\nuniform sampler2D tAtlas;\nuniform vec2 uOrigin;\nuniform vec2 uPitch;\nuniform vec2 uGrid;\nuniform int uPattern;\nuniform float uMarkSize;\nuniform float uStroke;\nuniform vec3 uColor;\nuniform vec3 uAccent;\nuniform vec4 uBackground;\nuniform vec3 uAtlas;\nout vec4 fragColor;\n\nfloat box(vec2 p, vec2 b, float r) {\n  vec2 q = abs(p) - b + r;\n  return length(max(q, 0.0)) + min(max(q.x, q.y), 0.0) - r;\n}\n\nfloat coverage(vec2 local, float level) {\n  float span = uPitch.y * uMarkSize;\n  float area = max(sqrt(level), 0.14);\n  if (uPattern == 0) {\n    return clamp(0.5 - (length(local) - 0.5 * span * area), 0.0, 1.0);\n  }\n  if (uPattern == 1) {\n    float extent = 0.5 * span * area;\n    return clamp(0.5 - box(local, vec2(extent), extent * 0.3), 0.0, 1.0);\n  }\n  if (uPattern == 2) {\n    float arm = 0.5 * span * mix(0.3, 1.0, level);\n    float width = 0.5 * uStroke;\n    return clamp(0.5 - min(box(local, vec2(arm, width), width), box(local, vec2(width, arm), width)), 0.0, 1.0);\n  }\n  if (uAtlas.z < 1.0) return 0.0;\n  vec2 g = local / span + 0.5;\n  if (g.x < 0.0 || g.y < 0.0 || g.x > 1.0 || g.y > 1.0) return 0.0;\n  float index = min(floor(level * uAtlas.z), uAtlas.z - 1.0);\n  vec2 tile = vec2(mod(index, uAtlas.x), floor(index / uAtlas.x));\n  vec2 atlasUv = (tile + vec2(g.x, 1.0 - g.y)) / uAtlas.xy;\n  vec2 texel = 1.0 / (span * uAtlas.xy);\n  return textureGrad(tAtlas, atlasUv, vec2(texel.x, 0.0), vec2(0.0, texel.y)).a;\n}\n\nvec4 lineInk(vec2 rel) {\n  float fx = rel.x / uPitch.x - 0.5;\n  float c0 = clamp(floor(fx), 0.0, uGrid.x - 1.0);\n  float c1 = min(c0 + 1.0, uGrid.x - 1.0);\n  float t = clamp(fx - c0, 0.0, 1.0);\n  float row = floor(rel.y / uPitch.y);\n  vec4 ink = vec4(0.0);\n  for (int k = -1; k <= 1; k++) {\n    float cy = row + float(k);\n    if (cy < 0.0 || cy >= uGrid.y) continue;\n    vec4 a = texelFetch(tField, ivec2(int(c0), int(cy)), 0);\n    vec4 b = texelFetch(tField, ivec2(int(c1), int(cy)), 0);\n    vec4 f = mix(a, b, t);\n    if (f.g < 0.002) continue;\n    float y = (cy + 0.5 + f.a - 0.5) * uPitch.y;\n    float slope = (b.a - a.a) * uPitch.y / uPitch.x;\n    float thickness = max(uStroke, uPitch.y * uMarkSize * f.r);\n    float d = abs(rel.y - y) / sqrt(1.0 + slope * slope) - 0.5 * thickness;\n    float alpha = clamp(0.5 - d, 0.0, 1.0) * f.g;\n    if (alpha > ink.a) ink = vec4(mix(uColor, uAccent, f.b) * alpha, alpha);\n  }\n  return ink;\n}\n\nvoid main() {\n  vec2 rel = gl_FragCoord.xy - uOrigin;\n  vec4 background = vec4(uBackground.rgb * uBackground.a, uBackground.a);\n  vec4 ink = vec4(0.0);\n  if (uPattern == 3) {\n    ink = lineInk(rel);\n  } else {\n    float cx = floor(rel.x / uPitch.x);\n    float row = floor(rel.y / uPitch.y);\n    if (cx >= 0.0 && cx < uGrid.x) {\n      for (int k = -1; k <= 1; k++) {\n        float cy = row + float(k);\n        if (cy < 0.0 || cy >= uGrid.y) continue;\n        vec4 f = texelFetch(tField, ivec2(int(cx), int(cy)), 0);\n        if (f.g < 0.002) continue;\n        vec2 center = (vec2(cx, cy) + 0.5) * uPitch + vec2(0.0, (f.a - 0.5) * uPitch.y);\n        float alpha = coverage(rel - center, f.r) * f.g;\n        if (alpha > ink.a) ink = vec4(mix(uColor, uAccent, f.b) * alpha, alpha);\n      }\n    }\n  }\n  fragColor = ink + background * (1.0 - ink.a);\n}\n";
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  let scene = null;
  function renderer(canvas) {
    const gl = canvas.getContext('webgl2', {alpha:true,premultipliedAlpha:true,antialias:false,depth:false,stencil:false});
    if (!gl) return null;
    let programs=[], shaders=[], textures=[], framebuffer=null, buffer=null;
    function destroy() {
      for(const p of programs) gl.deleteProgram(p);
      for(const s of shaders) gl.deleteShader(s);
      for(const t of textures) gl.deleteTexture(t);
      if(framebuffer)gl.deleteFramebuffer(framebuffer);
      if(buffer)gl.deleteBuffer(buffer);
    }
    try {
      function compile(kind,code) {
        const s=gl.createShader(kind);shaders.push(s);
        gl.shaderSource(s,code);gl.compileShader(s);
        if(!gl.getShaderParameter(s,gl.COMPILE_STATUS))throw Error(gl.getShaderInfoLog(s));
        return s;
      }
      const vs=compile(gl.VERTEX_SHADER,vertex);
      function program(code) {
        const p=gl.createProgram();programs.push(p);
        gl.attachShader(p,vs);gl.attachShader(p,compile(gl.FRAGMENT_SHADER,code));
        gl.bindAttribLocation(p,0,'position');gl.linkProgram(p);
        if(!gl.getProgramParameter(p,gl.LINK_STATUS))throw Error(gl.getProgramInfoLog(p));
        return p;
      }
      const fp=program(field),mp=program(marks);
      buffer=gl.createBuffer();gl.bindBuffer(gl.ARRAY_BUFFER,buffer);
      gl.bufferData(gl.ARRAY_BUFFER,new Float32Array([-1,-1,3,-1,-1,3]),gl.STATIC_DRAW);
      gl.enableVertexAttribArray(0);gl.vertexAttribPointer(0,2,gl.FLOAT,false,0,0);
      function texture(unit) {
        const t=gl.createTexture();textures.push(t);gl.activeTexture(gl.TEXTURE0+unit);
        gl.bindTexture(gl.TEXTURE_2D,t);
        for(const key of [gl.TEXTURE_MIN_FILTER,gl.TEXTURE_MAG_FILTER])gl.texParameteri(gl.TEXTURE_2D,key,gl.NEAREST);
        for(const key of [gl.TEXTURE_WRAP_S,gl.TEXTURE_WRAP_T])gl.texParameteri(gl.TEXTURE_2D,key,gl.CLAMP_TO_EDGE);
        gl.texImage2D(gl.TEXTURE_2D,0,gl.RGBA8,1,1,0,gl.RGBA,gl.UNSIGNED_BYTE,new Uint8Array(4));
        return t;
      }
      const grid=texture(0);texture(1);
      framebuffer=gl.createFramebuffer();gl.bindFramebuffer(gl.FRAMEBUFFER,framebuffer);
      gl.framebufferTexture2D(gl.FRAMEBUFFER,gl.COLOR_ATTACHMENT0,gl.TEXTURE_2D,grid,0);
      gl.bindFramebuffer(gl.FRAMEBUFFER,null);
      const locations=new Map();
      function uniforms(p,values) {
        gl.useProgram(p);
        if(!locations.has(p))locations.set(p,new Map());
        const cache=locations.get(p);
        for(const [key,value] of Object.entries(values)){
          if(!cache.has(key))cache.set(key,gl.getUniformLocation(p,key));
          const loc=cache.get(key);if(loc===null)continue;
          if(Array.isArray(value))gl['uniform'+value.length+'fv'](loc,value);
          else if(['uWave','uFade','uPattern','tRipple','tField','tAtlas'].includes(key))gl.uniform1i(loc,value);
          else gl.uniform1f(loc,value);
        }
      }
      let oldCols=0,oldRows=0;
      return {
        draw(time, energy=0, taps=[]) {
          const w=canvas.clientWidth,h=canvas.clientHeight;if(!w||!h||gl.isContextLost())return;
          const dpr=Math.min(window.devicePixelRatio||1,1.5,Math.sqrt(1000000/(w*h)));
          const cw=Math.max(1,Math.round(w*dpr)),ch=Math.max(1,Math.round(h*dpr));
          if(canvas.width!==cw||canvas.height!==ch){canvas.width=cw;canvas.height=ch;}
          const ratio=cw/w,pitch=Math.max(4,Math.round(9*ratio)),cols=Math.ceil(cw/pitch)+1,rows=Math.ceil(ch/pitch)+2;
          const origin=[Math.floor((cw-cols*pitch)/2),Math.floor((ch-rows*pitch)/2)];
          gl.activeTexture(gl.TEXTURE0);gl.bindTexture(gl.TEXTURE_2D,grid);
          if(cols!==oldCols||rows!==oldRows){
            gl.texImage2D(gl.TEXTURE_2D,0,gl.RGBA8,cols,rows,0,gl.RGBA,gl.UNSIGNED_BYTE,null);
            oldCols=cols;oldRows=rows;
          }
          const angle=20*Math.PI/180;
          const tapAt=i=>taps[i]?[taps[i].x,h-taps[i].y,taps[i].age,taps[i].strength]:[0,0,0,0];
          gl.bindFramebuffer(gl.FRAMEBUFFER,framebuffer);gl.viewport(0,0,cols,rows);
          uniforms(fp,{uSize:[w,h],uDpr:ratio,uOrigin:origin,uPitch:[pitch,pitch],uWave:0,uTime:time*.35,uUnit:520,uHeading:[Math.cos(angle),Math.sin(angle)],uAmp:1+energy*.13,uDepth:.95+energy*.09,uLight:[-Math.cos(angle)*.78,-Math.sin(angle)*.78,.62],uShine:.8+energy*.28,uContrast:1.2,uInk:0,uOpacity:.9,uFade:0,uFadeSize:.5,uAppear:1,tRipple:1,uRipple:0,uTap0:tapAt(0),uTap1:tapAt(1),uTap2:tapAt(2)});
          gl.drawArrays(gl.TRIANGLES,0,3);
          gl.bindFramebuffer(gl.FRAMEBUFFER,null);gl.viewport(0,0,cw,ch);
          uniforms(mp,{tField:0,tAtlas:1,uOrigin:origin,uPitch:[pitch,pitch],uGrid:[cols,rows],uPattern:0,uMarkSize:.95,uStroke:1,uColor:[.57,.72,.86],uAccent:[.84+energy*.07,.91+energy*.04,1],uBackground:[0,0,0,0],uAtlas:[1,1,0]});
          gl.drawArrays(gl.TRIANGLES,0,3);
        },
        destroy
      };
    } catch(error) {destroy();return null;}
  }
  // Keep the WebView's native canvas (including iOS rubber-band areas) in sync.
  function paintMusicShell(enabled) {
    document.documentElement.classList.toggle('nora-music-shell',enabled);
    const webApp=window.Telegram?.WebApp;
    const color=enabled?'#354451':(getComputedStyle(document.documentElement).getPropertyValue('--poster-bg').trim()||'#111013');
    if(!webApp)return;
    for(const [method,version] of [['setBackgroundColor','6.1'],['setHeaderColor','6.9'],['setBottomBarColor','7.10']]){
      try{if(webApp.isVersionAtLeast?.(version))webApp[method]?.(color);}catch{}
    }
  }
  function stopScene(s,immediate=false) {
    if(!s)return;
    s.host.classList.remove('nora-profile-music');
    s.element?.style.removeProperty('--music-energy');
    s.energy=0;s.taps=[];
    if(scene===s)paintMusicShell(false);
    s.running=false;cancelAnimationFrame(s.raf);s.raf=0;
    s.layer.classList.remove('is-playing');
    clearTimeout(s.removeTimer);
    const dispose=()=>{
      s.renderer?.destroy();s.layer.remove();
      if(scene===s)scene=null;
    };
    if(immediate)dispose();else s.removeTimer=setTimeout(dispose,520);
  }
  function tick(s,now) {
    s.raf=0;
    if(!s.running||document.hidden)return;
    if(!s.last||now-s.last>=32){
      const dt=s.last?Math.min(.1,(now-s.last)/1000):.033;
      s.last=now;
      const quiet=reduced.matches;
      const target=quiet?0:(s.track?.envelope?.[Math.floor((s.track.audio.currentTime||0)*20)]||0);
      // Smooth the measured bass envelope; do not flash on individual samples.
      s.energy+=(target-s.energy)*(1-Math.exp(-dt/(target>s.energy?.085:.24)));
      if(!quiet)s.time+=dt*(1+s.energy*.42);
      s.taps=s.taps.filter(t=>s.time-t.time<1.6);
      s.renderer?.draw(s.time,quiet?0:s.energy,quiet?[]:s.taps.map(t=>({...t,age:s.time-t.time})));
      s.element?.style.setProperty('--music-energy',s.energy.toFixed(3));
    }
    if(!reduced.matches)s.raf=requestAnimationFrame(t=>tick(s,t));
  }
  function wake(s) {
    if(!s||!s.running||document.hidden||s.raf)return;
    s.last=0;s.raf=requestAnimationFrame(t=>tick(s,t));
  }
  function sync(element,playing,track=null) {
    const person=element?.closest('#person-profile');
    const own=element?.closest('#app[data-screen="lk"] .lk-screen');
    const host=person&&person.closest('dialog')?.open?person.closest('dialog'):own?document.body:null;
    if(!playing||!host||!element.isConnected){
      if(scene?.running)stopScene(scene,!host||!element?.isConnected);
      return;
    }
    if(scene?.host!==host&&scene)stopScene(scene,true);
    if(!scene){
      const layer=document.createElement('div');layer.className='nora-profile-waves';layer.setAttribute('aria-hidden','true');
      const canvas=document.createElement('canvas');layer.append(canvas);
      host.prepend(layer);
      let engine=null;
      try{engine=renderer(canvas);}catch{}
      if(!engine)canvas.hidden=true;
      scene={host,layer,renderer:engine,raf:0,last:0,time:0,running:false,energy:0,taps:[],element:null,track:null};
      canvas.addEventListener('webglcontextlost',event=>{event.preventDefault();if(scene?.layer===layer){cancelAnimationFrame(scene.raf);scene.raf=0;scene.renderer=null;canvas.hidden=true;}});
      canvas.addEventListener('webglcontextrestored',()=>{if(scene?.layer===layer){scene.renderer=renderer(canvas);canvas.hidden=!scene.renderer;wake(scene);}});
    }
    if(scene.element!==element)scene.element?.style.removeProperty('--music-energy');
    scene.element=element;scene.track=track;
    if(scene.running)return;
    clearTimeout(scene.removeTimer);scene.running=true;host.classList.add('nora-profile-music');
    paintMusicShell(true);
    const s=scene;requestAnimationFrame(()=>{if(s.running)s.layer.classList.add('is-playing');});
    wake(s);
  }
  // Passive pointer effects only: no interference with scrolling, links or sliders.
  function ripple(event,strength) {
    const s=scene;
    if(!s?.running||!s.renderer||document.hidden||reduced.matches)return;
    if(event.target.closest('input,textarea,select,#nav,#scroll-jump'))return;
    if(s.host===document.body){
      if(document.querySelector('dialog[open]')||!event.target.closest('#app[data-screen="lk"]'))return;
    }else if(!event.target.closest('#person-profile'))return;
    const rect=s.layer.getBoundingClientRect(),x=event.clientX-rect.left,y=event.clientY-rect.top;
    if(x<0||y<0||x>rect.width||y>rect.height)return;
    s.taps=[{x,y,time:s.time,strength},...s.taps].slice(0,3);
  }
  document.addEventListener('pointerdown',event=>ripple(event,1),{passive:true});
  let lastHover=0,lastX=0,lastY=0;
  document.addEventListener('pointermove',event=>{
    if(event.pointerType!=='mouse'||event.timeStamp-lastHover<170||Math.hypot(event.clientX-lastX,event.clientY-lastY)<36)return;
    lastHover=event.timeStamp;lastX=event.clientX;lastY=event.clientY;
    ripple(event,.4);
  },{passive:true});
  document.addEventListener('visibilitychange',()=>{
    if(!scene)return;
    if(document.hidden){cancelAnimationFrame(scene.raf);scene.raf=0;}else wake(scene);
  });
  reduced.addEventListener('change',()=>{if(scene){cancelAnimationFrame(scene.raf);scene.raf=0;wake(scene);}});
  window.addEventListener('resize',()=>wake(scene),{passive:true});
  window.addEventListener('pagehide',()=>stopScene(scene,true));
  return {sync};
})();

window.NoraProfileTrack = (() => {
  let active = null, libraryReturn = null;

  // Analyse the already downloaded track separately. Never route playback through
  // AudioContext: a suspended Web Audio graph must not mute iOS playback.
  async function prepareMusicEnvelope(state) {
    if(state.analysisStarted||!state.blob||!state.element.closest('#app[data-screen="lk"] .lk-screen,#person-profile')||
       matchMedia('(prefers-reduced-motion: reduce)').matches)return;
    const duration=state.audio.duration;
    if(!Number.isFinite(duration)||duration<=0)return;
    state.analysisStarted=true;
    const blob=state.blob;state.blob=null;
    const Offline=window.OfflineAudioContext||window.webkitOfflineAudioContext;
    if(!Offline||duration>600||blob.size>16*1024*1024)return;
    try{
      const decoder=new Offline(1,1,22050);
      const encoded=await blob.arrayBuffer();
      if(active!==state)return;
      const decoded=await decoder.decodeAudioData(encoded);
      if(active!==state||decoded.duration>600)return;
      const samples=decoded.getChannelData(0);
      const second=decoded.numberOfChannels>1?decoded.getChannelData(1):null;
      const stride=Math.max(1,Math.floor(decoded.sampleRate/5500));
      const rate=decoded.sampleRate/stride, alpha=1-Math.exp(-2*Math.PI*145/rate);
      const count=Math.ceil(decoded.duration*20),levels=new Float32Array(count);
      let low=0,dc=0,baseline=.012,peak=.035;
      for(let frame=0;frame<count;frame++){
        const start=Math.floor(frame*decoded.sampleRate/20);
        const end=Math.min(samples.length,Math.floor((frame+1)*decoded.sampleRate/20));
        let bass=0,wide=0,n=0;
        for(let i=start;i<end;i+=stride){
          const a=samples[i],b=second?second[i]:a;
          const value=Math.abs(a)>=Math.abs(b)?a:b;
          dc+=(value-dc)*.003;low+=(value-dc-low)*alpha;
          bass+=low*low;wide+=value*value;n++;
        }
        const level=.78*Math.sqrt(bass/Math.max(1,n))+.22*Math.sqrt(wide/Math.max(1,n));
        baseline+=(level-baseline)*.045;
        peak=Math.max(level,peak*.994,.035);
        const intensity=Math.min(1,level/(peak+.025));
        const accent=Math.min(1,Math.max(0,(level-baseline)/(baseline+.035)));
        levels[frame]=Math.min(1,.55*intensity+.45*accent);
        if(frame%300===299){
          await new Promise(resolve=>setTimeout(resolve,0));
          if(active!==state)return;
        }
      }
      if(active===state)state.envelope=levels;
    }catch{
      // Unsupported codecs, memory limits or browsers keep the ordinary waves.
    }
  }

  function clock(seconds) {
    const total = Math.floor(Number(seconds) || 0);
    return Math.floor(total / 60) + ':' + String(total % 60).padStart(2, '0');
  }

  function html(track, endpoint, library = false, readonly = false) {
    if (!track) return '';
    const src = endpoint + '?v=' + encodeURIComponent(track.revision);
    const saved = library || Boolean(track.saved);
    const save = track.id && !readonly ? `<button type="button" class="profile-track-save" data-track-save data-track-id="${esc(track.id)}" data-save-path="${esc(library ? 'music-library' : endpoint.slice(5) + '/save')}" data-track-revision="${esc(track.revision)}" data-saved="${saved}" aria-pressed="${saved}" aria-label="${saved ? 'Удалить из моих треков' : 'Добавить в мои треки'}">${saved ? '✓' : '+'}</button>` : '';
    return `<section class="profile-track" data-track-src="${esc(src)}" aria-label="${library ? 'Сохранённый трек' : 'Трек профиля'}"><div class="profile-track-actions">
      <button type="button" class="profile-track-toggle" data-track-toggle aria-label="Включить трек: ${esc(track.title)}">
        <span class="profile-track-copy">
          <strong title="${esc(track.title)}">${esc(track.title)}</strong>
          <small>${library ? '' : '– '}${esc(track.artist || 'Неизвестен')}</small>
        </span>
      </button>${library ? `<span class="profile-library-duration">${clock(track.duration)}</span>` : ''}${save}</div>
      <div class="profile-track-timeline">
        <span data-track-time>0:00</span>
        <input type="range" min="0" max="1" step="0.001" value="0" data-track-seek aria-label="Позиция в треке" disabled>
        <span data-track-duration>${clock(track.duration)}</span>
      </div>
    </section>`;
  }

  function libraryButton(owner = '') {
    return `<button type="button" class="profile-library-open" data-music-library="${esc(owner)}">${owner ? 'Треки' : 'Мои треки'} <span aria-hidden="true">›</span></button>`;
  }

  function libraryScreen(title, subtitle, content) {
    return '<section id="music-library-profile" tabindex="-1" autofocus data-music-library-panel>' +
      '<header class="profile-library-header"><div class="profile-library-symbol" aria-hidden="true">' +
      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M3 14v-3a9 9 0 0 1 18 0v3M3 13h2a2 2 0 0 1 2 2v4a2 2 0 0 1-2 2H4a1 1 0 0 1-1-1v-7Zm18 0h-2a2 2 0 0 0-2 2v4a2 2 0 0 0 2 2h1a1 1 0 0 0 1-1v-7Z"/></svg></div>' +
      '<h2>' + esc(title) + '</h2><p data-library-count>' + esc(subtitle) + '</p></header>' +
      '<div class="profile-library-content">' + content + '</div></section>';
  }

  function libraryCount(count) {
    return number(count) + ' ' + plural(count, 'трек', 'трека', 'треков');
  }

  function libraryEmpty() {
    return '<div class="profile-library-empty"><strong>Пока нет треков</strong><p>Сохранённая музыка появится здесь.</p></div>';
  }

  function back() {
    const dialog = $('#sheet');
    if (!dialog.open || !$('#music-library-profile')) return false;
    const origin = libraryReturn;
    libraryReturn = null;
    if (origin) {
      void window.NoraPeople.visit(origin);
    } else {
      dialog.close();
    }
    return true;
  }

  async function showLibrary(owner = '') {
    const path = owner ? 'people/' + encodeURIComponent(owner) + '/music-library' : 'music-library';
    const title = owner ? 'Треки' : 'Мои треки';
    const person = $('#person-profile');
    libraryReturn = person ? Number(person.dataset.personId) : null;
    if (active) stop();
    sheet(libraryScreen(title, 'Загрузка…', '<div class="profile-library-empty" role="status">Загрузка…</div>'));
    const panel = $('#music-library-profile');
    panel.focus({preventScroll:true});
    $('#sheet').scrollTop = 0;
    try {
      const result = await api(path);
      if (!panel.isConnected || !$('#sheet').open) return;
      const visibility = owner ? '' : '<label class="profile-library-visibility"><span><strong>Публичная коллекция</strong><small>Другие участники смогут слушать твои треки</small></span><input type="checkbox" role="switch" data-library-visibility ' + (result.public ? 'checked' : '') + '></label>';
      panel.querySelector('[data-library-count]').textContent = libraryCount(result.tracks.length);
      panel.querySelector('.profile-library-content').innerHTML = (result.tracks.length
        ? '<div class="profile-library-list">' + result.tracks.map(track => html(track, '/api/' + path + '/' + track.id, true, Boolean(owner))).join('') + '</div>'
        : libraryEmpty()) + visibility;
    } catch (error) {
      if (panel.isConnected) {
        panel.querySelector('[data-library-count]').textContent = 'Коллекция недоступна';
        panel.querySelector('.profile-library-content').innerHTML = '<div class="profile-library-empty">' + esc(error.message) + '</div>';
      }
    }
  }

  document.addEventListener('close', event => {
    if (event.target === $('#sheet')) libraryReturn = null;
  }, true);

  document.addEventListener('cancel', event => {
    if (event.target === $('#sheet') && back()) event.preventDefault();
  }, true);

  document.addEventListener('change', async event => {
    const input = event.target;
    if (!input.matches('[data-library-visibility]')) return;
    const value = input.checked;
    input.disabled = true;
    try {
      await api('music-library/visibility', { public: value });
      toast(value ? 'Коллекция открыта' : 'Коллекция приватная');
    } catch (error) {
      input.checked = !value;
      toast(error.message);
    } finally {
      input.disabled = false;
    }
  });

  function paintSaved(button, saved) {
    button.dataset.saved = String(saved);
    button.setAttribute('aria-pressed', String(saved));
    button.setAttribute('aria-label', saved ? 'Удалить из моих треков' : 'Добавить в мои треки');
    button.textContent = saved ? '✓' : '+';
  }

  document.addEventListener('click', async event => {
    const open = event.target.closest('[data-music-library]');
    if (open) { await showLibrary(open.dataset.musicLibrary); return; }
    const button = event.target.closest('[data-track-save]');
    if (!button || button.disabled) return;
    const { trackId, savePath, trackRevision, saved } = button.dataset;
    button.disabled = true;
    try {
      const result = await api(savePath, savePath === 'music-library'
        ? { id: trackId } : { revision: trackRevision, saved: saved !== 'true' });
      for (const item of document.querySelectorAll('[data-track-save]')) {
        if (item.dataset.trackId === result.id) paintSaved(item, result.saved);
      }
      if (typeof data !== 'undefined' && data?.profile_track?.id === result.id) {
        data.profile_track.saved = result.saved;
      }
      if (savePath === 'music-library') {
        const row = button.closest('[data-track-src]');
        if (active?.element === row) stop();
        const panel = row.closest('[data-music-library-panel]');
        row.remove();
        if (panel) {
          const count = panel.querySelectorAll('[data-track-src]').length;
          panel.querySelector('[data-library-count]').textContent = libraryCount(count);
          if (!count) panel.querySelector('.profile-library-list')?.insertAdjacentHTML('afterend', libraryEmpty());
          if (!count) panel.querySelector('.profile-library-list')?.remove();
        }
      }
      toast(result.saved ? 'Добавлено в Мои треки' : 'Удалено из Моих треков');
    } catch (error) {
      toast(error.message);
    } finally {
      button.disabled = false;
    }
  });

  function paint(state) {
    const { audio, element, loading } = state;
    const playing = !audio.paused && !audio.ended;
    const duration = Number.isFinite(audio.duration) ? audio.duration : 0;
    const seek = element.querySelector('[data-track-seek]');
    const current = audio.currentTime || 0;
    seek.value = duration ? current / duration : 0;
    seek.disabled = !duration;
    seek.style.setProperty('--track-progress', (Number(seek.value) * 100) + '%');
    seek.setAttribute('aria-valuetext', clock(current));
    element.querySelector('[data-track-time]').textContent = clock(current);
    if (duration) element.querySelector('[data-track-duration]').textContent = clock(duration);
    element.dataset.ready = String(Boolean(duration && !loading));
    element.dataset.playing = String(playing);
    NoraProfileWaves.sync(element, playing && !loading,state);
    if(playing && !loading) void prepareMusicEnvelope(state);
    element.dataset.loading = String(loading);
    const play = element.querySelector('[data-track-toggle]');
    play.disabled = loading;
    play.setAttribute('aria-label', (loading ? 'Загружаем трек' : playing ? 'Поставить на паузу' : 'Включить трек') + ': ' + element.querySelector('.profile-track-copy strong').textContent);
  }

  function stop() {
    const state = active;
    if (!state) return;
    active = null;
    state.controller.abort();
    state.blob=null;state.envelope=null;
    state.audio.pause();
    state.audio.removeAttribute('src');
    state.audio.load();
    state.loading = false;
    paint(state);
    if (state.url) URL.revokeObjectURL(state.url);
  }

  document.addEventListener('click', async event => {
    const button = event.target.closest('[data-track-toggle]');
    if (!button) return;
    const element = button.closest('[data-track-src]');
    if (active?.element !== element) {
      stop();
      const audio = new Audio();
      active = { audio, element, src: element.dataset.trackSrc, controller: new AbortController(), loading: true };
      const state = active;
      for (const name of ['loadedmetadata', 'timeupdate', 'play', 'playing', 'pause', 'ended']) {
        audio.addEventListener(name, () => { if (active === state) paint(state); });
      }
      audio.addEventListener('error', () => {
        if (active === state) {
          stop();
          toast('Не удалось воспроизвести трек');
        }
      });
      paint(state);
      try {
        const response = await fetch(state.src, {
          headers: { Authorization: 'tma ' + auth }, signal: state.controller.signal,
        });
        if (!response.ok) throw new Error();
        const blob = await response.blob();
        if (active !== state) return;
        state.blob = blob;
        state.url = URL.createObjectURL(blob);
        audio.src = state.url;
      } catch {
        if (active === state) {
          stop();
          toast('Трек сейчас недоступен');
        }
        return;
      }
      state.loading = false;
      paint(state);
    }
    const state = active;
    if (!state || state.loading) return;
    if (!state.audio.paused) {
      state.audio.pause();
      return;
    }
    try {
      await state.audio.play();
    } catch (error) {
      if (active !== state) return;
      if (error.name === 'NotAllowedError') toast('Нажми «Включить трек» ещё раз');
      else {
        stop();
        toast('Не удалось воспроизвести трек');
      }
    }
  });

  document.addEventListener('input', event => {
    const seek = event.target;
    if (!seek.matches('[data-track-seek]') || active?.element !== seek.closest('[data-track-src]')) return;
    const { audio } = active;
    if (Number.isFinite(audio.duration)) {
      audio.currentTime = Number(seek.value) * audio.duration;
      paint(active);
    }
  });

  // The cabinet refreshes its markup periodically. Keep playback if the same track is still on screen.
  const observer = new MutationObserver(() => {
    if (!active || active.element.isConnected) return;
    const replacement = Array.from(document.querySelectorAll('[data-track-src]'))
      .find(element => element.dataset.trackSrc === active.src && !element.closest('dialog:not([open])'));
    if (!replacement) stop();
    else {
      active.element = replacement;
      paint(active);
    }
  });
  for (const id of ['app', 'sheet-content']) {
    observer.observe(document.getElementById(id), { childList: true, subtree: true });
  }
  document.addEventListener('close', event => {
    if (active && event.target.contains(active.element)) stop();
  }, true);
  window.addEventListener('pagehide', stop);
  return { html, libraryButton, back };
})();
