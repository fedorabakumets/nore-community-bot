'use strict';
window.NoraWorld = (() => {
  const GRAVITY=13, JUMP_SPEED=4.4;
  const WING_LIFT_SPEED=6.8, GLIDE_GRAVITY=6.5, GLIDE_FALL_SPEED=3.4;
  const TAVERN_JUMP_LIMIT=1.5; // Keep the avatar below the ceiling beams.
  const trees = [[-5.7,-5.6], [5.2,-4.7], [-5.6,5.3], [5.5,5.7]];
  const FURNITURE_RADIUS=.12;
  function overlapsBox(x,z,[x0,x1,z0,z1],radius){
    return x>x0-radius&&x<x1+radius&&z>z0-radius&&z<z1+radius;
  }
  function move(position, dx, dz, zone = {limit:8.35,boxes:[]}, feet) {
    // Substeps prevent tunneling through furniture after a frame stall.
    const steps=Math.max(1,Math.ceil(Math.hypot(dx,dz)/.12));
    for(let step=0;step<steps;step++)for(const [axis,delta] of [['x',dx/steps],['z',dz/steps]]) {
      const bound=axis==='x'?(zone.limitX||zone.limit):(zone.limitZ||zone.limit);
      const next=Math.max(-bound,Math.min(bound,position[axis]+delta));
      const x=axis==='x'?next:position.x,z=axis==='z'?next:position.z;
      if(!zone.boxes.some(box=>(feet??0)<(box[4]??Infinity)&&overlapsBox(x,z,box,Number.isFinite(box[4])&&feet!==undefined?FURNITURE_RADIUS:.34)))position[axis]=next;
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
  function timeOfDay(now=Date.now()) {
    // Moscow is UTC+3 year-round; independent of the device's selected timezone.
    const hour=((now/3600000+3)%24+24)%24;
    const elevation=Math.sin((hour-6)/24*Math.PI*2);
    const t=Math.max(0,Math.min(1,(elevation+.12)/.48));
    const daylight=t*t*(3-2*t);
    return {hour,daylight,twilight:1-Math.abs(daylight*2-1)};
  }
  function tavernAcoustics(inside,x,z,yaw=0) {
    const dx=-x,dz=(inside?0:2.55)-z,distance=Math.hypot(dx,dz);
    if(inside)return {gain:.9,cutoff:18000,pan:Math.max(-.65,Math.min(.65,(dx*Math.cos(yaw)-dz*Math.sin(yaw))/Math.max(1,distance)))};
    // Sound escapes through the front doorway; walls muffle side/rear listening.
    const front=Math.max(0,Math.min(1,(z-1.5)/1.6));
    const door=front/(1+distance*.65);
    return {gain:.035+.6*door,cutoff:450+4200*door,pan:Math.max(-.8,Math.min(.8,(dx*Math.cos(yaw)-dz*Math.sin(yaw))/Math.max(1,distance)))};
  }
  function createAtmosphere(T,scene,geometry) {
    const starsMaterial=new T.MeshBasicMaterial({color:'#dce4e0',transparent:true,depthWrite:false,fog:false});
    const leafMaterial=new T.MeshLambertMaterial({color:'#b6a06a'});
    const stars=new T.InstancedMesh(geometry,starsMaterial,112);
    const leaves=new T.InstancedMesh(geometry,leafMaterial,128);
    stars.name='nora-stars';leaves.name='nora-leaves';
    stars.frustumCulled=leaves.frustumCulled=false;
    stars.instanceMatrix.setUsage(T.DynamicDrawUsage);leaves.instanceMatrix.setUsage(T.DynamicDrawUsage);
    scene.add(stars,leaves);
    const o=new T.Object3D(),color=new T.Color();
    const anchors=[...trees,[-7.2,-10.5],[0,-10.5],[7.2,-10.5],[-7.2,10.5],[0,10.5],[7.2,10.5],[-10.5,0],[10.5,0]];
    const reduced=window.matchMedia?.('(prefers-reduced-motion: reduce)').matches||false;
    let elapsed=0;
    for(let i=0;i<128;i++){color.set(['#ae965c','#7b9867','#b17858','#647f68'][i%4]);leaves.setColorAt(i,color);}
    function update(dt,daylight,inside){
      elapsed+=dt;
      stars.visible=!inside&&daylight<.99;leaves.visible=!inside;
      starsMaterial.opacity=(1-daylight)*.85;
      if(inside)return;
      if(stars.visible){
        for(let i=0;i<112;i++){
          const a=i*2.399963, y=.12+(i+.5)/112*.86, radius=65*Math.sqrt(1-y*y);
          const pulse=reduced ? .7 : .45+.55*Math.pow(.5+.5*Math.sin(elapsed*(.32+(i%7)*.07)+i*1.7),3);
          o.position.set(Math.cos(a)*radius,65*y,Math.sin(a)*radius);
          o.rotation.set(0,a,0);o.scale.setScalar((.07+(i%4)*.025)*pulse);o.updateMatrix();stars.setMatrixAt(i,o.matrix);
        }
        stars.instanceMatrix.needsUpdate=true;
      }
      for(let i=0;i<128;i++){
        const leaf=Math.floor(i/4),fragment=i%4,anchor=anchors[leaf%anchors.length];
        const cycle=(elapsed*(reduced ? .035 : .12)+(leaf*.6180339)%1)%1;
        const drift=cycle*1.2,spread=Math.max(0,(cycle-.58)/.42);
        // Each leaf breaks into four separate voxel fragments before vanishing aloft.
        const visible=cycle<.75+fragment*.055;
        o.position.set(anchor[0]+Math.sin(leaf*7)*.9+Math.sin(cycle*7+leaf)*.28+drift+(fragment%2-.5)*(.07+spread*.35),
          3.7-cycle*3.3+(fragment<2?1:-1)*spread*.12,
          anchor[1]+Math.cos(leaf*3)*.9+Math.cos(cycle*6+leaf)*.35+(fragment<2?-.5:.5)*(.07+spread*.35));
        o.rotation.set(cycle*5+leaf,cycle*4,Math.sin(cycle*7+leaf)*.6);
        o.scale.set(visible?.065:0,visible?.025:0,visible?.065:0);o.updateMatrix();leaves.setMatrixAt(i,o.matrix);
      }
      leaves.instanceMatrix.needsUpdate=true;
    }
    return {update,dispose(){scene.remove(stars,leaves);stars.dispose();leaves.dispose();starsMaterial.dispose();leafMaterial.dispose();}};
  }
  function lobbyPlayers(T,scene,player,status){
    const peers=new Map();
    let session=null,pending=null,next=0;
    function remove(nickname){
      const peer=peers.get(nickname);
      scene.remove(peer.avatar.group);
      peer.label.material.map.dispose();peer.label.material.dispose();peer.avatar.dispose();
      peers.delete(nickname);
    }
    function add({nickname,outfit,x,y,z,heading}){
      const avatar=window.NoraVoxel.createCharacter(T,outfit);
      avatar.group.scale.setScalar(.32);
      avatar.group.position.set(x,y,z);avatar.group.rotation.y=heading;
      const canvas=document.createElement('canvas');canvas.width=256;canvas.height=48;
      const ctx=canvas.getContext('2d');
      ctx.fillStyle='#181424';ctx.fillRect(0,0,256,48);
      ctx.fillStyle='#f0ddff';ctx.font='bold 23px monospace';ctx.textAlign='center';
      ctx.fillText(nickname,128,32,236);
      const label=new T.Sprite(new T.SpriteMaterial({map:new T.CanvasTexture(canvas),depthWrite:false}));
      label.position.y=5.5;label.scale.set(4.5,.84,1);avatar.group.add(label);
      scene.add(avatar.group);
      const peer={avatar,label,target:null};peers.set(nickname,peer);return peer;
    }
    function leave(){
      if(!session)return Promise.resolve();
      const departed=session;session=null;
      for(const nickname of peers.keys())remove(nickname);
      const send=()=>api('nora-game/lobby',{leave:true,session:departed},AbortSignal.timeout(3000)).catch(()=>{});
      pending=Promise.resolve(pending).then(send).finally(()=>{pending=null;});
      return pending;
    }
    function update(time,dt){
      if(!session){
        session=crypto.randomUUID();next=0;
        status.textContent='ЛОББИ · ПОДКЛЮЧЕНИЕ';
      }
      if(!pending&&time>=next){
        next=time+400;
        const {x,y,z}=player.position,angle=player.rotation.y;
        const heading=Math.atan2(Math.sin(angle),Math.cos(angle));
        const sentSession=session;
        pending=api('nora-game/lobby',{session,x,y,z,heading},AbortSignal.timeout(3000)).then(({players})=>{
          if(session!==sentSession)return;
          if(status.textContent!=='ЛОББИ')status.textContent='ЛОББИ';
          const online=new Set();
          for(const pose of players){
            online.add(pose.nickname);
            const peer=peers.get(pose.nickname)||add(pose);
            peer.avatar.setWings(pose.outfit.wings);
            peer.target=pose;
          }
          for(const nickname of peers.keys())if(!online.has(nickname))remove(nickname);
        }).catch(()=>{
          if(session!==sentSession)return;
          if(status.textContent!=='ЛОББИ · СВЯЗЬ ПОТЕРЯНА')status.textContent='ЛОББИ · СВЯЗЬ ПОТЕРЯНА';
          for(const nickname of peers.keys())remove(nickname);
        });
        const sent=pending;
        sent.finally(()=>{if(pending===sent)pending=null;});
      }
      const ease=1-Math.exp(-9*dt);
      for(const {avatar,target} of peers.values()){
        const {position,rotation}=avatar.group;
        const dx=(target.x-position.x)*ease,dz=(target.z-position.z)*ease;
        position.x+=dx;position.z+=dz;position.y+=(target.y-position.y)*ease;
        const angle=target.heading-rotation.y;
        rotation.y+=Math.atan2(Math.sin(angle),Math.cos(angle))*ease;
        const distance=Math.hypot(dx,dz);
        avatar.walk(position.y>.04?0:distance,dt,distance>2.2*dt);
        avatar.animateWings(dt,target.y>.04);
      }
    }
    return {update,leave};
  }
  async function mount(canvas, root, outfit, sounds) {
    const T = await import('/vendor/three.module.js');
    if (!root.isConnected) { sounds?.stop(); return () => {}; }
    const renderer = new T.WebGLRenderer({canvas, antialias:false, powerPreference:'low-power'});
    const mobile=window.matchMedia?.('(pointer:coarse)').matches||false;
    let quality=1,frameTotal=0,frameCount=0,qualityAt=0,renderWidth=0,renderHeight=0,renderRatio=0;
    renderer.outputColorSpace = T.SRGBColorSpace;
    const scene = new T.Scene(); scene.background = new T.Color('#b2d5d2');
    scene.fog = new T.Fog('#b2d5d2', 12, 42);
    const camera = new T.PerspectiveCamera(58, 1, .1, 110);
    const ambient=new T.HemisphereLight('#fff6df', '#71865f', 2.2);scene.add(ambient);
    const sunlight = new T.DirectionalLight('#fff1cd', 2.4); sunlight.position.set(-12,22,10);scene.add(sunlight);
    const geometry = new T.BoxGeometry(1,1,1), material = new T.MeshLambertMaterial({color:'#b9bca4'});
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
    const sunMaterial=new T.MeshBasicMaterial({color:'#efd0a0',fog:false,transparent:true,depthWrite:false}), sun=new T.Mesh(geometry,sunMaterial);
    sun.position.set(-8,12,-45);sun.scale.set(4,4,1);scene.add(sun);
    const moonMaterial=new T.MeshBasicMaterial({color:'#c6d4dc',fog:false,transparent:true,depthWrite:false});
    const moon=new T.Mesh(geometry,moonMaterial);moon.scale.set(2.6,2.6,.8);scene.add(moon);
    const scenery=window.NoraScenery.create(T,geometry,material);scene.add(scenery.outdoor,scenery.indoor);if(scenery.carriedRecord)scene.add(scenery.carriedRecord);
    if(scenery.lobby)scene.add(scenery.lobby);
    const tavernOffset=window.NoraScenery.tavernOffset??0;
    const {portalZ,lobbyDeck}=window.NoraScenery;
    let inside=false,inLobby=false,zone=scenery.outdoorZone;
    const atmosphere=createAtmosphere(T,scene,geometry);
    const skyNight=new T.Color('#101621'),skyDay=new T.Color('#718982'),skyDusk=new T.Color('#795359');
    const lightNight=new T.Color('#9aadd0'),lightDay=new T.Color('#f3d8ad');
    let lightingAt=-Infinity;
    function updateLighting(now){
      const phase=timeOfDay(now);
      if(now-lightingAt>1000||now<lightingAt){
        lightingAt=now;
        if(inside){
          scene.background.set('#241c20');scene.fog.color.set('#382a2b');scene.fog.near=10;scene.fog.far=26;
          ambient.color.set('#e8c594');ambient.groundColor.set('#534037');ambient.intensity=1.65;
          sunlight.color.set('#ffc083');sunlight.intensity=1.25;
        }else if(inLobby){
          scene.background.set('#171725');scene.fog.color.copy(scene.background);
          scene.fog.near=10;scene.fog.far=32;
          ambient.color.set('#b8b6eb');ambient.groundColor.set('#504363');ambient.intensity=1.28;
          sunlight.color.set('#a3aeef');sunlight.intensity=.85;sunlight.position.set(-12,22,10);
        }else{
          scene.background.copy(skyNight).lerp(skyDay,phase.daylight).lerp(skyDusk,phase.twilight*.45);
          scene.fog.color.copy(scene.background);scene.fog.near=10;scene.fog.far=phase.daylight*10+32;
          ambient.color.copy(lightNight).lerp(lightDay,phase.daylight);ambient.groundColor.set('#3e5149');ambient.intensity=1.15+phase.daylight*.7;
          sunlight.color.copy(lightNight).lerp(lightDay,phase.daylight);sunlight.intensity=.75+phase.daylight*1.35;
          sunMaterial.opacity=phase.daylight;moonMaterial.opacity=1-phase.daylight;
          const angle=(phase.hour-6)/24*Math.PI*2;
          sun.position.set(Math.cos(angle)*38,Math.sin(angle)*38,-45);
          moon.position.set(-Math.cos(angle)*38,-Math.sin(angle)*38,-45);
          sunlight.position.lerpVectors(moon.position,sun.position,phase.daylight);sunlight.position.y=Math.max(8,sunlight.position.y);
        }
      }
      return inLobby?0:phase.daylight;
    }
    updateLighting(Date.now());
    const character=window.NoraVoxel.createCharacter(T,outfit), player=character.group;
    player.scale.setScalar(.32);player.position.set(0,.017,5.5+tavernOffset);player.rotation.y=Math.PI;scene.add(player);
    const locationLabel=root.querySelector('.nora-world-bar small');
    const lobby=lobbyPlayers(T,scene,player,locationLabel);
    // Soft contact patches without costly real-time shadow maps.
    const shadowCanvas=document.createElement('canvas');shadowCanvas.width=64;shadowCanvas.height=64;
    const context=shadowCanvas.getContext('2d'), gradient=context.createRadialGradient(32,32,3,32,32,32);
    gradient.addColorStop(0,'rgba(28,48,30,.3)');gradient.addColorStop(1,'rgba(28,48,30,0)');context.fillStyle=gradient;context.fillRect(0,0,64,64);
    const shadowTexture=new T.CanvasTexture(shadowCanvas), shadowGeo=new T.PlaneGeometry(1,1), shadowMat=new T.MeshBasicMaterial({map:shadowTexture,transparent:true,depthWrite:false});
    const groundShadows=new T.InstancedMesh(shadowGeo,shadowMat,trees.length);
    trees.forEach(([x,z],i)=>{matrix.position.set(x,.006,z);matrix.rotation.set(-Math.PI/2,0,0);matrix.scale.set(4,4,1);matrix.updateMatrix();groundShadows.setMatrixAt(i,matrix.matrix);});scene.add(groundShadows);
    const playerShadow=new T.Mesh(shadowGeo,shadowMat);playerShadow.rotation.x=-Math.PI/2;playerShadow.scale.set(1.1,1.1,1);scene.add(playerShadow);
    let yaw=0, targetYaw=0, pitch=.32, targetPitch=.32, raf=0, previous=0, disposed=false, orbitId=null, lastX=0,lastY=0,joyId=null;
    let wingBoostUsed=false;
    let pov=Number(root.dataset.pov ?? 100), actualDistance=5.7,cameraRelease=0,cameraSpeed=0,opacity=1,jumpHeight=0,jumpVelocity=0,view=0,velocityX=0,velocityZ=0,sprintTouch=false;
    const viewButton=root.querySelector('.nora-world-view');
    const views=['За спиной','От первого лица','Селфи'];
    function syncView(){viewButton.setAttribute('aria-label','Вид: '+views[view]+'. Сменить вид');viewButton.querySelector('small').textContent=views[view];}
    syncView();
    const sprintButton=root.querySelector('.nora-world-sprint');
    const keys=new Set(), jumpButton=root.querySelector('.nora-world-jump');
    const stick={x:0,z:0}, joystick=root.querySelector('.nora-world-joystick'), knob=root.querySelector('.nora-world-knob');
    const controls=new AbortController(), on=(el,event,fn)=>el.addEventListener(event,fn,{signal:controls.signal});
    function resetStick(){stick.x=stick.z=0;joyId=null;knob.style.transform='translate(0px,0px)';}
    function joystickMove(e){const rect=joystick.getBoundingClientRect();let x=e.clientX-(rect.left+rect.width/2),z=e.clientY-(rect.top+rect.height/2);const max=rect.width*.3,length=Math.hypot(x,z);if(length>max){x*=max/length;z*=max/length;}stick.x=x/max;stick.z=z/max;knob.style.transform=`translate(${x}px,${z}px)`;}
    on(joystick,'pointerdown',e=>{if(joyId!==null)return;e.preventDefault();joyId=e.pointerId;joystick.setPointerCapture(joyId);joystickMove(e);});
    on(joystick,'pointermove',e=>{if(e.pointerId===joyId)joystickMove(e);});
    for(const event of ['pointerup','pointercancel','lostpointercapture'])on(joystick,event,e=>{if(e.pointerId===joyId)resetStick();});
    on(canvas,'pointerdown',e=>{if(inputPaused()||orbitId!==null)return;orbitId=e.pointerId;lastX=e.clientX;lastY=e.clientY;canvas.setPointerCapture(orbitId);});
    on(canvas,'pointermove',e=>{if(e.pointerId!==orbitId)return;targetYaw-=(e.clientX-lastX)*.006;targetPitch=Math.max(.15,Math.min(.85,targetPitch+(e.clientY-lastY)*.004));lastX=e.clientX;lastY=e.clientY;});
    for(const event of ['pointerup','pointercancel','lostpointercapture'])on(canvas,event,e=>{if(e.pointerId===orbitId)orbitId=null;});
    on(sprintButton,'click',()=>{sprintTouch=!sprintTouch;sprintButton.setAttribute('aria-pressed',String(sprintTouch));sprintButton.blur();});
    let grounded=true;
    function jump(){
      if(inputPaused())return;
      if(grounded){grounded=false;jumpVelocity=JUMP_SPEED;}
      else if(outfit.wings&&jumpHeight>0&&!wingBoostUsed){
        wingBoostUsed=true;
        jumpVelocity=WING_LIFT_SPEED;
      } else return;
      sounds?.jump(inside);
    }
    on(root,'nora-pov',e=>{pov=e.detail;view=pov===0?1:0;actualDistance=0;cameraRelease=0;cameraSpeed=0;syncView();});
    if(pov===0){view=1;syncView();}
    on(viewButton,'click',()=>{viewButton.blur();view=(view+1)%3;if(view!==1&&pov===0){pov=100;root.dispatchEvent(new CustomEvent('nora-view-pov',{detail:pov}));}cameraRelease=0;cameraSpeed=0;syncView();});
    on(jumpButton,'pointerdown',e=>{if(e.button===0){e.preventDefault();jump();}});
    // Keyboard activation has detail=0. A pointer's click follows its pointerdown.
    on(jumpButton,'click',e=>{if(e.detail===0&&!e.pointerType)jump();});
    on(jumpButton,'keydown',e=>{if(e.repeat&&['Enter',' '].includes(e.key))e.preventDefault();});
    on(window,'keydown',e=>{
      if(inputPaused())return;
      if(!['KeyW','KeyA','KeyS','KeyD','Space','ShiftLeft','ShiftRight'].includes(e.code)||e.ctrlKey||e.metaKey||e.altKey)return;
      if(e.target?.closest?.('input,textarea,select,[contenteditable="true"]'))return;
      if(e.code==='Space'&&e.target?.closest?.('button'))return;
      e.preventDefault();
      if(e.code==='Space'){if(!e.repeat)jump();}else keys.add(e.code);
    });
    on(window,'keyup',e=>{if(keys.delete(e.code))e.preventDefault();});
    function reset(){resetStick();keys.clear();orbitId=null;previous=0;frameTotal=frameCount=qualityAt=0;velocityX=velocityZ=0;sprintTouch=false;sprintButton.setAttribute('aria-pressed','false');}
    on(root,'nora-settings-open',reset);on(window,'blur',reset);on(document,'visibilitychange',reset);
    const action=root.querySelector('.nora-world-action');
    const recordButton=root.querySelector('.nora-record-toggle');
    let recordPlaying=true, audioPlaying=true;
    function inputPaused(){return !!root.querySelector('.nora-settings[open]')||companion.panelOpen()||!!records?.panelOpen();}
    function nearLobbyDeck(){
      return inLobby&&Math.hypot(player.position.x-lobbyDeck.x,player.position.z-lobbyDeck.z)<1.8&&jumpHeight===0&&jumpVelocity===0;
    }
    function nearRecord(){
      return !inputPaused()&&(inLobby?nearLobbyDeck():
        inside&&Math.hypot(player.position.x,player.position.z)<1.8&&jumpHeight===0&&jumpVelocity===0);
    }
    function syncRecordButton(){
      const available=inLobby?records?.canToggleLobby():!records||records.hasRecord();
      const playing=inLobby?!!records?.lobbyPlaying():recordPlaying;
      const hidden=!nearRecord()||!available;
      if(recordButton.hidden!==hidden)recordButton.hidden=hidden;
      const text=playing?'Выключить проигрыватель':'Включить проигрыватель';
      if(recordButton.textContent!==text){recordButton.textContent=text;recordButton.setAttribute('aria-pressed',String(playing));}
    }
    on(recordButton,'click',()=>{
      if(!nearRecord())return;
      if(inLobby)records?.toggleLobby();
      else{recordPlaying=!recordPlaying;audioPlaying=recordPlaying;sounds?.playing(recordPlaying);}
      syncRecordButton();recordButton.blur();
    });
    function nearbyAction(){
      if(inputPaused()||jumpHeight>0||jumpVelocity!==0)return '';
      const {x,z}=player.position;
      if(inside)return Math.abs(x)<1.5&&z>3.3?'Выйти из таверны':'';
      if(portalZ&&Math.abs(x)<1.65&&Math.abs(z-portalZ[inLobby?'lobby':'home'])<1.85)
        return inLobby?'НА ОСТРОВ':'ЛОББИ';
      return !inLobby&&Math.abs(x)<1.5&&z-tavernOffset>2.55&&z-tavernOffset<4.8?'Войти в таверну':'';
    }
    on(action,'click',()=>{
      const label=nearbyAction();
      if(!label)return;
      const throughPortal=label==='ЛОББИ'||label==='НА ОСТРОВ';
      if(throughPortal){
        inLobby=!inLobby;
        if(!inLobby)lobby.leave().then(()=>records?.refresh());
        player.position.set(0,.017,portalZ[inLobby?'lobby':'home']-2.2);
        player.rotation.y=Math.PI;yaw=targetYaw=0;
      }else{
        inside=!inside;sounds?.door(inside);
        player.position.set(0,.017,inside?3.7:3.6+tavernOffset);
        player.rotation.y=inside?Math.PI:0;
      }
      const home=!inside&&!inLobby;
      zone=inside?scenery.indoorZone:inLobby?scenery.lobbyZone:scenery.outdoorZone;
      scenery.indoor.visible=inside;scenery.outdoor.visible=home;
      if(scenery.lobby)scenery.lobby.visible=inLobby;
      landscape.visible=sun.visible=moon.visible=groundShadows.visible=home;
      lightingAt=-Infinity;updateLighting(Date.now());
      jumpHeight=0;jumpVelocity=0;grounded=true;wingBoostUsed=false;action.hidden=true;action.blur();
      locationLabel.textContent=inside?'ТАВЕРНА':inLobby?'ЛОББИ':'ЛЕСНАЯ ПОЛЯНА';
      canvas.setAttribute('aria-label',inLobby?'Общее лобби Норы':'Стартовый остров Норы. Обзор поворачивается пальцем');
      for(const g of gusts)g.age=1;companion.reset();reset();
    });
    on(document,'visibilitychange',()=>{if(document.hidden)lobby.leave();});
    function resize(){
      const w=canvas.clientWidth,h=canvas.clientHeight;if(!w||!h)return;
      // Bound fill rate independently of orientation / Retina density. CSS stays full resolution.
      const ratio=Math.min(window.devicePixelRatio||1,mobile?1.25:1.5,Math.sqrt((mobile?420000:1600000)/(w*h)))*quality;
      if(w===renderWidth&&h===renderHeight&&Math.abs(ratio-renderRatio)<.001)return;
      renderWidth=w;renderHeight=h;renderRatio=ratio;
      renderer.setPixelRatio(ratio);renderer.setSize(w,h,false);
      camera.aspect=w/h;camera.updateProjectionMatrix();
      frameTotal=frameCount=0;qualityAt=0;
    }
    const observer=new ResizeObserver(resize);observer.observe(canvas);resize();
    const windMaterial=new T.MeshBasicMaterial({color:'#d5e4df',transparent:true,opacity:.09,depthWrite:false});
    const wind=new T.InstancedMesh(geometry,windMaterial,24);wind.frustumCulled=false;scene.add(wind);
    const gusts=Array.from({length:24},()=>({age:1,x:0,y:0,z:0,heading:0}));let gustIndex=0,gustTimer=0;
    function updateWind(dt,running){
      gustTimer+=dt;
      if(running&&gustTimer>.035){gustTimer=0;const g=gusts[gustIndex++%24],side=gustIndex%2?-.16:.16;
        g.age=0;g.heading=player.rotation.y;g.x=player.position.x+Math.cos(g.heading)*side;g.z=player.position.z-Math.sin(g.heading)*side;g.y=player.position.y+.35+(gustIndex%4)*.22;}
      for(let i=0;i<24;i++){const g=gusts[i];g.age+=dt;const fade=Math.max(0,1-g.age/.32);
        matrix.position.set(g.x,g.y,g.z);matrix.rotation.set(0,g.heading,0);matrix.scale.set(.012*fade,.012*fade,.16*fade);matrix.updateMatrix();wind.setMatrixAt(i,matrix.matrix);}
      wind.instanceMatrix.needsUpdate=true;
    }
    const target=new T.Vector3(), offset=new T.Vector3(), direction=new T.Vector3();
    const companion=window.NoraCompanion.mount(T,scene,geometry,root,player,move,()=>zone,reset);
    const records=window.NoraRecords?.mount(root,scenery,sounds,reset);
    function tick(time){
      if(disposed)return;const previousFrame=previous;const dt=previous?Math.min((time-previous)/1000,.05):0;previous=time;
      if(!document.hidden){
        // Sustained slow frames lower only drawing resolution, never simulation speed.
        const elapsed=previousFrame? (time-previousFrame)/1000 : 0;
        if(mobile&&elapsed>0&&elapsed<.25){frameTotal+=elapsed;frameCount++;}
        if(!qualityAt)qualityAt=time;
        if(mobile&&time-qualityAt>2500&&frameCount>30){
          const average=frameTotal/frameCount;
          const next=average>1/45?Math.max(.6,quality-.1):average<1/58?Math.min(1,quality+.05):quality;
          frameTotal=frameCount=0;qualityAt=time;
          if(Math.abs(next-quality)>.001){quality=next;resize();}
        }
        const smooth=1-Math.exp(-12*dt);yaw+=(targetYaw-yaw)*smooth;pitch+=(targetPitch-pitch)*smooth;
        let inputX=stick.x+(keys.has('KeyD')?1:0)-(keys.has('KeyA')?1:0);
        let inputZ=stick.z+(keys.has('KeyS')?1:0)-(keys.has('KeyW')?1:0);
        if(inputPaused()){inputX=inputZ=0;}
        const inputLength=Math.hypot(inputX,inputZ);if(inputLength<=.025){inputX=inputZ=0;}if(inputLength>1){inputX/=inputLength;inputZ/=inputLength;}
        // Movement is always relative to the visible camera, including selfie.
        // Turning the model must not rotate the camera or the input frame.
        const basis=yaw+(view===2?Math.PI:0);
        const sprinting=sprintTouch||keys.has('ShiftLeft')||keys.has('ShiftRight'),speed=sprinting?3.1:1.7;
        const wantedX=(inputX*Math.cos(basis)+inputZ*Math.sin(basis))*speed;
        const wantedZ=(-inputX*Math.sin(basis)+inputZ*Math.cos(basis))*speed;
        const response=1-Math.exp(-(inputLength>.025?20:28)*dt);
        velocityX+=(wantedX-velocityX)*response;velocityZ+=(wantedZ-velocityZ)*response;
        if(Math.hypot(velocityX,velocityZ)<.002){velocityX=velocityZ=0;}
        const dx=velocityX*dt,dz=velocityZ*dt;
        const oldX=player.position.x,oldZ=player.position.z;
        move(player.position,dx,dz,zone,jumpHeight);
        let floor=0;
        for(const box of zone.boxes){
          const top=box[4];
          if(top>floor&&top<=jumpHeight&&overlapsBox(player.position.x,player.position.z,box,FURNITURE_RADIUS))floor=top;
        }
        grounded=grounded&&jumpHeight===floor;
        if(dt>0&&!grounded){
          const gliding=wingBoostUsed&&jumpVelocity<=0;
          jumpVelocity-=(gliding?GLIDE_GRAVITY:GRAVITY)*dt;
          if(gliding)jumpVelocity=Math.max(-GLIDE_FALL_SPEED,jumpVelocity);
          jumpHeight+=jumpVelocity*dt;
          if(inside&&jumpHeight>TAVERN_JUMP_LIMIT){jumpHeight=TAVERN_JUMP_LIMIT;jumpVelocity=0;}
          if(jumpHeight<=floor){jumpHeight=floor;jumpVelocity=0;grounded=true;wingBoostUsed=false;sounds?.land(inside);}
        }
        player.position.y=.017+jumpHeight;
        character.animateWings(dt,!grounded,wingBoostUsed&&jumpVelocity>0);
        character.walk(!grounded?0:Math.hypot(player.position.x-oldX,player.position.z-oldZ),dt,sprinting);
        // Face actual travel, preserving the last heading when stopped/blocked.
        const travelledX=player.position.x-oldX,travelledZ=player.position.z-oldZ;
        const heading=Math.hypot(travelledX,travelledZ)>1e-5?Math.atan2(travelledX,travelledZ):player.rotation.y;
        const turn=Math.atan2(Math.sin(heading-player.rotation.y),Math.cos(heading-player.rotation.y));
        player.rotation.y+=turn*(1-Math.exp(-12*dt));
        if(scenery.carriedRecord){const angle=player.rotation.y;scenery.carriedRecord.position.set(player.position.x+Math.cos(angle)*.26+Math.sin(angle)*.2,player.position.y+.64,player.position.z-Math.sin(angle)*.26+Math.cos(angle)*.2);scenery.carriedRecord.rotation.y=angle;}
        playerShadow.position.set(player.position.x,.008,player.position.z);
        target.set(player.position.x,1.1+jumpHeight*.65,player.position.z);
        const wanted=(inside?4.6:(camera.aspect<.7?5.7:5.1))*Math.max(.04,pov/100);
        if(view===1){
          player.visible=false;playerShadow.visible=false;
          camera.position.set(player.position.x-Math.sin(yaw)*.22,1.51+jumpHeight,player.position.z-Math.cos(yaw)*.22);
          target.set(camera.position.x-Math.sin(yaw)*Math.cos(pitch),camera.position.y-Math.sin(pitch),camera.position.z-Math.cos(yaw)*Math.cos(pitch));
          camera.lookAt(target);
        }else{
          player.visible=true;playerShadow.visible=true;
          const cameraYaw=yaw+(view===2?Math.PI:0);
          direction.set(Math.sin(cameraYaw)*Math.cos(pitch),Math.sin(pitch),Math.cos(cameraYaw)*Math.cos(pitch));
          const safe=cameraDistance(target,direction,wanted,zone.cameraBoxes);
          if(actualDistance>safe)actualDistance=safe;
          if(safe<=actualDistance+.001&&safe<wanted-.001){
            // Never interpolate through a wall. Briefly hold release at corners
            // so alternating collision hits cannot pump the camera in and out.
            actualDistance=Math.min(actualDistance,safe);cameraRelease=.12;cameraSpeed=0;
          }else if(cameraRelease>0){cameraRelease=Math.max(0,cameraRelease-dt);}
          else{
            cameraSpeed+=(Math.min(3,(safe-actualDistance)*4)-cameraSpeed)*(1-Math.exp(-8*dt));
            actualDistance=Math.min(safe,actualDistance+cameraSpeed*dt);
          }
          const coverage=Math.max(0,Math.min(1,(actualDistance-1.4)/1.6));
          const fade=coverage*coverage*(3-2*coverage);
          // Hide immediately when the camera enters the body; restore only once
          // it is outside, without blending the thousands of overlapping cubes.
          opacity=fade<opacity?fade:Math.min(fade,opacity+(fade-opacity)*(1-Math.exp(-5*dt)));
          if(opacity>.999)opacity=1;
          character.setOpacity(opacity);
          offset.copy(direction).multiplyScalar(actualDistance);
          camera.position.copy(target).add(offset);camera.lookAt(target);
        }
        records?.update(inside,player.position.x,player.position.z,jumpHeight===0&&jumpVelocity===0,companion.panelOpen(),inLobby,nearLobbyDeck());
        syncRecordButton();
        const actionText=nearbyAction();
        if(action.hidden!==!actionText)action.hidden=!actionText;
        if(actionText&&action.textContent!==actionText){
          action.textContent=actionText;
          action.classList?.toggle('nora-portal-action',actionText==='ЛОББИ'||actionText==='НА ОСТРОВ');
        }
        if(inLobby)lobby.update(time,dt);
        updateWind(dt,sprinting&&Math.hypot(player.position.x-oldX,player.position.z-oldZ)>.001);
        const daylight=updateLighting(Date.now());
        const audioYaw=yaw+(view===2?Math.PI:0);
        const playing=inLobby?!!records?.lobbyPlaying():recordPlaying;
        if(playing!==audioPlaying){audioPlaying=playing;sounds?.playing(playing);}
        if(inLobby){
          const dx=lobbyDeck.x-player.position.x,dz=lobbyDeck.z-player.position.z;
          const distance=Math.hypot(dx,dz);
          sounds?.spatial({gain:.85*Math.max(0,1-distance/14),cutoff:16000,
            pan:.8*(dx*Math.cos(audioYaw)-dz*Math.sin(audioYaw))/Math.max(1,distance)});
          scenery.updatePortal(dt);
        }else{
          sounds?.spatial(tavernAcoustics(inside,player.position.x,
            player.position.z-(inside?0:tavernOffset),audioYaw));
          if(!inside)scenery.updatePortal?.(dt);
        }
        scenery.update?.(dt,inside,daylight,camera,playing&&(inLobby||!records||records.hasRecord()),inLobby);
        sounds?.update(inside,daylight,Math.hypot(player.position.x-oldX,player.position.z-oldZ),grounded);
        atmosphere.update(dt,daylight,inside||inLobby);
        companion.update(dt,camera);
        renderer.render(scene,camera);
      }
      raf=requestAnimationFrame(tick);
    }tick(0);
    function stop(){if(disposed)return;disposed=true;lobby.leave();sounds?.stop();cancelAnimationFrame(raf);controls.abort();observer.disconnect();resetStick();records?.dispose();companion.dispose();character.dispose();wind.dispose();windMaterial.dispose();atmosphere.dispose();scenery.dispose();landscape.dispose();groundShadows.dispose();geometry.dispose();material.dispose();sunMaterial.dispose();moonMaterial.dispose();shadowTexture.dispose();shadowGeo.dispose();shadowMat.dispose();renderer.dispose();}
    on(canvas,'webglcontextlost',e=>{e.preventDefault();stop();root.querySelector('.nora-world-help').textContent='Графика остановлена. Закрой и открой игру снова.';});
    return stop;
  }
  return {mount,move,cameraDistance,timeOfDay,createAtmosphere,tavernAcoustics};
})();
