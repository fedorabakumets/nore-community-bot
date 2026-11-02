'use strict';
window.NoraWorld = (() => {
  const trees = [[-5.7,-5.6], [5.2,-4.7], [-5.6,5.3], [5.5,5.7]];
  function move(position, dx, dz, zone = {limit:8.35,boxes:[]}) {
    // Substeps prevent tunneling through furniture after a frame stall.
    const steps=Math.max(1,Math.ceil(Math.hypot(dx,dz)/.12));
    for(let step=0;step<steps;step++)for(const [axis,delta] of [['x',dx/steps],['z',dz/steps]]) {
      const bound=axis==='x'?(zone.limitX||zone.limit):(zone.limitZ||zone.limit);
      const next=Math.max(-bound,Math.min(bound,position[axis]+delta));
      const x=axis==='x'?next:position.x,z=axis==='z'?next:position.z;
      if(!zone.boxes.some(([x0,x1,z0,z1])=>x>x0-.34&&x<x1+.34&&z>z0-.34&&z<z1+.34))position[axis]=next;
    }
    position.y=.017;
  }
  function cameraDistance(origin,direction,distance,boxes) {
    // Swept camera volume: enlarged boxes cover the near plane, not only its center ray.
    let safe=distance;
    for(const bounds of boxes){
      let near=0,far=distance;
      for(const [axis,lo,hi] of [['x',0,1],['y',2,3],['z',4,5]]){
        const min=bounds[lo]-.22,max=bounds[hi]+.22,v=direction[axis],p=origin[axis];
        if(Math.abs(v)<1e-7){if(p<min||p>max){far=-1;break;}}
        else {const a=(min-p)/v,b=(max-p)/v;near=Math.max(near,Math.min(a,b));far=Math.min(far,Math.max(a,b));}
      }
      if(near<=far&&far>=0)safe=Math.min(safe,Math.max(.55,near-.12));
    }
    return safe;
  }
  async function mount(canvas, root, outfit) {
    const T = await import('/vendor/three.module.js');
    if (!root.isConnected) return () => {};
    const renderer = new T.WebGLRenderer({canvas, antialias:false, powerPreference:'low-power'});
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5));
    renderer.outputColorSpace = T.SRGBColorSpace;
    const scene = new T.Scene(); scene.background = new T.Color('#8dcfee');
    scene.fog = new T.Fog('#a8daf0', 28, 85);
    const camera = new T.PerspectiveCamera(58, 1, .1, 110);
    const ambient=new T.HemisphereLight('#fff6df', '#71865f', 2.2);scene.add(ambient);
    const sunlight = new T.DirectionalLight('#fff1cd', 2.4); sunlight.position.set(-12,22,10);scene.add(sunlight);
    const geometry = new T.BoxGeometry(1,1,1), material = new T.MeshLambertMaterial({color:0xffffff});
    const blocks = [], matrix = new T.Object3D(), tint = new T.Color();
    function block(x,y,z,sx,sy,sz,color) { blocks.push([x,y,z,sx,sy,sz,color]); }
    // Grass top and layered soil; only exterior earth faces need cubes.
    for(let x=-9;x<9;x++) for(let z=-9;z<9;z++) {
      const tone=(Math.abs(x*17+z*13)%5);
      block(x+.5,-.25,z+.5,1,.5,1,['#70b94c','#7cc653','#83ca57','#79bf4d','#8ace60'][tone]);
      if (Math.abs(x+.5)>7.5 || Math.abs(z+.5)>7.5) {
        block(x+.5,-.75,z+.5,1,.5,1,['#94704c','#a57a50','#8e694b'][tone%3]);
        block(x+.5,-1.25,z+.5,1,.5,1,['#6d5b4c','#766450','#81715c'][tone%3]);
      }
    }
    block(0,-1.5,0,18,.25,18,'#6c5d51');
    trees.forEach(([x,z],tree)=>{
      // Trunks, roots and stepped branches built from small cubes.
      for(let y=0;y<8;y++) for(let a=0;a<2;a++) for(let b=0;b<2;b++)
        block(x+(a-.5)*.26,.13+y*.26,z+(b-.5)*.26,.26,.26,.26,(a+y)%3?'#87603e':'#aa7745');
      for(const side of [-1,1]) {block(x+side*.35,.13,z,.4,.26,.3,'#87603e');block(x+side*.4,1.7,z,.5,.24,.24,'#916840');}
      for(let a=-3;a<=3;a++) for(let b=-2;b<=3;b++) for(let c=-3;c<=3;c++) {
        if(Math.abs(a)+Math.abs(c)+Math.max(0,b)>7 || (Math.abs(a)<3&&Math.abs(c)<3&&b>-2&&b<3))continue;
        block(x+a*.42,2.7+b*.42,z+c*.42,.42,.42,.42,['#4c9a4c','#62b657','#75c95b','#8cce65'][Math.abs(a*7+b*3+c+tree)%4]);
      }
      // Sparse meadow tufts around the trees, away from the spawn point.
      for(let i=0;i<5;i++) block(x+Math.sin(i*2)*1.8,.09,z+Math.cos(i*2)*1.8,.12,.18,.12,'#a5d66a');
    });
    // Chunky cloud clusters at different depths in the bright sky.
    for(const [x,y,z] of [[-19,10,-35],[12,12,-45],[32,13,4],[-33,12,16],[0,12,38]])
      for(let a=-3;a<=3;a++)for(let b=0;b<2;b++)for(let c=-1;c<=1;c++) {
        if(Math.abs(a)+Math.abs(c)+b>4)continue;
        block(x+a*1.3,y+b*1.3,z+c*1.3,1.3,1.3,1.3,b?'#fffef2':'#dceaf0');
      }
    const landscape = new T.InstancedMesh(geometry,material,blocks.length);
    blocks.forEach(([x,y,z,sx,sy,sz,color],i)=>{matrix.position.set(x,y,z);matrix.scale.set(sx,sy,sz);matrix.updateMatrix();landscape.setMatrixAt(i,matrix.matrix);tint.set(color);landscape.setColorAt(i,tint);});
    landscape.instanceMatrix.needsUpdate=true;landscape.computeBoundingSphere();scene.add(landscape);
    const sunMaterial=new T.MeshBasicMaterial({color:'#fff3b0'}), sun=new T.Mesh(geometry,sunMaterial);
    sun.position.set(-8,12,-45);sun.scale.set(4,4,1);scene.add(sun);
    const scenery=window.NoraScenery.create(T,geometry,material);scene.add(scenery.outdoor,scenery.indoor);
    let inside=false,zone=scenery.outdoorZone;
    const character=window.NoraVoxel.createCharacter(T,outfit), player=character.group;
    player.scale.setScalar(.32);player.position.set(0,.017,5.5);player.rotation.y=Math.PI;scene.add(player);
    // Soft contact patches without costly real-time shadow maps.
    const shadowCanvas=document.createElement('canvas');shadowCanvas.width=64;shadowCanvas.height=64;
    const context=shadowCanvas.getContext('2d'), gradient=context.createRadialGradient(32,32,3,32,32,32);
    gradient.addColorStop(0,'rgba(28,48,30,.3)');gradient.addColorStop(1,'rgba(28,48,30,0)');context.fillStyle=gradient;context.fillRect(0,0,64,64);
    const shadowTexture=new T.CanvasTexture(shadowCanvas), shadowGeo=new T.PlaneGeometry(1,1), shadowMat=new T.MeshBasicMaterial({map:shadowTexture,transparent:true,depthWrite:false});
    const groundShadows=new T.InstancedMesh(shadowGeo,shadowMat,trees.length);
    trees.forEach(([x,z],i)=>{matrix.position.set(x,.006,z);matrix.rotation.set(-Math.PI/2,0,0);matrix.scale.set(4,4,1);matrix.updateMatrix();groundShadows.setMatrixAt(i,matrix.matrix);});scene.add(groundShadows);
    const playerShadow=new T.Mesh(shadowGeo,shadowMat);playerShadow.rotation.x=-Math.PI/2;playerShadow.scale.set(1.1,1.1,1);scene.add(playerShadow);
    let yaw=0, targetYaw=0, pitch=.32, targetPitch=.32, raf=0, previous=0, disposed=false, orbitId=null, lastX=0,lastY=0,joyId=null;
    let actualDistance=5.7,opacity=1;
    const stick={x:0,z:0}, joystick=root.querySelector('.nora-world-joystick'), knob=root.querySelector('.nora-world-knob');
    const controls=new AbortController(), on=(el,event,fn)=>el.addEventListener(event,fn,{signal:controls.signal});
    function resetStick(){stick.x=stick.z=0;joyId=null;knob.style.transform='translate(0px,0px)';}
    function joystickMove(e){const rect=joystick.getBoundingClientRect();let x=e.clientX-(rect.left+rect.width/2),z=e.clientY-(rect.top+rect.height/2);const max=rect.width*.3,length=Math.hypot(x,z);if(length>max){x*=max/length;z*=max/length;}stick.x=x/max;stick.z=z/max;knob.style.transform=`translate(${x}px,${z}px)`;}
    on(joystick,'pointerdown',e=>{if(joyId!==null)return;e.preventDefault();joyId=e.pointerId;joystick.setPointerCapture(joyId);joystickMove(e);});
    on(joystick,'pointermove',e=>{if(e.pointerId===joyId)joystickMove(e);});
    for(const event of ['pointerup','pointercancel','lostpointercapture'])on(joystick,event,e=>{if(e.pointerId===joyId)resetStick();});
    on(canvas,'pointerdown',e=>{if(orbitId!==null)return;orbitId=e.pointerId;lastX=e.clientX;lastY=e.clientY;canvas.setPointerCapture(orbitId);});
    on(canvas,'pointermove',e=>{if(e.pointerId!==orbitId)return;targetYaw-=(e.clientX-lastX)*.006;targetPitch=Math.max(.15,Math.min(.85,targetPitch+(e.clientY-lastY)*.004));lastX=e.clientX;lastY=e.clientY;});
    for(const event of ['pointerup','pointercancel','lostpointercapture'])on(canvas,event,e=>{if(e.pointerId===orbitId)orbitId=null;});
    function reset(){resetStick();orbitId=null;previous=0;}
    on(window,'blur',reset);on(document,'visibilitychange',reset);
    const action=root.querySelector('.nora-world-action');
    function nearDoor(){return Math.abs(player.position.x)<1.5&&(inside?player.position.z>3.3:player.position.z>2.55&&player.position.z<4.8);}
    on(action,'click',()=>{
      if(!nearDoor())return;
      inside=!inside;zone=inside?scenery.indoorZone:scenery.outdoorZone;
      scenery.indoor.visible=inside;scenery.outdoor.visible=!inside;landscape.visible=!inside;sun.visible=!inside;groundShadows.visible=!inside;
      scene.background.set(inside?'#3e3029':'#8dcfee');scene.fog=new T.Fog(inside?'#66503c':'#a8daf0',inside?14:28,inside?30:85);
      ambient.color.set(inside?'#ffe0b4':'#fff6df');ambient.groundColor.set(inside?'#795a43':'#71865f');sunlight.color.set(inside?'#ffd3a0':'#fff1cd');sunlight.intensity=inside?1.1:2.4;
      player.position.set(0,.017,inside?3.7:3.6);player.rotation.y=inside?Math.PI:0;
      root.querySelector('.nora-world-bar small').textContent=inside?'ТАВЕРНА':'ЛЕСНАЯ ПОЛЯНА';
      reset();
    });
    function resize(){const w=canvas.clientWidth,h=canvas.clientHeight;if(!w||!h)return;renderer.setSize(w,h,false);camera.aspect=w/h;camera.updateProjectionMatrix();}
    const observer=new ResizeObserver(resize);observer.observe(canvas);resize();
    const target=new T.Vector3(), offset=new T.Vector3(), direction=new T.Vector3();
    function tick(time){
      if(disposed)return;const dt=previous?Math.min((time-previous)/1000,.05):0;previous=time;
      if(!document.hidden){
        const smooth=1-Math.exp(-12*dt);yaw+=(targetYaw-yaw)*smooth;pitch+=(targetPitch-pitch)*smooth;
        const dx=(stick.x*Math.cos(yaw)+stick.z*Math.sin(yaw))*3.1*dt;
        const dz=(-stick.x*Math.sin(yaw)+stick.z*Math.cos(yaw))*3.1*dt;
        move(player.position,dx,dz,zone);
        if(Math.hypot(dx,dz)>.0001){const heading=Math.atan2(dx,dz),delta=Math.atan2(Math.sin(heading-player.rotation.y),Math.cos(heading-player.rotation.y));player.rotation.y+=delta*(1-Math.exp(-16*dt));}
        playerShadow.position.set(player.position.x,.008,player.position.z);
        target.set(player.position.x,1.1,player.position.z);
        const wanted=inside?4.6:(camera.aspect<.7?5.7:5.1);
        direction.set(Math.sin(yaw)*Math.cos(pitch),Math.sin(pitch),Math.cos(yaw)*Math.cos(pitch));
        const safe=cameraDistance(target,direction,wanted,zone.cameraBoxes);
        actualDistance=Math.min(safe,actualDistance+(safe-actualDistance)*(1-Math.exp(-5*dt)));
        const fade=Math.max(.35,Math.min(1,(actualDistance-.5)/2));
        opacity+=(fade-opacity)*(1-Math.exp(-14*dt));character.setOpacity(opacity);
        offset.copy(direction).multiplyScalar(actualDistance);
        action.hidden=!nearDoor();action.textContent=inside?'Выйти из таверны':'Войти в таверну';
        camera.position.copy(target).add(offset);camera.lookAt(target);renderer.render(scene,camera);
      }
      raf=requestAnimationFrame(tick);
    }tick(0);
    function stop(){if(disposed)return;disposed=true;cancelAnimationFrame(raf);controls.abort();observer.disconnect();resetStick();character.dispose();scenery.dispose();landscape.dispose();groundShadows.dispose();geometry.dispose();material.dispose();sunMaterial.dispose();shadowTexture.dispose();shadowGeo.dispose();shadowMat.dispose();renderer.dispose();}
    on(canvas,'webglcontextlost',e=>{e.preventDefault();stop();root.querySelector('.nora-world-help').textContent='Графика остановлена. Закрой и открой игру снова.';});
    return stop;
  }
  return {mount,move,cameraDistance};
})();
