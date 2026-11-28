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
  const field = "#version 300 es\nprecision highp float;\nprecision highp int;\nuniform vec2 uSize;\nuniform float uDpr;\nuniform vec2 uOrigin;\nuniform vec2 uPitch;\nuniform int uWave;\nuniform float uTime;\nuniform float uUnit;\nuniform vec2 uHeading;\nuniform float uAmp;\nuniform float uDepth;\nuniform vec3 uLight;\nuniform float uShine;\nuniform float uContrast;\nuniform float uInk;\nuniform float uOpacity;\nuniform int uFade;\nuniform float uFadeSize;\nuniform float uAppear;\nuniform sampler2D tRipple;\nuniform float uRipple;\nuniform float uBeat;\nuniform vec4 uTap0;\nuniform vec4 uTap1;\nuniform vec4 uTap2;\nout vec4 fragColor;\n\nconst float FOLDS = 5.5;\n\nuvec3 scramble(uvec3 v) {\n  v = v * 1664525u + 1013904223u;\n  v.x += v.y * v.z;\n  v.y += v.z * v.x;\n  v.z += v.x * v.y;\n  v ^= v >> 16u;\n  v.x += v.y * v.z;\n  v.y += v.z * v.x;\n  v.z += v.x * v.y;\n  return v;\n}\n\nvec3 lattice(vec3 corner) {\n  uvec3 h = scramble(uvec3(ivec3(corner) + 4096));\n  return vec3(h & 65535u) / 32767.5 - 1.0;\n}\n\nfloat gradientNoise(vec3 p) {\n  vec3 i = floor(p);\n  vec3 f = p - i;\n  vec3 u = f * f * f * (f * (f * 6.0 - 15.0) + 10.0);\n  float n000 = dot(lattice(i), f);\n  float n100 = dot(lattice(i + vec3(1.0, 0.0, 0.0)), f - vec3(1.0, 0.0, 0.0));\n  float n010 = dot(lattice(i + vec3(0.0, 1.0, 0.0)), f - vec3(0.0, 1.0, 0.0));\n  float n110 = dot(lattice(i + vec3(1.0, 1.0, 0.0)), f - vec3(1.0, 1.0, 0.0));\n  float n001 = dot(lattice(i + vec3(0.0, 0.0, 1.0)), f - vec3(0.0, 0.0, 1.0));\n  float n101 = dot(lattice(i + vec3(1.0, 0.0, 1.0)), f - vec3(1.0, 0.0, 1.0));\n  float n011 = dot(lattice(i + vec3(0.0, 1.0, 1.0)), f - vec3(0.0, 1.0, 1.0));\n  float n111 = dot(lattice(i + vec3(1.0, 1.0, 1.0)), f - vec3(1.0, 1.0, 1.0));\n  return mix(\n    mix(mix(n000, n100, u.x), mix(n010, n110, u.x), u.y),\n    mix(mix(n001, n101, u.x), mix(n011, n111, u.x), u.y),\n    u.z\n  );\n}\n\nvec2 turn(vec2 v, float angle) {\n  float c = cos(angle);\n  float s = sin(angle);\n  return vec2(c * v.x - s * v.y, s * v.x + c * v.y);\n}\n\nfloat surface(vec2 p, float t) {\n  if (uWave == 0) {\n    vec2 side = vec2(-uHeading.y, uHeading.x);\n    float u = dot(p, uHeading);\n    float v = dot(p, side);\n    float bend = gradientNoise(vec3(v * 0.85, u * 0.3, t * 0.05)) * 1.7 + 0.4 * sin(v * 1.6 + t * 0.2);\n    float phase = u * FOLDS + bend - t * 0.45;\n    float swell = 0.6 + 0.4 * gradientNoise(vec3(u * 0.55 + 3.0, v * 0.45, t * 0.04));\n    float fold = sin(phase) + 0.32 * sin(2.0 * phase + 1.3);\n    float ripple = 0.16 * sin(u * FOLDS * 2.5 + bend * 1.9 - t * 0.9 + 2.1);\n    return (fold + ripple) * swell;\n  }\n  if (uWave == 1) {\n    float bend = gradientNoise(vec3(p * 0.6, t * 0.05)) * 0.6;\n    float phase = dot(p, uHeading) * 15.0 + bend * 2.2 - t * 1.4;\n    float swell = sin(phase) + 0.3 * sin(2.0 * phase - 0.8);\n    float roll = 0.75 + 0.25 * gradientNoise(vec3(p * 0.9 + 11.0, t * 0.05));\n    return 0.8 * swell * roll;\n  }\n  float r = length(p + uHeading * 1.2);\n  float bend = gradientNoise(vec3(p * 1.2, t * 0.05)) * 0.1;\n  return sin((r + bend) * 9.0 - t * 1.8) * (0.45 + 0.55 * exp(-(r - 0.6) * 0.8));\n}\n\nfloat touchWave(vec2 css, vec4 tap) {\n  if (tap.w <= 0.0 || tap.z > 1.6) return 0.0;\n  float distanceToTap = length(css - tap.xy);\n  float front = distanceToTap - tap.z * 270.0;\n  float envelope = exp(-front * front / 5200.0) * exp(-tap.z * 2.7);\n  return sin(front * 0.065) * envelope * tap.w * 0.30;\n}\nfloat heightAt(vec2 css) {\n  float h = surface((css - 0.5 * uSize) / uUnit, uTime) * uAmp;\n  if (uRipple > 0.0) h += texture(tRipple, css / uSize).r * uRipple;\n  h += touchWave(css,uTap0) + touchWave(css,uTap1) + touchWave(css,uTap2);\n  return h;\n}\n\nvoid main() {\n  vec2 cell = floor(gl_FragCoord.xy);\n  vec2 center = uOrigin + (cell + 0.5) * uPitch;\n  vec2 css = center / uDpr;\n  vec2 uv = css / uSize;\n  float e = max(uPitch.y / uDpr, 4.0);\n  float h = heightAt(css);\n  float hx = (heightAt(css + vec2(e, 0.0)) - heightAt(css - vec2(e, 0.0))) / (2.0 * e);\n  float hy = (heightAt(css + vec2(0.0, e)) - heightAt(css - vec2(0.0, e))) / (2.0 * e);\n  vec2 grad = vec2(hx, hy) * uUnit * uDepth * 0.4;\n  vec3 n = normalize(vec3(-grad, 1.0));\n\n  float diffuse = clamp(dot(n, uLight), 0.0, 1.0);\n  vec3 halfway = normalize(uLight + vec3(0.0, 0.0, 1.0));\n  float spec = pow(clamp(dot(n, halfway), 0.0, 1.0), 160.0) * uShine * 1.15;\n  float hollow = 0.7 + 0.3 * clamp(h * 0.5 + 0.5, 0.0, 1.0);\n  float tone = clamp(diffuse * hollow * 0.78 + spec, 0.0, 1.0);\n  tone = clamp((tone - 0.42) * uContrast + 0.42, 0.0, 1.0);\n\n  float level = uInk > 0.5 ? pow(clamp(1.0 - tone / 0.46, 0.0, 1.0), 2.4) * 0.72 : pow(tone, 2.2);\n  float emphasis = uInk > 0.5 ? smoothstep(0.55, 0.95, level) : clamp(spec * 1.6, 0.0, 1.0);\n\n  float fade = 1.0;\n  vec2 c = uv * 2.0 - 1.0;\n  if (uFade == 1) {\n    fade = 1.0 - smoothstep(1.0 - uFadeSize, 1.18, length(c));\n  } else if (uFade == 2) {\n    fade = mix(0.05, 1.0, smoothstep(0.08, 0.08 + uFadeSize, length(c * vec2(1.0, 1.35))));\n  } else if (uFade == 3) {\n    fade = smoothstep(0.0, uFadeSize, uv.y);\n  } else if (uFade == 4) {\n    fade = smoothstep(0.0, uFadeSize, 1.0 - uv.y);\n  }\n\n  float reach = length(css - 0.5 * uSize) / max(0.5 * length(uSize), 1.0);\n  float appear = smoothstep(reach - 0.05, reach + 0.3, uAppear * 1.35);\n\n  level = clamp(level * (1.0 + uBeat * 0.65) + uBeat * 0.12, 0.0, 1.0);\n  float alpha = uOpacity * fade * appear * (0.22 + 0.78 * level);\n  float lift = clamp(h * uDepth * 0.42, -0.48, 0.48);\n  fragColor = vec4(level, alpha, emphasis, lift + 0.5);\n}\n";
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
        draw(time, energy=0, rings=[], beat=0) {
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
          const tapAt=i=>rings[i]?[w*rings[i].x,h*(1-rings[i].y),rings[i].age,rings[i].strength]:[0,0,0,0];
          gl.bindFramebuffer(gl.FRAMEBUFFER,framebuffer);gl.viewport(0,0,cols,rows);
          uniforms(fp,{uSize:[w,h],uDpr:ratio,uOrigin:origin,uPitch:[pitch,pitch],uWave:0,uTime:time*.35,uUnit:520,uHeading:[Math.cos(angle),Math.sin(angle)],uAmp:1+energy*.16+beat*.42,uDepth:.95+energy*.08+beat*.16,uLight:[-Math.cos(angle)*.78,-Math.sin(angle)*.78,.62],uShine:.8+energy*.20+beat*.65,uContrast:1.2,uInk:0,uOpacity:.76+beat*.24,uFade:0,uFadeSize:.5,uAppear:1,tRipple:1,uRipple:0,uBeat:beat,uTap0:tapAt(0),uTap1:tapAt(1),uTap2:tapAt(2)});
          gl.drawArrays(gl.TRIANGLES,0,3);
          gl.bindFramebuffer(gl.FRAMEBUFFER,null);gl.viewport(0,0,cw,ch);
          uniforms(mp,{tField:0,tAtlas:1,uOrigin:origin,uPitch:[pitch,pitch],uGrid:[cols,rows],uPattern:0,uMarkSize:.82+beat*.32,uStroke:1,uColor:[.57,.72,.86],uAccent:[.84+beat*.13,.91+beat*.07,1],uBackground:[0,0,0,0],uAtlas:[1,1,0]});
          gl.drawArrays(gl.TRIANGLES,0,3);
        },
        destroy
      };
    } catch(error) {destroy();return null;}
  }
  // Keep the WebView's native canvas (including iOS rubber-band areas) in sync.
  function stopScene(s,immediate=false) {
    if(!s)return;
    s.host.classList.remove('nora-profile-music');
    s.element?.style.removeProperty('--music-energy');
    s.energy=0;s.beat=0;
    s.layer.style.removeProperty('--music-beat');
    if(scene===s)syncTelegramPalette();
    s.running=false;cancelAnimationFrame(s.raf);s.raf=0;
    s.layer.classList.remove('is-playing');
    clearTimeout(s.removeTimer);
    const dispose=()=>{
      s.renderer?.destroy();s.layer.remove();
      if(scene===s)scene=null;
    };
    if(immediate)dispose();else s.removeTimer=setTimeout(dispose,520);
  }
  // Reuse the original touch ripple shader, but emit rings only at measured
  // musical onsets. Audio-clock ages keep rings aligned through seeks and pauses.
  function musicRings(track, seconds) {
    if(!track?.hits||!Number.isFinite(seconds))return [];
    const rings=[],index=Math.floor(Math.max(0,seconds)*40);
    for(let i=Math.min(index,track.hits.length-1);i>=Math.max(0,index-64)&&rings.length<3;i--){
      const strength=track.hits[i];
      const age=seconds-i/40;
      if(!strength||age<0||age>=1.6)continue;
      // A stable low-discrepancy sequence spreads consecutive hits across the
      // viewport. Rewinding reproduces the same locations, without frame jitter.
      const ordinal=track.hitOrdinals?.[i]||i+1;
      const fract=v=>v-Math.floor(v);
      const x=.14+.72*fract(ordinal*.61803398875+.17);
      const y=.16+.70*fract(ordinal*.41421356237+.31);
      rings.push({x,y,age,strength});
    }
    return rings;
  }
  function tick(s,now) {
    s.raf=0;
    if(!s.running||document.hidden)return;
    if(!s.last||now-s.last>=32){
      const dt=s.last?Math.min(.1,(now-s.last)/1000):.033;
      s.last=now;
      const quiet=reduced.matches;
      const seconds=s.track?.audio.currentTime||0;
      const index=Math.floor(seconds*40);
      const target=quiet?0:(s.track?.envelope?.[index]||0);
      // Fast attack and a short tail give individual kicks a clear visual impact.
      const beat=quiet?0:Math.max(s.track?.beats?.[index]||0,s.track?.beats?.[index+1]||0);
      s.energy+=(target-s.energy)*(1-Math.exp(-dt/(target>s.energy?.05:.16)));
      s.beat=quiet?0:Math.max(beat,s.beat*Math.exp(-dt/.105));
      if(!quiet)s.time+=dt*(1+s.energy*.32+s.beat*.65);
      s.renderer?.draw(s.time,quiet?0:s.energy,quiet?[]:musicRings(s.track,seconds),s.beat);
      s.element?.style.setProperty('--music-energy',Math.max(s.energy*.45,s.beat).toFixed(3));
      s.layer.style.setProperty('--music-beat',s.beat.toFixed(3));
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
      scene={host,layer,renderer:engine,raf:0,last:0,time:0,running:false,energy:0,beat:0,element:null,track:null};
      canvas.addEventListener('webglcontextlost',event=>{event.preventDefault();if(scene?.layer===layer){cancelAnimationFrame(scene.raf);scene.raf=0;scene.renderer=null;canvas.hidden=true;}});
      canvas.addEventListener('webglcontextrestored',()=>{if(scene?.layer===layer){scene.renderer=renderer(canvas);canvas.hidden=!scene.renderer;wake(scene);}});
    }
    if(scene.element!==element)scene.element?.style.removeProperty('--music-energy');
    if(scene.track!==track){scene.beat=0;scene.energy=0;}
    scene.element=element;scene.track=track;
    if(scene.running)return;
    clearTimeout(scene.removeTimer);scene.running=true;host.classList.add('nora-profile-music');
    syncTelegramPalette();
    const s=scene;requestAnimationFrame(()=>{if(s.running)s.layer.classList.add('is-playing');});
    wake(s);
  }
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
  let queue = [], queueIndex = -1, shuffle = false, repeat = false;
  let playIntent = 0, playerReturn = null;
  const mini = document.getElementById('nora-mini-player');
  const miniHome = mini.parentElement, miniNext = mini.nextSibling;
  const miniOpen = mini.querySelector('[data-mini-open]');
  const miniToggle = mini.querySelector('[data-mini-toggle]');
  const miniTitle = mini.querySelector('[data-mini-title]');
  const miniArtist = mini.querySelector('[data-mini-artist]');
  const miniProgress = mini.querySelector('progress');
  const miniShare = mini.querySelector('[data-mini-share]');
  let sharePending = false, miniSource = '', sharedSource = '', shareUntil = 0, shareTimer = 0;
  const miniMotion = matchMedia('(prefers-reduced-motion: reduce)');
  // Session-only LRU: never persist private profile music on a shared device.
  const musicCache = new Map();
  const musicCacheLimit = 64 * 1024 * 1024, musicCacheCount = 8, musicCacheTTL = 20 * 60 * 1000;
  let musicCacheBytes = 0, musicCacheAuth = null;
  function clearMusicCache() {
    musicCache.clear(); musicCacheBytes = 0; musicCacheAuth = null;
  }
  function removeCachedTrack(key) {
    const item = musicCache.get(key);
    if (item) { musicCacheBytes -= item.blob.size; musicCache.delete(key); }
  }
  function syncMusicCache() {
    if (musicCacheAuth !== auth) { clearMusicCache(); musicCacheAuth = auth; }
    const now = Date.now();
    for (const [key, item] of musicCache) if (item.expires <= now) removeCachedTrack(key);
  }
  function cachedTrack(key) {
    syncMusicCache();
    const item = musicCache.get(key);
    if (!item) return null;
    musicCache.delete(key); musicCache.set(key, item);
    return item.blob;
  }
  function rememberTrack(key, blob) {
    syncMusicCache(); removeCachedTrack(key);
    if (!blob.size || blob.size > musicCacheLimit) return;
    while (musicCache.size >= musicCacheCount || musicCacheBytes + blob.size > musicCacheLimit) {
      removeCachedTrack(musicCache.keys().next().value);
    }
    musicCache.set(key, {blob, expires: Date.now() + musicCacheTTL});
    musicCacheBytes += blob.size;
  }

  // Analyse the already downloaded track separately. Never route playback through
  // AudioContext: a suspended Web Audio graph must not mute iOS playback.
  // Callback and Promise variants are both supported by older iOS WebViews.
  function decodeTrack(context,bytes) {
    return new Promise((resolve,reject)=>{
      try{const result=context.decodeAudioData(bytes,resolve,reject);result?.then?.(resolve,reject);}catch(error){reject(error);}
    });
  }
  async function decodeProfileTrack(blob,duration) {
    const Offline=window.OfflineAudioContext||window.webkitOfflineAudioContext;
    if(Offline){
      for(const rate of [22050,44100]){
        try{return await decodeTrack(new Offline(1,1,rate),await blob.arrayBuffer());}catch{}
      }
    }
    const AudioCtx=window.AudioContext||window.webkitAudioContext;
    if(!AudioCtx||duration>300)throw Error('Decoder unavailable');
    let context;
    try{
      context=new AudioCtx({sampleRate:22050});
      return await decodeTrack(context,await blob.arrayBuffer());
    }finally{try{await context?.close();}catch{}}
  }
  async function prepareMusicEnvelope(state) {
    if(state.analysisStarted||!state.blob||!state.element?.closest('#app[data-screen="lk"] .lk-screen,#person-profile')||
       matchMedia('(prefers-reduced-motion: reduce)').matches)return;
    const duration=state.audio.duration;
    if(!Number.isFinite(duration)||duration<=0)return;
    state.analysisStarted=true;
    const blob=state.blob;state.blob=null;
    if(duration>600||blob.size>20*1024*1024){state.analysisStatus='limited';return;}
    state.analysisStatus='decoding';
    try{
      const decoded=await decodeProfileTrack(blob,duration);
      if(active!==state||decoded.duration>600)return;
      const samples=decoded.getChannelData(0);
      const second=decoded.numberOfChannels>1?decoded.getChannelData(1):null;
      const stride=Math.max(1,Math.floor(decoded.sampleRate/6000));
      const rate=decoded.sampleRate/stride;
      const lowAlpha=1-Math.exp(-2*Math.PI*125/rate);
      const highAlpha=1-Math.exp(-2*Math.PI*35/rate);
      const count=Math.ceil(decoded.duration*40);
      const raw=new Float32Array(count),wide=new Float32Array(count);
      let low=0,sub=0;
      for(let frame=0;frame<count;frame++){
        const start=Math.floor(frame*decoded.sampleRate/40);
        const end=Math.min(samples.length,Math.floor((frame+1)*decoded.sampleRate/40));
        let bass=0,full=0,n=0;
        for(let i=start;i<end;i+=stride){
          const a=samples[i],b=second?second[i]:a;
          const value=Math.abs(a)>=Math.abs(b)?a:b;
          low+=(value-low)*lowAlpha;sub+=(value-sub)*highAlpha;
          const band=low-sub*.65;
          bass+=band*band;full+=value*value;n++;
        }
        raw[frame]=Math.sqrt(bass/Math.max(1,n));
        wide[frame]=Math.sqrt(full/Math.max(1,n));
        if(frame%400===399){
          await new Promise(resolve=>setTimeout(resolve,0));
          if(active!==state)return;
        }
      }
      const levels=new Float32Array(count),beats=new Float32Array(count),hits=new Float32Array(count);
      const hitOrdinals=new Uint16Array(count),hitFrames=[];
      let floor=.002,peak=.008,prev=0,baseline=.002,fluxBase=.001,lastHit=-20,pulse=0;
      for(let frame=0;frame<count;frame++){
        // Adaptive bass envelope and positive spectral-energy flux, not a fake BPM.
        const v=raw[frame]+wide[frame]*.13;
        floor+=(v-floor)*(v<floor?.13:.004);
        peak=Math.max(v,peak*.985,.008);
        const level=Math.min(1,Math.max(0,(v-floor)/(peak-floor+.003)));
        const flux=Math.max(0,v-prev);prev=v;
        const rise=Math.max(0,v-baseline);
        const threshold=Math.max(.002,fluxBase*2.1,peak*.045);
        if(v>.003&&frame-lastHit>=5&&flux>threshold&&rise>Math.max(.002,peak*.07)){
          pulse=Math.min(1,.70+.30*flux/(threshold*2));
          lastHit=frame;
          // Measure actual loudness of this transient over its first 75 ms.
          // Keep the separate global beat pulse unchanged.
          let loudness=0;
          for(let j=frame;j<Math.min(count,frame+3);j++){
            loudness=Math.max(loudness,.72*raw[j]+.28*wide[j]);
          }
          hits[frame]=loudness;
          hitFrames.push(frame);
          hitOrdinals[frame]=hitFrames.length;
        }
        // A short pulse tail remains visible even on a 30 fps WebView.
        beats[frame]=pulse;
        pulse*=.79;
        levels[frame]=v<.001?0:level;
        baseline+=(v-baseline)*.085;
        fluxBase+=(flux-fluxBase)*.06;
      }
      // Normalize to a robust loud-hit reference for this track, not the
      // detection threshold (which previously saturated most hits to 1).
      const loudnesses=hitFrames.map(frame=>hits[frame]).sort((a,b)=>a-b);
      const reference=Math.max(.008,loudnesses[Math.floor(.9*Math.max(0,loudnesses.length-1))]||0);
      for(const frame of hitFrames){
        const ratio=hits[frame]/reference;
        hits[frame]=Math.min(1.45,.10+1.15*Math.pow(ratio,1.35));
      }
      if(active===state){state.envelope=levels;state.beats=beats;state.hits=hits;state.hitOrdinals=hitOrdinals;state.analysisStatus='ready';}
    }catch{
      if(active===state)state.analysisStatus='unavailable';
    }
  }

  function clock(seconds) {
    const total = Math.floor(Number(seconds) || 0);
    return Math.floor(total / 60) + ':' + String(total % 60).padStart(2, '0');
  }

  function coverImage(track, className = 'music-cover') {
    const url = track?.cover;
    if (typeof url !== 'string' || !/^https:\/\/avatars(?:\.mds)?\.yandex\.net\/[A-Za-z0-9_./-]+$/.test(url)) return '';
    return '<img class="' + className + '" src="' + esc(url) + '" loading="lazy" referrerpolicy="no-referrer" alt="">';
  }

  function html(track, endpoint, library = false, readonly = false) {
    if (!track) return '';
    const src = endpoint + '?v=' + encodeURIComponent(track.revision);
    const saved = library || Boolean(track.saved);
    const save = track.id && !readonly ? `<button type="button" class="profile-track-save" data-track-save data-track-id="${esc(track.id)}" data-save-path="${esc(library ? 'music-library' : endpoint.slice(5) + '/save')}" data-track-revision="${esc(track.revision)}" data-saved="${saved}" aria-pressed="${saved}" aria-label="${saved ? NoraI18n.t("Удалить из моих треков") : NoraI18n.t("Добавить в мои треки")}">${saved ? '✓' : '+'}</button>` : '';
    return `<section class="profile-track" data-track-src="${esc(src)}" data-track-id="${esc(track.id || '')}" data-track-title="${esc(track.title)}" data-track-artist="${esc(track.artist || NoraI18n.t("Неизвестен"))}" data-track-length="${esc(track.duration || 0)}" data-track-cover="${esc(track.cover || '')}" aria-label="${library ? NoraI18n.t("Сохранённый трек") : NoraI18n.t("Трек профиля")}"><div class="profile-track-actions">
      <button type="button" class="profile-track-toggle" data-track-toggle aria-label="${NoraI18n.html("Включить трек:")} ${esc(track.title)}">
        ${library ? coverImage(track) : ''}<span class="profile-track-copy">
          <strong title="${esc(track.title)}">${esc(track.title)}</strong>
          <small>${library ? '' : '– '}${esc(track.artist || NoraI18n.t("Неизвестен"))}</small>
        </span>
      </button>${library ? `<span class="profile-library-duration">${clock(track.duration)}</span>` : ''}${save}</div>
      <div class="profile-track-timeline">
        <span data-track-time>0:00</span>
        <input type="range" min="0" max="1" step="0.001" value="0" data-track-seek aria-label="${NoraI18n.html("Позиция в треке")}" disabled>
        <span data-track-duration>${clock(track.duration)}</span>
      </div>
    </section>`;
  }

  function libraryButton(owner = '') {
    return `<button type="button" class="profile-library-open" data-music-library="${esc(owner)}">${owner ? NoraI18n.t("Треки") : NoraI18n.t("Мои треки")} <span aria-hidden="true">›</span></button>`;
  }

  function libraryScreen(title, subtitle, content) {
    return '<section id="music-library-profile" tabindex="-1" autofocus data-music-library-panel>' +
      '<header class="profile-library-header"><div class="profile-library-symbol" aria-hidden="true">' +
      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M3 14v-3a9 9 0 0 1 18 0v3M3 13h2a2 2 0 0 1 2 2v4a2 2 0 0 1-2 2H4a1 1 0 0 1-1-1v-7Zm18 0h-2a2 2 0 0 0-2 2v4a2 2 0 0 0 2 2h1a1 1 0 0 0 1-1v-7Z"/></svg></div>' +
      '<h2>' + esc(title) + '</h2><p data-library-count>' + esc(subtitle) + '</p></header>' +
      '<div class="profile-library-content">' + content + '</div></section>';
  }

  function libraryCount(count) {
    return number(count) + ' ' + plural(count, NoraI18n.t("трек"), NoraI18n.t("трека"), NoraI18n.t("треков"));
  }

  function libraryEmpty() {
    return ("<div class=\"profile-library-empty\"><strong>" + NoraI18n.html("Пока нет треков") + "</strong><p>" + NoraI18n.html("Сохранённая музыка появится здесь.") + "</p></div>");
  }

  function back() {
    const dialog = $('#sheet');
    if (!dialog.open) return false;
    if ($('#nora-now-playing')) { closeNowPlaying(); return true; }
    if (!$('#music-library-profile')) return false;
    const origin = libraryReturn;
    libraryReturn = null;
    if (origin) {
      void window.NoraPeople.visit(origin);
    } else {
      dialog.close();
    }
    return true;
  }


  function ownLibrary(panel, result, visibility) {
    panel.classList.add('music-discovery');
    panel.querySelector('.profile-library-header h2').textContent = NoraI18n.t("Музыка");
    const content = panel.querySelector('.profile-library-content');
    const t = NoraI18n.html;
    content.innerHTML = '<form class="music-search" data-music-search><span aria-hidden="true">⌕</span>' +
      '<input type="search" maxlength="120" data-music-query placeholder="' + t("Трек, исполнитель…") + '" aria-label="' + t("Поиск музыки") + '">' +
      '<button type="submit">' + t("Найти") + '</button></form>' +
      '<div class="music-tabs" role="group" aria-label="' + t("Музыка") + '">' +
      '<button type="button" data-music-tab="home" aria-pressed="true">' + t("Обзор") + '</button>' +
      '<button type="button" data-music-tab="mine" aria-pressed="false">' + t("Мои треки") + '</button>' +
      '<button type="button" data-music-tab="search" aria-pressed="false">' + t("Поиск") + '</button></div>' +
      '<div class="music-discovery-cards" data-music-cards>' +
      '<button type="button" class="music-feature music-feature-purple" data-music-go="wave"><small>NORA / WAVE</small><strong>' + t("Моя волна") + '</strong><span>' + t("Музыка в твоём вкусе") + ' ↗</span></button>' +
      '<button type="button" class="music-feature music-feature-red" data-music-go="top"><small>NORA / TOP</small><strong>' + t("Топ Норы") + '</strong><span>' + t("Популярная музыка") + ' ↗</span></button>' +
      '<button type="button" class="music-feature music-feature-blue" data-music-go="friends"><small>FRIENDS</small><strong>' + t("Музыка друзей") + '</strong><span>' + t("На одной волне") + ' ↗</span></button>' +
      '<button type="button" class="music-feature music-feature-history" data-music-go="history"><small>RECENT</small><strong>' + t("История") + '</strong><span>' + t("Недавно слушал") + ' ↗</span></button></div>' +
      '<section data-music-social hidden><div class="music-social-header"><h3 data-music-social-title></h3><div data-music-period class="music-period" hidden><button type="button" data-period="day">' + t("Сутки") + '</button><button type="button" data-period="week" aria-pressed="true">' + t("Неделя") + '</button><button type="button" data-period="all">' + t("Вся история") + '</button></div></div><div data-music-social-results aria-live="polite"></div></section>' +
      '<label class="profile-library-visibility" data-music-activity-wrap><span><strong>' + t("Музыкальная активность") + '</strong><small>' + t("Друзья увидят недавнюю музыку, треки попадут в общий рейтинг") + '</small></span><input type="checkbox" role="switch" data-music-activity disabled></label>' +
      '<div class="music-discovery-heading"><h3 data-music-heading>' + t("Недавно добавлено") + '</h3></div>' +
      '<div class="profile-library-list">' + result.tracks.map(track => html(track, '/api/music-library/' + track.id, true)).join('') + '</div>' +
      '<div data-music-local-empty hidden>' + libraryEmpty() + '</div>' +
      '<section data-music-catalog hidden><div class="music-wave-head"><h3 data-catalog-heading>' + t("Яндекс Музыка") + '</h3><button type="button" data-wave-refresh hidden>' + t("Обновить") + ' ↻</button></div><div data-music-results aria-live="polite"></div></section>' +
      '<div data-music-visibility>' + visibility + '</div>';
    const form = content.querySelector('[data-music-search]');
    const input = content.querySelector('[data-music-query]');
    const catalog = content.querySelector('[data-music-catalog]');
    const remote = content.querySelector('[data-music-results]');
    const list = content.querySelector('.profile-library-list');
    const social = content.querySelector('[data-music-social]');
    const socialResults = content.querySelector('[data-music-social-results]');
    const activity = content.querySelector('[data-music-activity]');
    let mode = 'home', generation = 0, controller = null, importPending = false, socialGeneration = 0, period = 'week', waveTracks = [];
    const alive = () => panel.isConnected && $('#sheet').open;
    const normalize = value => value.toLocaleLowerCase().trim();
    function filter() {
      const q = normalize(input.value);
      let count = 0;
      for (const [i, row] of Array.from(list.querySelectorAll('[data-track-src]')).entries()) {
        const match = !q || q.split(/\s+/).every(word => normalize(row.dataset.trackTitle + ' ' + row.dataset.trackArtist).includes(word));
        row.hidden = !match || (mode === 'home' && i >= 5);
        if (!row.hidden) count++;
      }
      for (const button of remote.querySelectorAll('[data-music-import][data-saved-id]')) {
        const saved = Array.from(list.querySelectorAll('[data-track-src]')).some(row => row.dataset.trackId === button.dataset.savedId);
        if (!saved && button.textContent === '✓') { button.disabled = false; button.textContent = '+'; }
      }
      const socialMode = ['top','friends','history'].includes(mode);
      const waveMode = mode === 'wave';
      list.hidden = count === 0 || socialMode || waveMode;
      const empty = content.querySelector('[data-music-local-empty]');
      empty.hidden = count > 0 || socialMode || waveMode;
      empty.innerHTML = q ? '<div class="profile-library-empty">' + t("В коллекции ничего не найдено") + '</div>' : libraryEmpty();
      content.querySelector('[data-music-cards]').hidden = mode !== 'home';
      content.querySelector('[data-music-visibility]').hidden = mode === 'search' || mode === 'wave';
      content.querySelector('[data-music-heading]').textContent = NoraI18n.t(mode === 'home' ? "Недавно добавлено" : mode === 'search' ? "В твоей коллекции" : "Мои треки");
      catalog.hidden = mode !== 'search' && !waveMode;
      content.querySelector('[data-catalog-heading]').textContent = NoraI18n.t(waveMode ? 'Моя волна' : 'Яндекс Музыка');
      content.querySelector('[data-wave-refresh]').hidden = !waveMode;
      content.querySelector('.music-discovery-heading').hidden = socialMode || waveMode;
      social.hidden = !socialMode;
      content.querySelector('[data-music-activity-wrap]').hidden = mode === 'search' || waveMode;
      panel.querySelector('[data-library-count]').textContent = libraryCount(list.querySelectorAll('[data-track-src]').length);
    }
    function setMode(next, focus = false) {
      const previousMode = mode;
      mode = next;
      for (const button of content.querySelectorAll('[data-music-tab]')) button.setAttribute('aria-pressed', String(button.dataset.musicTab === mode));
      if (mode !== 'search') { input.value = ''; generation++; controller?.abort(); remote.innerHTML = ''; }
      else if (previousMode !== 'search' || !remote.innerHTML) remote.innerHTML = '<p class="music-catalog-note">' + t("Введи название или исполнителя и нажми «Найти».") + '</p>';
      filter();
      if (mode === 'wave') void loadWave();
      if (['top','friends','history'].includes(mode)) void loadSocial();
      else socialGeneration++;
      if (focus) input.focus();
    }

    function socialRow(track, label = '') {
      const live = track.playing ? '<span class="music-equalizer" aria-hidden="true"><i></i><i></i><i></i></span> ' + t("Сейчас слушает") : '';
      return '<div class="music-social-item">' + (label ? '<p class="music-social-label">' + esc(label) + (live ? ' · ' + live : '') + '</p>' : '') +
        html(track, track.source, true, true) + '</div>';
    }
    let friendsRefresh = 0;
    async function loadSocial(quiet = false) {
      clearTimeout(friendsRefresh);
      const version = ++socialGeneration;
      const kind = mode;
      content.querySelector('[data-music-social-title]').textContent = NoraI18n.t({top:"Топ Норы",friends:"Музыка друзей",history:"История"}[kind]);
      content.querySelector('[data-music-period]').hidden = kind !== 'top';
      for (const item of content.querySelectorAll('[data-period]')) item.setAttribute('aria-pressed', String(item.dataset.period === period));
      if (!quiet) socialResults.innerHTML = '<p class="music-catalog-note">' + t("Загрузка…") + '</p>';
      try {
        const response = await api(kind === 'history' ? 'music-library/history' : 'music-library/social?' + new URLSearchParams({period}));
        if (!alive() || version !== socialGeneration) return;
        const tracks = kind === 'history' ? response.tracks : kind === 'top' ? response.top : response.friends;
        socialResults.innerHTML = tracks.length ? '<div class="music-social-list">' +
          tracks.map((track, i) => socialRow(track, kind === 'top' ? (i+1) + ' · ' + track.listeners + ' ' + NoraI18n.t("слушателей") : kind === 'friends' ? track.name : '')).join('') + '</div>' :
          '<div class="profile-library-empty">' + t("Здесь пока тихо") + '</div>';
      } catch (error) {
        if (alive() && version === socialGeneration && !quiet) socialResults.textContent = error.message;
      } finally {
        if (kind === 'friends' && alive() && version === socialGeneration) friendsRefresh = setTimeout(() => {
          if (alive() && mode === 'friends') void loadSocial(true);
        }, 20000);
      }
    }
    void api('music-library/history').then(value => {
      if (alive()) { activity.checked = Boolean(value.public); activity.disabled = false; }
    }).catch(() => {});
    activity.addEventListener('change', async () => {
      const value = activity.checked;
      activity.disabled = true;
      try { await api('music-library/activity', {public:value}); }
      catch (error) { activity.checked = !value; toast(error.message); }
      finally { activity.disabled = false; }
      if (['top','friends'].includes(mode)) void loadSocial();
    });
    content.addEventListener('click', event => {
      const periodButton = event.target.closest('[data-period]');
      if (periodButton) { period = periodButton.dataset.period; void loadSocial(); return; }
      const button = event.target.closest('[data-music-tab], [data-music-go]');
      if (button) {
        const next = button.dataset.musicTab || button.dataset.musicGo;
        setMode(next, next === 'search' && Boolean(button.dataset.musicGo));
      }
    });
    input.addEventListener('input', () => {
      generation++;
      controller?.abort();
      if (mode !== 'search') setMode('search');
      remote.innerHTML = '<p class="music-catalog-note">' + t("Введи название или исполнителя и нажми «Найти».") + '</p>';
      filter();
    });
    function renderCatalog(response, wave = false) {
      remote.innerHTML = response.tracks.length ? '<p class="music-catalog-note">' + t(wave ? (response.personalized ? "Подборка по твоему вкусу и новые открытия" : "Случайная музыка из каталога") : "Слушай без лимитов. Новому треку может понадобиться время на загрузку.") + '</p>' +
          response.tracks.map(track => '<article class="music-catalog-row"><button type="button" class="music-catalog-art" data-music-play="' + esc(track.id) + '" aria-label="' + t("Воспроизвести") + '">' + coverImage(track) + '<span class="music-catalog-glyph">▶</span></button><button type="button" class="music-catalog-copy" data-music-play="' + esc(track.id) + '"><strong>' +
            esc(track.title) + '</strong><small>' + esc(track.artist) + ' · ' + clock(track.duration) + '</small></button><button type="button" data-music-import="' +
            esc(track.id) + '" data-saved-id="' + esc(track.saved_id || '') + '" aria-label="' + t(track.saved_id ? "Добавлено в Мои треки" : "Добавить в мои треки") + '"' + (track.saved_id ? ' disabled>✓' : '>+') + '</button></article>').join('') :
          '<p class="music-catalog-note">' + t("Треки не найдены") + '</p>';
    }
    async function loadWave() {
      if (importPending) return;
      const version = ++generation;
      const refresh = content.querySelector('[data-wave-refresh]');
      refresh.disabled = true;
      remote.innerHTML = '<p class="music-catalog-note" role="status">' + t("Собираем твою волну…") + '</p>';
      try {
        const response = await api('music-library/wave');
        if (!alive() || version !== generation || mode !== 'wave') return;
        waveTracks = response.tracks;
        renderCatalog(response, true);
      } catch (error) {
        if (alive() && version === generation) remote.textContent = error.message;
      } finally { refresh.disabled = false; }
    }
    content.querySelector('[data-wave-refresh]').addEventListener('click', () => void loadWave());
    form.addEventListener('submit', async event => {
      event.preventDefault();
      if (importPending) return;
      const q = input.value.trim();
      if (q.length < 2) { toast(NoraI18n.t("Введи от 2 до 120 символов.")); return; }
      setMode('search');
      input.blur();
      controller?.abort();
      controller = new AbortController();
      const version = ++generation;
      remote.innerHTML = '<p class="music-catalog-note" role="status">' + t("Ищем музыку…") + '</p>';
      try {
        const response = await api('music-library/search?' + new URLSearchParams({q}), null, controller.signal);
        if (!alive() || version !== generation) return;
        renderCatalog(response);
      } catch (error) {
        if (alive() && version === generation) remote.textContent = error.message;
      }
    });
    remote.addEventListener('click', async event => {

      const playButton = event.target.closest('[data-music-play]');
      if (playButton) {
        const row = playButton.closest('.music-catalog-row');
        if (row.dataset.playSource && active?.src === row.dataset.playSource) {
          void toggleActive(active); return;
        }
        if (importPending) return;
        const intent = ++playIntent;
        const version = generation;
        importPending = true;
        const art = row.querySelector('.music-catalog-glyph');
        art.textContent = '…';
        try {
          const isWave = mode === 'wave';
          const response = await api('music-library/play', {id:playButton.dataset.musicPlay, wave:isWave});
          if (!alive() || version !== generation || intent !== playIntent) return;
          const track = response.track;
          const item = {src: response.source + '?v=' + encodeURIComponent(track.revision), track};
          row.dataset.playSource = item.src;
          if (isWave) {
            queue = waveTracks.map(t => t.id === playButton.dataset.musicPlay ? {...item,wave:true,catalogId:t.id} : {wave:true,catalogId:t.id,track:t});
            queueIndex = queue.findIndex(t=>t.catalogId === playButton.dataset.musicPlay);
          } else { queue = [item]; queueIndex = 0; }
          void startTrack(item);
        } catch (error) { if (alive()) toast(error.message); }
        finally { importPending = false; if (art.textContent === '…') art.textContent = '▶'; }
        return;
      }
      const button = event.target.closest('[data-music-import]');
      if (!button || button.disabled || importPending) return;
      importPending = true;
      const version = generation;
      button.disabled = true;
      button.textContent = '…';
      try {
        const response = await api('music-library/import', {id: button.dataset.musicImport, wave:mode === 'wave'});
        if (!alive()) return;
        const track = response.track;
        if (!Array.from(list.querySelectorAll('[data-track-id]')).some(row => row.dataset.trackId === String(track.id))) {
          list.insertAdjacentHTML('afterbegin', html(track, '/api/music-library/' + track.id, true));
        }
        filter();
        if (button.isConnected && version === generation) {
          button.dataset.savedId = String(track.id);
          button.textContent = '✓';
          button.setAttribute('aria-label', NoraI18n.t("Добавлено в Мои треки"));
        }
        toast(NoraI18n.t("Добавлено в Мои треки"));
      } catch (error) {
        if (alive()) toast(error.message);
        if (button.isConnected) { button.disabled = false; button.textContent = '+'; }
      } finally {
        importPending = false;
      }
    });
    panel.addEventListener('music-collection-changed', filter);
    filter();
  }

  async function showLibrary(owner = '') {
    const path = owner ? 'people/' + encodeURIComponent(owner) + '/music-library' : 'music-library';
    const title = owner ? NoraI18n.t("Треки") : NoraI18n.t("Мои треки");
    const person = $('#person-profile');
    libraryReturn = person ? Number(person.dataset.personId) : null;
    sheet(libraryScreen(title, NoraI18n.t("Загрузка…"), ("<div class=\"profile-library-empty\" role=\"status\">" + NoraI18n.html("Загрузка…") + "</div>")));
    const panel = $('#music-library-profile');
    panel.focus({preventScroll:true});
    $('#sheet').scrollTop = 0;
    $('#sheet-content').scrollTop = 0;
    try {
      const result = await api(path);
      if (!panel.isConnected || !$('#sheet').open) return;
      const visibility = owner ? '' : ("<label class=\"profile-library-visibility\"><span><strong>" + NoraI18n.html("Публичная коллекция") + "</strong><small>" + NoraI18n.html("Другие участники смогут слушать твои треки") + "</small></span><input type=\"checkbox\" role=\"switch\" data-library-visibility ") + (result.public ? 'checked' : '') + '></label>';
      if (!owner) { ownLibrary(panel, result, visibility); return; }
      panel.querySelector('[data-library-count]').textContent = libraryCount(result.tracks.length);
      panel.querySelector('.profile-library-content').innerHTML = (result.tracks.length
        ? '<div class="profile-library-list">' + result.tracks.map(track => html(track, '/api/' + path + '/' + track.id, true, Boolean(owner))).join('') + '</div>'
        : libraryEmpty()) + visibility;
    } catch (error) {
      if (panel.isConnected) {
        panel.querySelector('[data-library-count]').textContent = NoraI18n.t("Коллекция недоступна");
        panel.querySelector('.profile-library-content').innerHTML = '<div class="profile-library-empty">' + esc(error.message) + '</div>';
      }
    }
  }

  document.addEventListener('close', event => {
    if (event.target === $('#sheet')) { libraryReturn = null; playerReturn = null; syncMiniHost(); }
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
      toast(value ? NoraI18n.t("Коллекция открыта") : NoraI18n.t("Коллекция приватная"));
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
    button.setAttribute('aria-label', saved ? NoraI18n.t("Удалить из моих треков") : NoraI18n.t("Добавить в мои треки"));
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
      if (active?.track.id === result.id) { active.saved = result.saved; paintNowSaved(active); }
      if (savePath === 'music-library') {
        const row = button.closest('[data-track-src]');
        if (active?.src === row.dataset.trackSrc) stop();
        const panel = row.closest('[data-music-library-panel]');
        row.remove();
        if (panel?.classList.contains('music-discovery')) {
          panel.dispatchEvent(new Event('music-collection-changed'));
        } else if (panel) {
          const count = panel.querySelectorAll('[data-track-src]').length;
          panel.querySelector('[data-library-count]').textContent = libraryCount(count);
          if (!count) panel.querySelector('.profile-library-list')?.insertAdjacentHTML('afterend', libraryEmpty());
          if (!count) panel.querySelector('.profile-library-list')?.remove();
        }
      }
      toast(result.saved ? NoraI18n.t("Добавлено в Мои треки") : NoraI18n.t("Удалено из Моих треков"));
    } catch (error) {
      toast(error.message);
    } finally {
      button.disabled = false;
    }
  });

  // Playback is owned by this module, not by a profile DOM node.
  function matchingRows(state) {
    return Array.from(document.querySelectorAll('[data-track-src]')).filter(element =>
      element.dataset.trackSrc === state.src && !element.closest('dialog:not([open])'));
  }

  function currentRow(state) {
    const rows = matchingRows(state);
    return rows.find(element => element.closest('dialog[open]')) || rows[0] || null;
  }

  function syncMiniHost() {
    const dialog = $('#sheet');
    const library = dialog.open && dialog.querySelector('#music-library-profile');
    const full = dialog.open && dialog.querySelector('#nora-now-playing');
    const docked = Boolean(library && active);
    const wasDocked = dialog.classList.contains('music-mini-docked');
    // Keep the actual touched element mounted throughout a swipe into the
    // full player. Moving it during a touch sequence cancels gestures on iOS.
    if (docked && mini.parentElement !== dialog) {
      dialog.append(mini);
      mini.hidden = false;
      if (!miniMotion.matches) mini.animate?.([{opacity:0,transform:'translateY(18px)'},{opacity:1,transform:'translateY(0)'}],{duration:280,easing:'cubic-bezier(.2,.8,.2,1)'});
    } else if (!docked && !full && mini.parentElement !== miniHome) {
      miniHome.insertBefore(mini, miniNext?.parentElement === miniHome ? miniNext : dialog);
    }
    if (docked !== wasDocked) dialog.classList.toggle('music-mini-docked', docked);
    return docked;
  }

  function closeNowPlaying() {
    const dialog = $('#sheet');
    if (!dialog.querySelector('#nora-now-playing')) return false;
    if (!playerReturn) { dialog.close(); return true; }
    const saved = playerReturn;
    playerReturn = null;
    $('#sheet-content').replaceChildren(saved.panel);
    libraryReturn = saved.libraryReturn;
    syncMiniHost();
    $('#sheet-content').scrollTop = saved.scrollTop;
    saved.panel.focus({preventScroll:true});
    window.NoraShop?.syncBack();
    if (active) paint(active);
    return true;
  }

  function paintMini() {
    syncMiniHost();
    const state = active;
    const visible = Boolean(state && document.querySelector('#nav .nav-drop'));
    mini.hidden = !visible;
    document.body.classList.toggle('nora-mini-player-active', visible);
    if (!visible) {
      for (const art of document.querySelectorAll('.music-catalog-row[data-play-source] .music-catalog-glyph')) art.textContent = '▶';
      return;
    }
    const { audio, loading, track } = state;
    const playing = !audio.paused && !audio.ended;
    const artist = loading ? NoraI18n.t("Загрузка…") : track.artist;
    if (miniTitle.textContent !== track.title) miniTitle.textContent = track.title;
    if (miniArtist.textContent !== artist) miniArtist.textContent = artist;
    if (miniSource !== state.src) {
      miniSource = state.src;
      const artwork = mini.querySelector('.nora-mini-art');
      artwork.querySelector('img')?.remove();
      artwork.insertAdjacentHTML('beforeend', coverImage(track, 'music-mini-cover'));
      if (!miniMotion.matches) mini.querySelector('.nora-mini-copy').animate?.([
        {opacity: .25, transform: 'translateY(5px)'}, {opacity: 1, transform: 'translateY(0)'}
      ], {duration: 240, easing: 'cubic-bezier(.2,.8,.2,1)'});
    }
    miniShare.disabled = loading || sharePending || Date.now() < shareUntil;
    miniShare.dataset.sending = String(sharePending);
    miniShare.dataset.sent = String(!sharePending && sharedSource === state.src && Date.now() < shareUntil);
    miniShare.setAttribute('aria-label', sharePending ? NoraI18n.t("Отправляем трек") : Date.now() < shareUntil ? NoraI18n.t("Повторная отправка доступна через 5 минут") : NoraI18n.t("Поделиться треком в чате"));
    const fullShare = $('#nora-now-playing [data-now-share]');
    if (fullShare) {
      fullShare.disabled = miniShare.disabled;
      fullShare.dataset.sending = miniShare.dataset.sending;
      fullShare.dataset.sent = miniShare.dataset.sent;
      fullShare.setAttribute('aria-label', miniShare.getAttribute('aria-label'));
    }
    for (const row of document.querySelectorAll('.music-catalog-row[data-play-source]')) {
      const art = row.querySelector('.music-catalog-glyph');
      if (art) art.textContent = row.dataset.playSource === state.src ? (loading ? '…' : playing ? 'Ⅱ' : '▶') : '▶';
    }
    mini.dataset.playing = String(playing);
    miniToggle.disabled = loading;
    miniToggle.setAttribute('aria-label', loading ? NoraI18n.t("Загружаем трек") : playing ? NoraI18n.t("Пауза") : NoraI18n.t("Воспроизвести"));
    miniOpen.setAttribute('aria-label', NoraI18n.t("Открыть плеер: ") + track.title);
    const progress = Number.isFinite(audio.duration) && audio.duration > 0
      ? Math.min(1, Math.max(0, audio.currentTime / audio.duration)) : 0;
    miniProgress.value = progress;
    mini.style.setProperty('--mini-progress', String(progress));
  }

  function paint(state) {
    const { audio, loading } = state;
    const playing = active === state && !audio.paused && !audio.ended;
    const duration = Number.isFinite(audio.duration) ? audio.duration : 0;
    const current = audio.currentTime || 0;
    for (const element of matchingRows(state)) {
      const seek = element.querySelector('[data-track-seek]');
      seek.value = duration ? current / duration : 0;
      seek.disabled = !duration;
      seek.style.setProperty('--track-progress', (Number(seek.value) * 100) + '%');
      seek.setAttribute('aria-valuetext', clock(current));
      const time = element.querySelector('[data-track-time]');
      if (time.textContent !== clock(current)) time.textContent = clock(current);
      const total = element.querySelector('[data-track-duration]');
      if (duration && total.textContent !== clock(duration)) total.textContent = clock(duration);
      element.dataset.ready = String(Boolean(duration && !loading && active === state));
      element.dataset.playing = String(playing);
      element.dataset.loading = String(loading);
      const play = element.querySelector('[data-track-toggle]');
      play.disabled = loading;
      play.setAttribute('aria-label', (loading ? NoraI18n.t("Загружаем трек") : playing ? NoraI18n.t("Поставить на паузу") : NoraI18n.t("Включить трек")) + ': ' + state.track.title);
    }
    state.element = currentRow(state);
    NoraProfileWaves.sync(state.element, playing && !loading, state);
    if (active === state && !loading) void prepareMusicEnvelope(state);
    paintMini();
  }

  function waitMediaEvent(target, name, signal, action, timeout = 5000) {
    return new Promise((resolve, reject) => {
      let timer;
      const finish = error => {
        clearTimeout(timer);
        target.removeEventListener(name, done);
        target.removeEventListener('error', fail);
        target.removeEventListener('abort', fail);
        signal.removeEventListener('abort', fail);
        error ? reject(error) : resolve();
      };
      const done = () => finish();
      const fail = () => finish(Error('Media stream interrupted'));
      if (signal.aborted) { fail(); return; }
      target.addEventListener(name, done, {once:true});
      target.addEventListener('error', fail, {once:true});
      target.addEventListener('abort', fail, {once:true});
      signal.addEventListener('abort', fail, {once:true});
      timer = setTimeout(fail, timeout);
      try { action(); } catch (error) { finish(error); }
    });
  }

  function installBlob(state, blob) {
    const previous = state.url;
    state.blob = blob;
    state.url = URL.createObjectURL(blob);
    state.audio.src = state.url;
    if (previous) URL.revokeObjectURL(previous);
  }

  async function loadTrack(state) {
    const signal = state.controller.signal;
    const headers = {Authorization: 'tma ' + auth};
    let blob = cachedTrack(state.src);
    if (blob) {
      // A cached file must never bypass profile privacy, bans, or revision checks.
      const check = await fetch(state.src + '&check=1', {headers, signal, cache:'no-store'});
      if (!check.ok) { removeCachedTrack(state.src); throw Error('Track access changed'); }
      if (active !== state) return;
      installBlob(state, blob);
      state.loading = false; paint(state);
      await toggleActive(state);
      return;
    }

    const response = await fetch(state.src, {headers, signal, cache:'no-store'});
    if (!response.ok) throw Error('Track unavailable');
    const mime = (response.headers.get('Content-Type') || '').split(';')[0].trim();
    // Only enable MSE for supported MP3 streams. Ordinary M4A files are not
    // necessarily fragmented; native blob playback is the compatibility path.
    const Media = [window.ManagedMediaSource, window.MediaSource].find(
      candidate => candidate?.isTypeSupported?.(mime));
    if (mime !== 'audio/mpeg' || !Media || !response.body?.getReader) {
      blob = await response.blob();
      if (active !== state) return;
      rememberTrack(state.src, blob); installBlob(state, blob);
      state.loading = false; paint(state);
      await toggleActive(state);
      return;
    }

    const reader = response.body.getReader(), chunks = [];
    let media, buffer, started = false, total = 0;
    state.progressive = true;
    try {
      media = new Media();
      state.audio.disableRemotePlayback = true;
      state.url = URL.createObjectURL(media);
      await waitMediaEvent(media, 'sourceopen', signal, () => { state.audio.src = state.url; }, 2000);
      buffer = media.addSourceBuffer(mime);
    } catch { state.progressiveFailed = true; }

    try {
      while (true) {
        const {done, value} = await reader.read();
        if (active !== state || signal.aborted) return;
        if (done) break;
        total += value.byteLength;
        if (total > 20 * 1024 * 1024) throw Error('Track too large');
        chunks.push(value);
        if (!state.progressiveFailed) {
          try {
            await waitMediaEvent(buffer, 'updateend', signal, () => buffer.appendBuffer(value));
            if (active !== state) return;
            if (!started) {
              started = true;
              state.loading = false; paint(state);
              // play() may wait for more media; never block the download on it.
              void toggleActive(state);
            }
          } catch { state.progressiveFailed = true; }
        }
      }
    } finally {
      if (signal.aborted || active !== state) {
        try { await reader.cancel(); } catch {}
      }
      reader.releaseLock();
    }
    if (active !== state) return;
    blob = new Blob(chunks, {type:mime});
    if (!blob.size) throw Error('Empty track');
    rememberTrack(state.src, blob);
    if (!state.progressiveFailed) {
      try { if (media.readyState === 'open') media.endOfStream(); }
      catch { state.progressiveFailed = true; }
    }
    if (state.progressiveFailed || !started) {
      const position = state.audio.currentTime || 0;
      const resume = !started || state.wantsPlayback;
      state.audio.pause();
      installBlob(state, blob);
      if (position) state.audio.addEventListener('loadedmetadata', () => {
        if (active === state) state.audio.currentTime = Math.min(position, state.audio.duration || position);
      }, {once:true});
      state.progressive = false;
      state.loading = false; paint(state);
      if (resume) await toggleActive(state);
    } else {
      // The same downloaded bytes power the existing offline beat analysis.
      state.blob = blob;
      state.progressive = false;
      paint(state);
    }
  }

  function stop() {
    const state = active;
    if (!state) return;
    active = null;
    void api('music-library/playing', {...trackReference(state), playing:false}).catch(() => {});
    state.controller.abort();
    state.blob=null;state.envelope=null;state.beats=null;state.hits=null;state.hitOrdinals=null;
    state.audio.pause();
    state.audio.removeAttribute('src');
    state.audio.load();
    state.loading = false;
    paint(state);
    if (state.url) URL.revokeObjectURL(state.url);
  }

  async function toggleActive(state) {
    if (!state || active !== state || state.loading) return;
    if (!state.audio.paused) {
      state.wantsPlayback = false;
      state.audio.pause();
      return;
    }
    state.wantsPlayback = true;
    const source = state.url;
    try {
      await state.audio.play();
    } catch (error) {
      if (active !== state || state.url !== source) return;
      if (error.name === 'NotAllowedError') toast(NoraI18n.t("Нажми «Включить трек» ещё раз"));
      else if (state.progressive) state.progressiveFailed = true;
      else {
        stop();
        toast(NoraI18n.t("Не удалось воспроизвести трек"));
      }
    }
  }

  function trackReference(state) {
    const [source, revision] = state.src.split('?v=');
    return {source, revision: decodeURIComponent(revision || '')};
  }

  function paintNowSaved(state) {
    const panel = $('#nora-now-playing');
    if (!panel || panel.dataset.trackSrc !== state.src) return;
    const button = panel.querySelector('[data-now-save]');
    const profile = panel.querySelector('[data-now-profile]');
    button.dataset.saved = String(state.saved === true);
    button.disabled = Boolean(state.savePending) || state.saved == null;
    button.setAttribute('aria-pressed', String(state.saved === true));
    button.setAttribute('aria-label', state.saved ? NoraI18n.t("Убрать из лайков") : NoraI18n.t("Поставить лайк треку"));
    profile.dataset.saved = String(state.inProfile === true);
    profile.disabled = Boolean(state.savePending) || state.inProfile == null || state.inProfile === true;
    profile.setAttribute('aria-pressed', String(state.inProfile === true));
    profile.setAttribute('aria-label', state.inProfile ? NoraI18n.t("Трек уже в профиле") : NoraI18n.t("Добавить трек в профиль"));
  }

  async function loadNowSaved(state) {
    const request = state.saveStatusRequest = (state.saveStatusRequest || 0) + 1;
    try {
      const result = await api('music-library/current?' + new URLSearchParams(trackReference(state)));
      if (active !== state || state.savePending || request !== state.saveStatusRequest) return;
      state.saved = result.saved === true;
      state.inProfile = result.in_profile === true;
      paintNowSaved(state);
    } catch (error) {
      if (active === state && !state.savePending && request === state.saveStatusRequest) {
        toast(error.message);
        paintNowSaved(state);
      }
    }
  }

  async function addNowTrack(action = 'like') {
    const state = active;
    if (!state || state.savePending || state.saved == null || state.inProfile == null ||
        (action === 'profile' && state.inProfile)) return;
    state.savePending = true;
    state.saveStatusRequest = (state.saveStatusRequest || 0) + 1;
    paintNowSaved(state);
    try {
      const result = await api('music-library/current', {
        ...trackReference(state), action, ...(action === 'like' ? {saved: !state.saved} : {})
      });
      if (active === state) {
        state.saved = result.saved === true;
        state.inProfile = result.in_profile === true;
      }
      for (const item of document.querySelectorAll('[data-track-save]')) {
        if (item.dataset.trackId === result.id) paintSaved(item, result.saved);
      }
      if (typeof data !== 'undefined' && data) {
        if (result.profile_track) {
          data.profile_track = result.profile_track;
          const identity = document.querySelector('#app .lk-identity');
          if (identity) {
            const old = identity.querySelector(':scope > .profile-track');
            const markup = html(result.profile_track, '/api/profile/track');
            if (old) old.outerHTML = markup;
            else identity.querySelector(':scope > .profile-library-open')?.insertAdjacentHTML('beforebegin', markup);
          }
        } else if (data.profile_track?.id === result.id) {
          data.profile_track.saved = result.saved;
        }
      }
      toast(action === 'profile' ? NoraI18n.t("Трек добавлен в профиль") : result.saved ? NoraI18n.t("Добавлено в Мои треки") : NoraI18n.t("Убрано из лайков"));
      window.Telegram?.WebApp?.HapticFeedback?.notificationOccurred('success');
    } catch (error) {
      toast(error.message);
    } finally {
      state.savePending = false;
      if (active === state) paintNowSaved(state);
    }
  }

  function openNowPlaying() {
    const state = active;
    if (!state) return;
    const dialog = $('#sheet'), library = dialog.querySelector('#music-library-profile');
    if (dialog.open && library) {
      playerReturn = {panel:library, libraryReturn, scrollTop:$('#sheet-content').scrollTop};
    }
    libraryReturn = null;
    const svg = (path, cls='') => '<svg class="' + cls + '" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="' + path + '"/></svg>';
    sheet('<section id="nora-now-playing" aria-label="' + NoraI18n.html("Музыкальный плеер") + '" tabindex="-1" data-track-src="' + esc(state.src) + '">' +
      ("<p class=\"nora-now-playing-label\">" + NoraI18n.html("Сейчас играет") + "</p>") +
      '<div class="nora-now-playing-art" aria-hidden="true">' + coverImage(state.track, 'music-full-cover') + '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.35" stroke-linecap="round" stroke-linejoin="round"><path d="M9 18V5l12-2v13M9 9l12-2"/><ellipse cx="6" cy="18" rx="3" ry="2"/><ellipse cx="18" cy="16" rx="3" ry="2"/></svg></div>' +
      '<div class="nora-now-meta"><div class="nora-now-copy"><h2>' + esc(state.track.title) + '</h2><p>' + esc(state.track.artist) + '</p></div>' +
      ("<button type=\"button\" class=\"nora-now-save\" data-now-save data-saved=\"false\" aria-label=\"" + NoraI18n.html("Поставить лайк треку") + "\" aria-pressed=\"false\" disabled>") +
      svg('M20.8 8.5c0 4.1-8.8 9.7-8.8 9.7S3.2 12.6 3.2 8.5a4.7 4.7 0 0 1 8.8-2.3 4.7 4.7 0 0 1 8.8 2.3Z','nora-now-heart') + svg('m5 12 4 4L19 6','nora-now-check') + '</button></div>' +
      ("<div class=\"nora-now-timeline\"><input type=\"range\" min=\"0\" max=\"1\" step=\"0.001\" value=\"0\" data-track-seek aria-label=\"" + NoraI18n.html("Позиция в треке") + "\" disabled><div class=\"nora-now-times\"><span data-track-time>0:00</span><span data-track-duration>") + clock(state.track.duration) + '</span></div></div>' +
      ("<div class=\"nora-now-controls\"><button type=\"button\" class=\"nora-now-secondary nora-now-profile\" data-now-profile data-saved=\"false\" aria-label=\"" + NoraI18n.html("Добавить трек в профиль") + "\" aria-pressed=\"false\" disabled>") + svg('M12 5v14M5 12h14','nora-now-profile-plus') + svg('m5 12 4 4L19 6','nora-now-profile-check') + '</button>' +
      ("<button type=\"button\" class=\"nora-now-play\" data-track-toggle aria-label=\"" + NoraI18n.html("Воспроизвести") + "\"><svg class=\"nora-now-play-icon\" viewBox=\"0 0 24 24\" fill=\"currentColor\" aria-hidden=\"true\"><path d=\"M8 4.5v15l12-7.5z\"/></svg><svg class=\"nora-now-pause-icon\" viewBox=\"0 0 24 24\" fill=\"currentColor\" aria-hidden=\"true\"><rect x=\"6\" y=\"4.5\" width=\"4\" height=\"15\" rx=\"1\"/><rect x=\"14\" y=\"4.5\" width=\"4\" height=\"15\" rx=\"1\"/></svg></button>") +
      ("<button type=\"button\" class=\"nora-now-secondary nora-mini-share\" data-now-share aria-label=\"" + NoraI18n.html("Поделиться треком в чате") + "\">") + svg('m22 2-7 20-4-9-9-4 20-7ZM22 2 11 13','nora-mini-send') + svg('m5 12 4 4L19 6','nora-mini-sent') + '</button></div><div class="music-queue-controls"><button type="button" data-queue-prev aria-label="' + NoraI18n.html("Предыдущий трек") + '">⏮</button><button type="button" data-queue-shuffle aria-pressed="' + shuffle + '" aria-label="' + NoraI18n.html("Перемешать") + '">⤨</button><button type="button" data-queue-repeat aria-pressed="' + repeat + '" aria-label="' + NoraI18n.html("Повтор трека") + '">↻</button><button type="button" data-queue-next aria-label="' + NoraI18n.html("Следующий трек") + '">⏭</button></div></section>');
    $('#sheet').scrollTop = 0;
    $('#sheet-content').scrollTop = 0;
    $('#nora-now-playing')?.focus({preventScroll:true});
    window.NoraShop?.syncBack();
    paint(state);
    paintNowSaved(state);
    void loadNowSaved(state);
  }

  async function shareCurrent() {
    const state = active;
    if (!state || state.loading || sharePending || Date.now() < shareUntil) return;
    sharePending = true;
    paintMini();
    try {
      const [source, revision] = state.src.split('?v=');
      const result = await api('community/music/share', {source, revision: decodeURIComponent(revision || '')});
      if (!result.sent) throw Error(result.message || NoraI18n.t("Не удалось отправить трек"));
      sharedSource = state.src;
      shareUntil = Date.now() + Math.max(1, Number(result.retry_after) || 300) * 1000;
      clearTimeout(shareTimer);
      shareTimer = setTimeout(paintMini, Math.max(0, shareUntil - Date.now()));
      toast(result.message || NoraI18n.t("Трек отправлен в чат 🎧"));
      window.Telegram?.WebApp?.HapticFeedback?.notificationOccurred('success');
    } catch (error) {
      toast(error.message);
    } finally {
      sharePending = false;
      paintMini();
    }
  }

  miniShare.addEventListener('click', () => void shareCurrent());
  miniOpen.addEventListener('click', openNowPlaying);
  miniToggle.addEventListener('click', () => void toggleActive(active));
  document.addEventListener('click', event => {
    if (event.target.closest('[data-queue-prev]')) { void stepQueue(-1); return; }
    if (event.target.closest('[data-queue-next]')) { void stepQueue(1); return; }
    const shuffleButton = event.target.closest('[data-queue-shuffle]');
    if (shuffleButton) { shuffle = !shuffle; shuffleButton.setAttribute('aria-pressed',String(shuffle)); return; }
    const repeatButton = event.target.closest('[data-queue-repeat]');
    if (repeatButton) { repeat = !repeat; repeatButton.setAttribute('aria-pressed',String(repeat)); return; }
    if (event.target.closest('[data-now-save]')) { void addNowTrack(); return; }
    if (event.target.closest('[data-now-profile]')) { void addNowTrack('profile'); return; }
    if (event.target.closest('[data-now-share]')) { void shareCurrent(); return; }
    if (event.target.closest('[data-mini-stop]')) {
      ++playIntent; queue=[]; queueIndex=-1; stop();
      if ($('#nora-now-playing')) $('#sheet').close();
    }
  });

  function queueItem(element) {
    return {src:element.dataset.trackSrc, track:{id:element.dataset.trackId,title:element.dataset.trackTitle,
      artist:element.dataset.trackArtist,duration:Number(element.dataset.trackLength)||0,cover:element.dataset.trackCover}};
  }

  async function startTrack(item) {
    if (!item) return;
    if (!item.src && item.wave && item.catalogId) {
      const intent = ++playIntent;
      try {
        const response = await api('music-library/play', {id:item.catalogId,wave:true});
        if (intent !== playIntent) return;
        item.src = response.source + '?v=' + encodeURIComponent(response.track.revision);
        item.track = response.track;
        for (const row of document.querySelectorAll('.music-catalog-row')) {
          if (row.querySelector('[data-music-play]')?.dataset.musicPlay === item.catalogId) row.dataset.playSource = item.src;
        }
      } catch (error) { if (intent === playIntent) toast(error.message); return; }
    }
    if (active?.src === item.src) { await toggleActive(active); return; }
    const full = $('#sheet').open && Boolean($('#nora-now-playing'));
    stop();
    const audio = new Audio();
    active = {audio, element:null, src:item.src, controller:new AbortController(), loading:true, track:item.track};
    const state = active;
    let listened = 0, last = 0, lastPresence = 0;
    const presence = (playing) => {
      lastPresence = Date.now();
      void api('music-library/playing', {...trackReference(state), playing}).catch(() => {});
    };
    for (const name of ['loadedmetadata','timeupdate','play','playing','pause','ended']) {
      audio.addEventListener(name, () => {
        if (active !== state) return;
        if (name === 'playing') presence(true);
        if (name === 'pause' || name === 'ended') presence(false);
        if (name === 'timeupdate') {
          if (!audio.paused && Date.now() - lastPresence >= 15000) presence(true);
          const delta = audio.currentTime - last;
          if (!audio.paused && delta > 0 && delta < 2) listened += delta;
          last = audio.currentTime;
          const threshold = Math.min(15, (audio.duration || 30) * .65);
          if (!state.historySent && listened >= threshold) {
            state.historySent = true;
            void api('music-library/listened', trackReference(state)).catch(() => {state.historySent=false;});
          }
        }
        paint(state);
        if (name === 'ended') {
          if (repeat) { audio.currentTime=0; void toggleActive(state); }
          else void stepQueue(1);
        }
      });
    }
    audio.addEventListener('error', () => {
      if (active !== state) return;
      if (state.progressive) { state.progressiveFailed = true; return; }
      stop(); toast(NoraI18n.t("Не удалось воспроизвести трек"));
    });
    if (full) openNowPlaying();
    paint(state);
    try { await loadTrack(state); }
    catch { if (active === state) { stop(); toast(NoraI18n.t("Трек сейчас недоступен")); } }
  }

  async function stepQueue(direction) {
    if (!queue.length) return;
    let next = queueIndex + direction;
    if (shuffle && direction > 0 && queue.length > 1) {
      next = (queueIndex + 1 + Math.floor(Math.random() * (queue.length-1))) % queue.length;
    }
    if (next >= queue.length && direction > 0 && queue[queueIndex]?.wave) {
      const intent = ++playIntent;
      try {
        const response = await api('music-library/wave');
        if (intent !== playIntent || !response.tracks.length) return;
        const previous = new Set(queue.map(item=>item.catalogId));
        const fresh = response.tracks.filter(track=>!previous.has(track.id));
        queue = (fresh.length ? fresh : response.tracks).map(track=>({wave:true,catalogId:track.id,track}));
        next = 0;
      } catch (error) { if (intent === playIntent) toast(error.message); return; }
    }
    if (next < 0 || next >= queue.length) return;
    queueIndex = next;
    await startTrack(queue[next]);
  }

  document.addEventListener('click', async event => {
    const button = event.target.closest('[data-track-toggle]');
    if (!button) return;
    const element = button.closest('[data-track-src]');
    if (!element) return;
    if (active?.src === element.dataset.trackSrc) { await toggleActive(active); return; }
    ++playIntent;
    const group = element.closest('.profile-library-list,.music-social-list');
    queue = group ? Array.from(group.querySelectorAll('[data-track-src]')).filter(row=>!row.hidden).map(queueItem) : [queueItem(element)];
    queueIndex = queue.findIndex(item => item.src === element.dataset.trackSrc);
    await startTrack(queue[queueIndex] || queueItem(element));
  });

  document.addEventListener('input', event => {
    const seek = event.target;
    if (!seek.matches('[data-track-seek]') || !active || active.src !== seek.closest('[data-track-src]')?.dataset.trackSrc) return;
    const { audio } = active;
    if (Number.isFinite(audio.duration)) {
      audio.currentTime = Number(seek.value) * audio.duration;
      paint(active);
    }
  });

  // Reattach only the UI after route changes, refreshes and dialog dismissal.
  // In-memory audio is cleared when the authenticated navigation is removed.
  function rebind() {
    if (!document.querySelector('#nav .nav-drop')) { stop(); clearMusicCache(); return; }
    syncMiniHost();
    if (!active) return;
    const replacement = currentRow(active);
    if (active.element !== replacement) {
      active.element = replacement;
      paint(active);
    }
  }
  const observer = new MutationObserver(rebind);
  for (const id of ['app', 'sheet-content', 'nav']) {
    observer.observe(document.getElementById(id), { childList: true, subtree: true });
  }
  observer.observe($('#sheet'), { attributes: true, attributeFilter: ['open'] });
  document.addEventListener('close', rebind, true);
  window.addEventListener('pagehide', () => { stop(); clearMusicCache(); });
  return { html, libraryButton, back, closeNowPlaying };
})();
