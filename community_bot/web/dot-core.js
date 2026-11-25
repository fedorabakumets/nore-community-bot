"use strict";
globalThis.NoraDotCore=(()=>{
  const W=360,H=500,X=87,R=10,PIPE=46,STEP=1/120;
  const clamp=(n,a,b)=>Math.max(a,Math.min(b,n));
  const lerp=(a,b,t)=>a+(b-a)*t;
  const STAGES=[
    {name:"FLOW",start:0,color:[174,164,194],gap:180,shift:66,description:"Поймай ритм"},
    {name:"PULSE",start:10,color:[103,151,255],gap:166,shift:85,description:"Темп растёт"},
    {name:"SHIFT",start:25,color:[177,118,255],gap:158,shift:76,description:"Препятствия движутся"},
    {name:"PRESSURE",start:45,color:[250,181,100],gap:220,shift:54,description:"Тап меняет гравитацию · мягкий режим"},
    {name:"CHAOS",start:70,color:[255,83,112],gap:138,shift:75,description:"Скорость пульсирует"},
    {name:"VOID",start:100,color:[230,215,255],gap:130,shift:79,description:"Предела больше нет"},
    {name:"PARADOX",start:130,color:[102,224,239],gap:178,shift:108,description:"Тап меняет гравитацию"}
  ];
  const PARADOX_START=130, INVERT_GRAVITY=670, SOFT_GRAVITY=780;
  const softMode=n=>n>=45&&n<70;
  const gravityMode=n=>softMode(n)||n>=PARADOX_START;
  const acceleration=n=>softMode(n)?SOFT_GRAVITY:INVERT_GRAVITY;
  const stageAt=n=>n>=PARADOX_START?6:n>=100?5:n>=70?4:n>=45?3:n>=25?2:n>=10?1:0;
  const speedAt=(t,passed=0)=>{
    const base=Math.min(365,125+t*3.1);
    const pulse=clamp((passed-70)/12,0,1)*(.5+.5*Math.sin(t*2.1));
    const normal=base*(1-.12*pulse);
    if(softMode(passed))return Math.min(245,normal);
    if(passed>=70&&passed<82){
      const progress=clamp((passed-70)/12,0,1);
      return lerp(Math.min(245,normal),normal,progress);
    }
    return Math.min(365,normal);
  };
  const widths={static:46,zigzag:46,lift:46,iris:46,tunnel:90,double:82,phantom:46,hybrid:46};
  const typeNames={static:"",zigzag:"ZIG",lift:"SHIFT",iris:"IRIS",tunnel:"TUNNEL",double:"DOUBLE",phantom:"GHOST",hybrid:"SHIFT · IRIS"};
  function gateShape(g,t){
    const shift=g.amp*Math.sin(t*g.rate+g.phase),gap=g.gap-g.squeeze*(.5+.5*Math.sin(t*g.rate*.83+g.phase+1));
    return {center:g.center+shift,gap};
  }
  function segments(g,t){
    const {center,gap}=gateShape(g,t);
    return g.type==="double"?[{offset:0,width:30,center,gap},{offset:52,width:30,center:center+g.second,gap}]:[{offset:0,width:g.width,center,gap}];
  }
  function collision(y,d,g,t){
    for(const p of segments(g,t)){
      const x=g.x-d+p.offset,top=p.center-p.gap/2,bottom=p.center+p.gap/2;
      const dx=X-clamp(X,x,x+p.width);
      if(dx>=R)continue;
      const dy1=y-clamp(y,0,top),dy2=y-clamp(y,bottom,H);
      if(dx*dx+dy1*dy1<R*R||dx*dx+dy2*dy2<R*R)return true;
    }
    return false;
  }
  function advance(s,dt,passed){
    s.time+=dt;s.distance+=speedAt(s.time,passed)*dt;
    const limit=softMode(passed)?340:440;
    s.vy=gravityMode(passed)?clamp(s.vy+(s.gravity||1)*acceleration(passed)*dt,-limit,limit):Math.min(440,s.vy+670*dt);
    s.y+=s.vy*dt;
  }
  function enterParadox(s){
    // Deterministic handoff toward the center of the field.
    s.vy=clamp(s.vy,-160,160);
    s.gravity=s.y>H/2?-1:s.y<H/2?1:s.vy>0?-1:1;
  }
  function stageHandoff(s,passed){
    if(passed===45||passed===PARADOX_START){
      enterParadox(s);
      if(passed===PARADOX_START)s.vy=s.gravity*clamp(Math.abs(s.vy),160,200);
    }
    else if(passed===70){s.gravity=0;s.vy=clamp(s.vy,-180,160);}
  }
  function flipGravity(s,passed){
    s.gravity=-s.gravity;
    // Both gravity stages respond immediately; PARADOX retains its faster pace.
    if(softMode(passed))s.vy=s.gravity*clamp(Math.abs(s.vy)*.55,145,190);
    else if(passed>=PARADOX_START)s.vy=s.gravity*clamp(Math.abs(s.vy)*.55,180,235);
  }
  function paradoxPilot(s,target,deadband,passed){
    const stopping=s.y+s.vy*.07;
    const desired=stopping>target+deadband?-1:stopping<target-deadband?1:s.gravity;
    if(desired!==s.gravity&&s.time-(s.lastFlip??-1)>=.05){flipGravity(s,passed);s.lastFlip=s.time;}
  }
  // A constructive witness, not a promise that every player position is recoverable.
  // Every accepted gate has an explicit collision-free continuation from the previous witness.
  function witnessFor(start,g,passed){
    const policies=[[15,-12,0],[8,-24,0],[23,0,0],[12,-45,.12],[20,-20,.20],[5,-10,.12],[30,25,.1],[15,-65,.2],[24,-15,-.10],[12,0,-.12]];
    for(const [threshold,minVy,look] of policies){
      const s={...start};let count=0;
      stageHandoff(s,passed);
      while(g.x+g.width>=s.distance+X-R&&count++<1200){
        const aim=gateShape(g,s.time+look),offset=g.type==="double"&&g.x-s.distance<X-26?g.second:0;
        const target=aim.center+offset-4;
        if(gravityMode(passed))paradoxPilot(s,target,Math.max(4,threshold*.45),passed);
        else if(s.y>target+threshold&&s.vy>=minVy){s.vy=-254;s.lastFlip=s.time;}
        advance(s,STEP,passed);
        if(s.y<=R||s.y>=H-R||collision(s.y,s.distance,g,s.time))break;
        if(g.x+g.width<s.distance+X-R)return s;
      }
    }
    return null;
  }
  function seededRandom(seed){
    let n=seed>>>0;return ()=>{n=(Math.imul(n,1664525)+1013904223)>>>0;return n/4294967296;};
  }
  // Stable independent hash: variation never consumes the gate RNG or changes physics.
  function crumbHash(g){
    let n=(Math.imul(g.index,0x9e3779b1)^Math.floor(g.phase*1000000)^Math.floor(g.center*4096))>>>0;
    n=Math.imul(n^(n>>>16),0x85ebca6b)>>>0;return (n^(n>>>13))>>>0;
  }
  function crumbPosition(g,t,rules=2){
    const shape=gateShape(g,t),hash=crumbHash(g);
    if(rules!==2)return {y:shape.center,kind:hash>>>2&3};
    // Four slots within the shared opening, including DOUBLE gates.
    const half=(shape.gap-Math.abs(g.second))/2;
    return {y:shape.center+g.second/2+[-.54,-.18,.18,.54][hash&3]*half,kind:hash>>>2&3};
  }
  function createRun(random=Math.random,rules=2){
    const r={y:H*.48,py:H*.48,vy:0,time:0,previousTime:0,distance:0,previousDistance:0,cookies:0,passed:0,gates:[],rules,dead:false,stage:0,ticks:0,generated:0,verified:0,fallbacks:0};
    let witness={y:r.y,vy:-254,time:0,distance:0},previous=null;
    function typeFor(index,stage){
      const since=index-1-STAGES[stage].start;
      if(stage===0)return "static";
      if(stage===1)return since%3===1?"zigzag":"static";
      if(stage===2)return since===0||since%3===1?"lift":since%3===2?"zigzag":"static";
      if(stage===3)return since<4?"static":["static","zigzag","static","tunnel","static","zigzag"][since%6];
      if(stage===6)return since<4?"static":["zigzag","static","tunnel","zigzag","static","zigzag"][since%6];
      if(stage===4)return ["lift","iris","static","double","phantom","tunnel","zigzag","static","hybrid"][since%9];
      return ["hybrid","double","static","phantom","lift","tunnel","iris","zigzag","static","hybrid"][since%10];
    }
    function add(){
      const index=r.generated+1,stage=stageAt(index-1),level=STAGES[stage],type=typeFor(index,stage);
      const baseSpeed=speedAt(witness.time,index-1),priorCenter=previous?.center??H*.48;
      const spacingSpeed=stage===4&&index<=82?Math.max(baseSpeed,Math.min(365,125+witness.time*3.1)*.90):baseSpeed;
      const easy=index%7===0&&index-1!==level.start;
      const desired=easy?"static":type;
      let accepted=null,nextWitness=null;
      for(let attempt=0;attempt<16;attempt++){
        const kind=attempt<9?desired:"static",width=widths[kind];
        const amp=kind==="lift"||kind==="hybrid"?Math.min(38,20+stage*3):0;
        const squeeze=kind==="iris"||kind==="hybrid"?Math.min(34,15+stage*3):0;
        const second=kind==="double"?(random()<.5?-1:1)*(13+stage*2):0;
        const gap=Math.max(130,level.gap+(stage===3&&index<=49?28:0)+(stage===6&&index<=PARADOX_START+4?40:0)+(easy?18:0)+(attempt>=9?28:0)+(kind==="tunnel"?14:0));
        const shift=kind==="zigzag"?level.shift*1.35:level.shift;
        const margin=gap/2+amp+Math.abs(second)+25;
        const direction=random()<.5?-1:1;
        const center=clamp(attempt>=9?witness.y:priorCenter+(kind==="zigzag"?direction*(shift*.55+random()*shift*.45):(random()-.5)*shift*2),margin,H-margin);
        const interval=Math.max(170,spacingSpeed*(stage===3?(index===46?2.1:1.40):stage===4&&index===71?1.65:stage===6?(index===PARADOX_START+1?2.1:index<=PARADOX_START+4?1.55:1.30):stage>=4?1.02:1.16))+(previous?Math.max(0,previous.width-46):0)+(easy?55:0)+(attempt>=9?50:0);
        const x=previous?previous.x+interval:W-30;
        const g={index,stage,type:kind,x,width,center,gap,amp,squeeze,second,rate:.85+stage*.14,phase:random()*Math.PI*2,collected:false,passed:false};
        const path=witnessFor(witness,g,index-1);
        if(path){accepted=g;nextWitness=path;break;}
      }
      if(!accepted){
        // Emergency corridor: generous enough for a bounded feedback pilot to re-center.
        // Still verified using the same physical model before being placed.
        for(const center of [H/2,clamp(witness.y,145,H-145),priorCenter]){
          const g={index,stage,type:"static",x:previous?previous.x+Math.max(320,baseSpeed*1.7)+previous.width:W+60,width:46,center:clamp(center,145,H-145),gap:240,amp:0,squeeze:0,second:0,rate:0,phase:0,collected:false,passed:false};
          const path=witnessFor(witness,g,index-1);if(path){accepted=g;nextWitness=path;r.fallbacks++;break;}
        }
      }
      if(!accepted)return false;
      r.gates.push(accepted);r.generated++;r.verified++;witness=nextWitness;previous=accepted;return true;
    }
    add();
    r.flap=()=>{if(!r.dead){if(gravityMode(r.passed))flipGravity(r,r.passed);else r.vy=-254;}};
    r.step=(dt,emit=()=>{})=>{
      if(r.dead)return;
      r.ticks++;r.py=r.y;r.previousDistance=r.distance;r.previousTime=r.time;
      advance(r,dt,r.passed);
      function die(){r.dead=true;emit("crash");}
      if(r.y-R<=0||r.y+R>=H){r.y=clamp(r.y,R,H-R);die();return;}
      for(const g of r.gates){
        const x=g.x-r.distance,crumb=crumbPosition(g,r.time,rules);
        if(collision(r.y,r.distance,g,r.time)){die();return;}
        if(!g.collected&&Math.hypot(X-x-g.width/2,r.y-crumb.y)<R+17){
          g.collected=true;r.cookies++;emit("cookie");
        }
        if(!g.passed&&x+g.width<X-R){
          g.passed=true;r.passed++;emit("pass");
          const stage=stageAt(r.passed);if(stage!==r.stage){r.stage=stage;stageHandoff(r,r.passed);emit("stage");}
        }
      }
      const tail=r.gates.at(-1);
      if(!tail||tail.x-r.distance<W-145)add();
      while(r.gates.length>1&&r.gates[0].x+r.gates[0].width<r.distance-30)r.gates.shift();
    };
    r.revive=()=>{
      if(!r.dead||r.revived)return false;
      // Reposition in the nearest unpassed corridor, preserving progress and collected coins.
      const next=r.gates.find(g=>!g.passed);
      const shape=next?gateShape(next,r.time):{center:H/2};
      r.y=clamp(shape.center,R+18,H-R-18);r.py=r.y;r.vy=0;
      r.previousTime=r.time;r.previousDistance=r.distance;
      if(gravityMode(r.passed))r.gravity=r.y>H/2?-1:1;
      r.dead=false;r.revived=true;return true;
    };
    r.generate=add;
    return r;
  }


  function replay(seed,ticks,flaps,reviveTick=null,rules=1){
    if(reviveTick!==null&&(!Number.isInteger(reviveTick)||reviveTick<=0||reviveTick>=ticks))throw Error("invalid revive");
    if(!Number.isInteger(seed)||seed<0||seed>4294967295||!Number.isInteger(ticks)||ticks<1||ticks>432000||!Array.isArray(flaps)||flaps.length>ticks||flaps[0]!==0)throw Error("invalid flight");
    let previous=-1;for(const tick of flaps){if(!Number.isInteger(tick)||tick<=previous||tick>=ticks)throw Error("invalid input");previous=tick;}
    const r=createRun(seededRandom(seed),rules);let i=0;
    for(let tick=0;tick<ticks;tick++){
      if(tick===reviveTick&&!r.revive())throw Error("revive without crash");
      if(r.dead)throw Error("flight already ended");
      if(flaps[i]===tick){r.flap();i++;}
      r.step(STEP);
    }
    if(!r.dead||i!==flaps.length)throw Error("flight not finished");
    return {cookies:r.cookies,passed:r.passed,ticks:r.ticks};
  }
  return {W,H,X,R,PIPE,STEP,PARADOX_START,gravityMode,softMode,clamp,lerp,STAGES,stageAt,speedAt,typeNames,gateShape,crumbPosition,segments,witnessFor,createRun,seededRandom,replay};
})();
