'use strict';
window.NoraBurrowModels = (() => {
  const slots = [[-3,-3.35],[2.9,-3.35],[-3,-1.35],[3,-1.35],[-3,.7],[3,.7],[-2.9,3],[2.9,3]];
  const stall = {x:-6.9,z:2.6};
  const wood='#784a38', brass='#e5b968', dark='#342e39', mint='#8adbc5', wine='#a6455a';
  function merchant(box,solid) {
    const {x,z}=stall;
    const b=(dx,y,dz,w,h,d,c)=>box(x+dx,y,z+dz,w,h,d,c);
    for(const dx of [-1.2,1.2])for(const dz of [-.7,.7])b(dx,1.1,dz,.13,2.2,.13,wood);
    for(let i=-4;i<=4;i++)for(let j=-3;j<=3;j++){
      const col=i%2?wine:'#e8bf83';
      b(i*.32,2.69-Math.abs(j)*.13,j*.32,.324,.16,.34,col);
      if(j===3)b(i*.32,2.19,1,.32,i%2?.21:.32,.09,col);
    }
    b(0,.43,.58,2.35,.86,.47,wood);b(0,.9,.58,2.5,.12,.55,brass);
    for(let i=-4;i<=4;i++)b(i*.23,.45,.83,.18,.63,.05,i%2?'#935845':'#a7694c');
    b(0,1.04,-.16,.61,.8,.38,'#426861');b(0,1.62,-.12,.49,.5,.44,'#de9b76');
    b(0,1.9,-.14,.63,.17,.58,wine);b(.12,2,-.12,.33,.13,.39,wine);
    for(const sign of [-1,1]){
      b(sign*.13,1.66,.11,.065,.07,.04,dark);b(sign*.36,1.13,0,.16,.37,.2,'#426861');
      b(sign*.36,.98,.1,.16,.15,.18,'#de9b76');
    }
    b(0,1.51,.13,.19,.045,.04,'#925c53');b(0,1.24,.05,.25,.22,.08,brass);
    b(-.77,1.09,.62,.36,.3,.13,mint);b(.83,1.04,.63,.35,.16,.27,wine);
    solid(x,1,z,2.52,2,1.7);
  }
  function model(id,b,lit) {
    const feet=(w,d,h)=>{for(const x of [-w,w])for(const z of [-d,d])b(x,h/2,z,.11,h,.11,wood);};
    switch(id){
    case 'fern':
      b(0,.19,0,.42,.38,.38,'#b1654e');b(0,.39,0,.51,.1,.46,'#df9c71');
      for(let i=0;i<7;i++)for(let j=0;j<3;j++)b(Math.sin(i*2)*j*.1,.5+j*.09,Math.cos(i*2)*j*.1,.17,.15,.12,i%2?'#588f58':'#85af62');break;
    case 'rug':
      b(0,.019,0,1.6,.038,1.1,wine);
      for(let i=-3;i<=3;i++){b(i*.19,.043,0,.16,.012,(4-Math.abs(i))*.17,brass);for(const s of [-1,1])b(i*.22,.023,s*.58,.09,.02,.13,'#ecd7af');}break;
    case 'stool':
      feet(.22,.2,.43);b(0,.46,0,.75,.16,.66,wine);b(0,.57,0,.55,.08,.48,'#c95855');
      for(const [x,z] of [[.17,.15],[-.15,.08],[0,-.15]])b(x,.62,z,.11,.03,.1,'#f4dab2');break;
    case 'books':
      for(const x of [-.54,.54])b(x,.64,0,.1,1.28,.56,wood);
      for(let i=0;i<3;i++)b(0,.09+i*.56,0,1.18,.1,.6,brass);
      for(let j=0;j<2;j++)for(let i=0;i<5;i++){const x=-.38+i*.18,y=.32+j*.56;b(x,y,0,.14,.33+i%2*.11,.43,[wine,mint,wood][(i+j)%3]);b(x,y+.08,.22,.12,.035,.02,brass);}break;
    case 'couch':
      feet(.57,.24,.25);b(0,.35,0,1.58,.29,.78,wood);b(0,.73,-.32,1.57,.64,.2,'#854254');
      for(const x of [-.4,.4]){b(x,.53,.02,.73,.22,.59,wine);b(x,.86,-.18,.57,.34,.2,'#cb7a80');}
      for(const x of [-.8,.8])b(x,.58,0,.16,.43,.81,wood);break;
    case 'lamp':
      b(0,.08,0,.52,.16,.5,wood);b(0,.64,0,.11,1.12,.11,brass);
      b(0,1.31,0,.46,.48,.42,lit?'#ffce6d':'#756445');
      for(const s of [-.24,.24])for(const t of [-.22,.22])b(s,1.31,t,.055,.57,.055,wood);
      for(const y of [1.04,1.58])b(0,y,0,.59,.09,.54,brass);b(0,1.69,0,.31,.12,.29,wood);break;
    case 'aquarium':
      feet(.49,.22,.55);b(0,.57,0,1.32,.17,.67,wood);b(0,.93,-.22,1.18,.63,.1,'#36767e');
      b(0,.67,0,1.18,.09,.55,'#d5b886');b(0,1.28,0,1.29,.08,.63,dark);
      for(const s of [-.59,.59])b(s,.96,0,.065,.59,.56,mint);
      for(let i=0;i<5;i++)b(-.46+i*.17,.79,0,.055,.2+i%3*.1,.1,'#599c71');break;
    case 'hifi':
      feet(.56,.29,.28);b(0,.46,0,1.43,.46,.8,wood);b(0,.71,0,1.51,.07,.87,'#bd8863');
      for(const x of [-.48,.48]){b(x,.46,.42,.35,.33,.07,dark);for(let i=-2;i<=2;i++)b(x+i*.058,.46,.46,.018,.26,.035,brass);}
      for(let i=-3;i<=3;i++)b(-.17+i*.08,.76,0,.09,.04,.51-Math.abs(i)*.065,dark);
      b(-.17,.79,0,.13,.025,.13,wine);b(.31,.81,0,.06,.06,.34,brass);b(.2,.82,.16,.24,.05,.05,brass);break;
    case 'confetti':
      feet(.25,.2,.19);b(0,.38,0,.8,.48,.65,wine);b(0,.65,0,.86,.13,.7,brass);b(0,.75,0,.6,.1,.51,wine);
      for(const x of [-.26,.26])b(x,.4,.34,.08,.42,.04,brass);
      for(let i=-2;i<=2;i++)b(i*.09,.815,0,.09,.03,(3-Math.abs(i))*.1,mint);
      b(.49,.44,0,.16,.08,.08,brass);b(.58,.53,0,.07,.2,.07,brass);b(.6,.65,0,.14,.11,.11,dark);break;
    case 'tv':
      feet(.48,.23,.47);b(0,.49,0,1.48,.12,.74,wood);b(0,.98,0,1.44,.91,.67,'#936749');
      b(-.09,1,.345,1.09,.68,.04,dark);b(-.09,1,.37,.98,.56,.035,'#46626a');
      for(const y of [.87,1.14]){b(.56,y,.35,.16,.16,.08,dark);b(.56,y,.405,.035,.1,.03,brass);}
      for(let i=-2;i<=2;i++)b(i*.1,1.45,0,.065,.045,.4,dark);
      for(let i=0;i<5;i++)for(const sign of [-1,1])b(sign*(.07+i*.07),1.5+i*.065,0,.09,.1,.055,brass);break;
    }
  }
  function room(T, geometry, material, scenery){
    const group=new T.Group();scenery.indoor.add(group);
    const baseBoxes=scenery.indoorZone.boxes.length,baseCamera=scenery.indoorZone.cameraBoxes.length;
    let signature='', mesh=null, fish=null, lamp=null, particles=null, meter=null, playing=false, burstAt=-10, lastBurst=null;
    const dummy=new T.Object3D(),color=new T.Color();
    function clear(){
      mesh?.dispose();fish?.dispose();particles?.dispose();meter?.dispose();group.clear();mesh=fish=particles=lamp=meter=null;
      scenery.indoorZone.boxes.length=baseBoxes;scenery.indoorZone.cameraBoxes.length=baseCamera;
    }
    function build(boxes){
      const batch=new T.InstancedMesh(geometry,material,boxes.length);
      boxes.forEach(([x,y,z,w,h,d,c],i)=>{dummy.position.set(x,y,z);dummy.scale.set(w,h,d);dummy.updateMatrix();
        batch.setMatrixAt(i,dummy.matrix);batch.setColorAt(i,color.set(c));});
      batch.computeBoundingSphere();group.add(batch);return batch;
    }
    function apply(home){
      playing=!!home.record;
      const key=JSON.stringify([home.layout,home.lamp]);if(signature===key)return;
      signature=key;clear();const boxes=[];
      for(const [index,id] of Object.entries(home.layout)){
        const [x,z]=slots[index],parts=[];
        model(id,(dx,y,dz,w,h,d,c)=>parts.push([x+dx,y,z+dz,w,h,d,c]),home.lamp);
        boxes.push(...parts);
        if(id==='aquarium'){
          fish=build([[0,0,0,.18,.09,.07,'#f8ae72'],[-.12,0,0,.08,.14,.05,'#e98164'],[.064,.023,.043,.025,.025,.02,dark]]);
          fish.position.set(x,.98,z+.11);fish.userData.x=x;
        }
        if(id==='hifi'){
          meter=build(Array.from({length:5},(_,i)=>[(i-2)*.052,0,0,.038,.12,.023,i<3?mint:brass]));
          meter.position.set(x,.46,z+.41);meter.visible=playing;
        }
        if(id==='lamp'&&home.lamp){lamp=new T.PointLight('#ffc27a',4,3);lamp.position.set(x,1.4,z);group.add(lamp);}
        if(id==='confetti'){
          particles=build(Array.from({length:30},(_,i)=>[0,0,0,.055,.055,.055,[wine,mint,brass][i%3]]));
          particles.frustumCulled=false;particles.visible=false;particles.position.set(x,.83,z);
        }
        if(id==='rug')continue;
        const left=Math.min(...parts.map(p=>p[0]-p[3]/2)),right=Math.max(...parts.map(p=>p[0]+p[3]/2));
        const back=Math.min(...parts.map(p=>p[2]-p[5]/2)),front=Math.max(...parts.map(p=>p[2]+p[5]/2));
        const top=Math.max(...parts.map(p=>p[1]+p[4]/2));
        scenery.indoorZone.boxes.push([left,right,back,front,top]);
        scenery.indoorZone.cameraBoxes.push([left,right,0,top,back,front]);
      }
      if(boxes.length)mesh=build(boxes);
    }
    function tick(time){
      const t=time/1000;
      if(fish){fish.position.x=fish.userData.x+.31*Math.sin(t);fish.rotation.y=Math.cos(t)<0?Math.PI:0;}
      if(meter){meter.visible=playing;meter.scale.y=.8+.4*Math.sin(t*9);}
      if(!particles)return;
      const age=t-burstAt;particles.visible=age>=0&&age<1.45;
      if(!particles.visible)return;
      for(let i=0;i<particles.count;i++){
        const speed=.28+(i%7)*.12;
        dummy.position.set(Math.cos(i*2.4)*age*speed,age*(2.6+(i%4)*.18)-2.4*age*age,Math.sin(i*2.4)*age*speed);
        dummy.scale.setScalar(.065*Math.min(1,(1.45-age)*3));dummy.updateMatrix();particles.setMatrixAt(i,dummy.matrix);
      }
      particles.instanceMatrix.needsUpdate=true;
    }
    return {apply,tick,burst(stamp){if(lastBurst!==stamp){lastBurst=stamp;burstAt=performance.now()/1000;}},dispose:clear};
  }
  function apparel(id,box){
    const band=(y,c)=>box(-11,11,y,y+2,-8,8,c);
    const lens=(x,y,c)=>{box(x-3,x+3,y-2,y+2,8,10,'cream');box(x-2,x+2,y-1,y+1,11,11,c);};
    switch(id){
    case 'beret':band(44,'burgundy');box(-10,8,47,49,-7,7,'burgundy');box(-4,-2,50,51,-1,1,'cream');break;
    case 'scarf':box(-7,7,25,28,-5,6,'eye');box(3,6,18,26,7,8,'eye');box(3,6,18,19,8,8,'cream');break;
    case 'glasses':lens(-5,36,'black');lens(5,36,'black');box(-2,2,36,36,9,10,'cream');break;
    case 'bow':for(const s of [-1,1]){box(s*4-2,s*4+2,45,49,4,7,'burgundy');box(s*6-1,s*6+1,44,50,4,7,'red');}box(-1,1,46,48,6,8,'cream');break;
    case 'satchel':for(let j=0;j<12;j++)box(j-6,j-4,25-j,26-j,6,8,'denimGray');box(2,10,12,18,5,9,'shadow');box(3,9,16,18,10,10,'cream');dotLock();break;
    case 'phones':box(-10,10,47,48,-2,2,'black');for(const s of [-1,1]){box(10*s-1,10*s+1,37,47,-2,2,'black');box(12*s-1,12*s+1,34,40,-3,3,'denimGray');box(13*s,13*s,36,38,-1,1,'stripeWhite');}break;
    case 'fox':for(const s of [-1,1])for(let i=0;i<5;i++)box(s*7-4+i,s*7+4-i,45+i*2,46+i*2,-1,3,i>2?'cream':'shadow');break;
    case 'crown':band(44,'cream');for(let i=-2;i<=2;i++){box(i*4-1,i*4+1,47,48+Math.abs(i)%2,6,8,'cream');}box(-1,1,44,47,9,10,'red');break;
    case 'goggles':band(40,'shadow');lens(-5,42,'denimGray');lens(5,42,'denimGray');box(-2,2,42,43,9,10,'cream');break;
    case 'halo':for(let i=0;i<24;i++){const x=Math.round(10*Math.sin(i*Math.PI/12)),z=Math.round(8*Math.cos(i*Math.PI/12));box(x-1,x+1,51,52,z-1,z+1,i%3?'cream':'white');}break;
    }
    function dotLock(){box(6,7,15,16,10,11,'sole');}
  }
  function icon(canvas,item){
    const boxes=[];
    if(item.group==='decor')model(item.id,(...part)=>boxes.push(part),true);
    else if(item.group==='wear'){
      const colors={cream:brass,white:'#fff0cf',burgundy:wine,eye:'#58906b',black:dark,shadow:'#b97858',red:'#e66e71',denimGray:'#527688',sole:brass,stripeWhite:mint};
      apparel(item.id,(a,b,c,d,e,f,t)=>boxes.push([(a+b)/2,(c+d)/2,(e+f)/2,b-a+1,d-c+1,f-e+1,colors[t]]));
    }else{
      const hue=['#ba6077','#66a39a','#a589c0','#799cc2','#d39b61'][['vinyl_s1','vinyl_02','vinyl_03','vinyl_04','vinyl_06'].indexOf(item.id)];
      boxes.push([0,0,0,1,1,.09,hue]);
      for(let i=-3;i<=3;i++)boxes.push([.25,i*.112,.1,.8-Math.abs(i)*.115,.115,.09,dark]);
      boxes.push([.25,0,.18,.2,.2,.04,hue]);
    }
    const ctx=canvas.getContext('2d'),project=([x,y,z])=>[x*.84-z*.46,-y+.24*x+.34*z];
    const faces=[];
    for(const [x,y,z,w,h,d,color] of boxes.sort((a,b)=>(a[0]+a[2]+a[1])-(b[0]+b[2]+b[1]))){
      const vertex=(i,j,k)=>project([x+i*w/2,y+j*h/2,z+k*d/2]);
      for(const [corners,shade] of [[[[1,-1,-1],[1,-1,1],[1,1,1],[1,1,-1]],.73],[[[-1,-1,1],[1,-1,1],[1,1,1],[-1,1,1]],.92],[[[-1,1,-1],[1,1,-1],[1,1,1],[-1,1,1]],1]]){
        faces.push([corners.map(v=>vertex(...v)),color,shade]);
      }
    }
    const points=faces.flatMap(f=>f[0]);if(!points.length)return;
    const xs=points.map(p=>p[0]),ys=points.map(p=>p[1]),w=Math.max(...xs)-Math.min(...xs),h=Math.max(...ys)-Math.min(...ys);
    const scale=47/Math.max(w,h);
    ctx.setTransform(scale,0,0,scale,28-(Math.min(...xs)+w/2)*scale,28-(Math.min(...ys)+h/2)*scale);
    for(const [polygon,color,shade] of faces){ctx.fillStyle=color;ctx.beginPath();polygon.forEach(([x,y],i)=>i?ctx.lineTo(x,y):ctx.moveTo(x,y));ctx.closePath();ctx.fill();ctx.fillStyle='rgba(0,0,0,'+(1-shade)+')';ctx.fill();}
  }
  return {slots,stall,merchant,room,apparel,icon};
})();
