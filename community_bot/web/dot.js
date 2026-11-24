"use strict";
window.NoraDot = (() => {
  const W = 360, H = 500, X = 88, R = 11, PIPE = 46;
  let root, canvas, ctx, hud, overlay, button, abort, raf = 0, last = 0;
  let y, vy, time, distance, pipes, trail, sparks, cookies, passed, mode, paused;
  const speed = () => Math.min(370, 118 + time * 3.2);
  const circle = (x,y,r,color) => { ctx.fillStyle=color; ctx.beginPath(); ctx.arc(x,y,r,0,Math.PI*2); ctx.fill(); };
  function gate(x, previous = H/2) {
    const gap = Math.max(125, 174 - time * .48);
    const center = Math.max(108,Math.min(H-108,previous+(Math.random()-.5)*150));
    return {x, center, gap, collected:false, passed:false};
  }
  function reset() {
    y=H*.48; vy=0; time=distance=cookies=passed=0; pipes=[gate(W+35)]; trail=[]; sparks=[];
    mode="ready"; paused=false; last=0; updateHud();
  }
  function updateHud() {
    hud.textContent = "🍪 "+cookies+"     ·     "+passed+" пройдено";
  }
  function haptic(type) { try { window.Telegram?.WebApp?.HapticFeedback?.impactOccurred(type); } catch {} }
  function flap() {
    if (mode==="over") { reset(); showOverlay(); return; }
    if (mode==="ready" || paused) { mode="play"; paused=false; last=0; showOverlay(); }
    vy=-265;
  }
  function showOverlay() {
    overlay.hidden=mode==="play"&&!paused;
    overlay.querySelector("strong").textContent=mode==="over"?"Полёт завершён":paused?"Пауза":"DOT";
    overlay.querySelector("small").textContent=mode==="over"?"Печеньки за полёт: "+cookies:paused?"Продолжи, когда будешь готов":"Касайся экрана, чтобы лететь";
    button.textContent=mode==="over"?"Ещё раз":paused?"Продолжить":"Играть";
  }
  function end() { mode="over"; haptic("medium"); showOverlay(); }
  function intersects(x0,y0,w,h) {
    const dx=X-Math.max(x0,Math.min(X,x0+w)), dy=y-Math.max(y0,Math.min(y,y0+h));
    return dx*dx+dy*dy<R*R;
  }
  function step(dt) {
    time+=dt; distance+=speed()*dt; vy+=760*dt; y+=vy*dt;
    trail.push({y,t:time}); if(trail.length>15)trail.shift();
    if(y<R||y>H-R){end();return;}
    for(const p of pipes) {
      p.x-=speed()*dt;
      const top=p.center-p.gap/2, bottom=p.center+p.gap/2;
      if(intersects(p.x,0,PIPE,top)||intersects(p.x,bottom,PIPE,H-bottom)){end();return;}
      if(!p.collected&&Math.hypot(X-(p.x+PIPE/2),y-p.center)<R+12){
        p.collected=true; cookies++; updateHud(); haptic("light");
        for(let i=0;i<9;i++){const angle=i*Math.PI*2/9;sparks.push({x:X,y,vx:Math.cos(angle)*65,vy:Math.sin(angle)*65,t:.4});}
      }
      if(!p.passed&&p.x+PIPE<X-R){p.passed=true;passed++;updateHud();}
    }
    const tail=pipes[pipes.length-1];
    if(tail.x<W-145)pipes.push(gate(tail.x+Math.max(190,speed()*1.12),tail.center));
    pipes=pipes.filter(p=>p.x+PIPE>-10);
    sparks=sparks.filter(s=>{s.x+=s.vx*dt;s.y+=s.vy*dt;s.t-=dt;return s.t>0;});
  }
  function rounded(x,y,w,h,r) {
    ctx.beginPath(); if(ctx.roundRect)ctx.roundRect(x,y,w,h,r);else ctx.rect(x,y,w,h);
  }
  function wall(x,y,w,h) {
    const g=ctx.createLinearGradient(x,y,x+w,y);g.addColorStop(0,"#38363e");g.addColorStop(.35,"#26252c");g.addColorStop(1,"#17171c");
    rounded(x,y,w,h,Math.min(10,h/2));ctx.fillStyle=g;ctx.fill();ctx.strokeStyle="#ffffff30";ctx.lineWidth=1;ctx.stroke();
  }
  function draw() {
    ctx.fillStyle="#101014";ctx.fillRect(0,0,W,H);
    for(let i=0;i<14;i++)for(let j=0;j<20;j++)circle((i*28-distance*.18%28+28)%392,j*28,1,"#ffffff12");
    for(const p of pipes) {
      const top=p.center-p.gap/2,bottom=p.center+p.gap/2;
      wall(p.x,-10,PIPE,top+10);wall(p.x,bottom,PIPE,H-bottom+10);
      if(!p.collected){const cx=p.x+PIPE/2,cy=p.center;circle(cx,cy,11,"#be8853");circle(cx-1,cy-1,9,"#e4b16f");
        for(const [dx,dy] of [[-4,-4],[4,-3],[0,3],[-5,4],[5,5]])circle(cx+dx,cy+dy,1.8,"#75452d");
      }
    }
    trail.forEach((p,i)=>{const f=(i+1)/trail.length;circle(X-(trail.length-i)*2.6,p.y,2+f*4,"rgba(255,70,94,"+(.24*f)+")");});
    ctx.save();ctx.shadowColor="#ff344d";ctx.shadowBlur=16;circle(X,y,R,"#f34c62");ctx.restore();circle(X,y,5,"#151116");
    for(const s of sparks)circle(s.x,s.y,2,"rgba(255,203,130,"+Math.min(1,s.t*2.5)+")");
  }
  function tick(now) {
    if(!root?.isConnected){unmount();return;}
    const dt=last?Math.min(.05,(now-last)/1000):0;last=now;
    if(mode==="play"&&!paused&&!document.hidden&&!document.querySelector("dialog[open]")){
      let remaining=dt;while(remaining>0&&mode==="play"){const slice=Math.min(1/120,remaining);step(slice);remaining-=slice;}
    }
    draw();raf=requestAnimationFrame(tick);
  }
  function screen() {
    return '<section id="dot-root" class="dot-game"><div class="dot-header"><button type="button" class="text-btn play-back" data-tab="games">← Игры</button><b>DOT</b><span data-dot-speed></span></div><div class="dot-hud" data-dot-hud></div><div class="dot-stage"><canvas width="360" height="500" tabindex="0" aria-label="Игровое поле DOT. Касание или пробел для прыжка."></canvas><div class="dot-overlay"><strong></strong><small></small><button type="button" class="dot-start"></button></div></div><p class="sub dot-note">Печеньки пока считаются только в этой партии.</p></section>';
  }
  function mount(next) {
    if(root===next&&raf)return;unmount();if(!next)return;
    root=next;canvas=root.querySelector("canvas");ctx=canvas.getContext("2d");hud=root.querySelector("[data-dot-hud]");overlay=root.querySelector(".dot-overlay");button=root.querySelector(".dot-start");
    abort=new AbortController();const options={signal:abort.signal};
    canvas.addEventListener("pointerdown",e=>{e.preventDefault();if(e.isPrimary)flap();},options);
    button.addEventListener("click",()=>{if(mode==="over")reset();flap();},options);
    document.addEventListener("keydown",e=>{if((e.code==="Space"||e.code==="ArrowUp")&&!e.repeat&&!document.querySelector("dialog[open]")&&!e.target.closest("button,input,textarea,select")){e.preventDefault();flap();}},options);
    document.addEventListener("visibilitychange",()=>{last=0;if(document.hidden&&mode==="play"){paused=true;showOverlay();}},options);
    reset();showOverlay();draw();raf=requestAnimationFrame(tick);
  }
  function unmount(){cancelAnimationFrame(raf);raf=0;abort?.abort();abort=null;root=null;last=0;}
  return {screen,mount,unmount};
})();
