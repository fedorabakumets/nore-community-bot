'use strict';
window.NoraCompanion = (() => {
  function create(T, scene, geometry, species) {
    const palette={cat:['#a39485','#eee2cc'],dog:['#ac784a','#e6c79b'],fox:['#c87946','#f0dbb5'],raccoon:['#7a8184','#cbd0c6'],dragon:['#65876d','#b5c69b']};
    const [fur,cream]=palette[species]||palette.cat, voxels=new Map(),unit=.055;
    function box(x0,x1,y0,y1,z0,z1,color,part=0){
      for(let x=x0;x<=x1;x++)for(let y=y0;y<=y1;y++)for(let z=z0;z<=z1;z++)
        if(x===x0||x===x1||y===y0||y===y1||z===z0||z===z1)voxels.set(`${part}:${x},${y},${z}`,{x,y,z,color,part});
    }
    box(-3,3,3,7,-5,3,fur);box(-2,2,3,4,-4,3,cream);
    box(-4,4,6,11,2,7,fur);box(-3,3,6,8,7,8,cream);
    box(-1,1,8,8,9,9,'#312e36');
    for(const side of [-1,1]){
      if(species==='raccoon')box(side*3-1,side*3+1,9,10,8,8,'#363a40');
      box(side*2,side*2,9,10,9,9,'#171e25');box(side*2,side*2,10,10,10,10,'#f1e7cd');
      const ear=species==='dog'?5:3;
      box(side*ear-1,side*ear+1,species==='dog'?6:11,species==='dog'?10:14,3,5,fur);
      if(species!=='dog')box(side*3,side*3,12,13,6,6,species==='dragon'?'#d1b17a':'#c68d91');
    }
    for(let leg=0;leg<4;leg++){
      const x=leg%2?2:-2,z=leg<2?2:-4;
      box(x-1,x+1,0,3,z-1,z+1,fur,leg+1);box(x-1,x+1,0,0,z,z+2,cream,leg+1);
    }
    for(let z=-10;z<=-6;z++)box(-1,1,5+(-z-6)/2,6+(-z-6)/2,z,z,
      species==='raccoon'&&z%2===0?'#343941':z<-8?cream:fur,5);
    if(species==='dragon'){
      for(const side of [-1,1])for(let i=0;i<4;i++)box(side*(4+i),side*(4+i),6+i,9+i,-3,-1,'#8d9d80');
      for(let z=-4;z<3;z+=2)box(0,0,8,9,z,z,'#c9b37c');
    }
    const material=new T.MeshLambertMaterial({color:0xffffff});
    const mesh=new T.InstancedMesh(geometry,material,voxels.size),body=new T.Group();body.name='nora-companion';body.add(mesh);scene.add(body);
    mesh.frustumCulled=false;mesh.instanceMatrix.setUsage(T.DynamicDrawUsage);
    const items=[...voxels.values()],o=new T.Object3D(),color=new T.Color();
    items.forEach((v,i)=>{color.set(v.color);mesh.setColorAt(i,color);});
    const pixels=['0110110','1111111','1111111','0111110','0011100','0001000'];
    const cells=[];pixels.forEach((row,y)=>[...row].forEach((v,x)=>{if(v==='1')cells.push([x-3,3-y]);}));
    const heartMaterial=new T.MeshBasicMaterial({transparent:true,opacity:0,depthWrite:false});
    const hearts=new T.InstancedMesh(geometry,heartMaterial,cells.length*5);hearts.name='nora-pet-hearts';hearts.frustumCulled=false;hearts.visible=false;scene.add(hearts);
    for(let i=0;i<hearts.count;i++){color.set(Math.floor(i/cells.length)%2?'#ef5c79':'#f59ac3');hearts.setColorAt(i,color);}
    let phase=0,petting=0,heartTime=2;const heartOrigin=new T.Vector3(),pixel=new T.Vector3();
    function stroke(){if(petting>0)return;petting=1.6;heartTime=0;heartOrigin.copy(body.position);}
    function animate(dt,distance,camera){
      phase+=distance*18;petting=Math.max(0,petting-dt);heartTime+=dt;
      const bounce=petting>0?Math.sin((1.6-petting)*Math.PI*3)*.04:Math.sin(phase*2)*Math.min(.018,distance*2);
      items.forEach((v,i)=>{
        let y=v.y*unit+bounce,z=v.z*unit;
        if(v.part>=1&&v.part<=4){const step=Math.sin(phase+(v.part===1||v.part===4?0:Math.PI));y+=Math.max(0,step)*Math.min(.06,distance*5);z+=step*Math.min(.045,distance*4);}
        let x=v.x*unit;if(v.part===5)x+=Math.sin(phase+petting*10)*(.02+(petting>0?.08:0));
        o.position.set(x,y,z);o.rotation.set(0,0,0);o.scale.setScalar(unit);o.updateMatrix();mesh.setMatrixAt(i,o.matrix);
      });mesh.instanceMatrix.needsUpdate=true;
      hearts.visible=body.visible&&heartTime<1.8;heartMaterial.opacity=.85*Math.max(0,1-heartTime/1.8);
      if(hearts.visible){
        for(let i=0;i<hearts.count;i++){
          const n=Math.floor(i/cells.length),cell=cells[i%cells.length];
          pixel.set(cell[0]*.027,cell[1]*.027,0).applyQuaternion(camera.quaternion);
          o.position.copy(heartOrigin).add(pixel);o.position.x+=Math.sin(n*2.4)*(.15+heartTime*.08);o.position.z+=Math.cos(n*2.4)*.12;
          o.position.y+=.72+n*.09+heartTime*.55;o.quaternion.copy(camera.quaternion);o.scale.set(.025,.025,.012);o.updateMatrix();hearts.setMatrixAt(i,o.matrix);
        }hearts.instanceMatrix.needsUpdate=true;
      }
    }
    return {body,stroke,animate,clear(){petting=0;heartTime=2;hearts.visible=false;},dispose(){scene.remove(body,hearts);mesh.dispose();hearts.dispose();material.dispose();heartMaterial.dispose();}};
  }

  function mount(T,scene,geometry,root,player,move,getZone,resetInput) {
    const controls=new AbortController(),on=(el,type,fn)=>el.addEventListener(type,fn,{signal:controls.signal});
    const actions=root.querySelector('.nora-pet-actions'),open=root.querySelector('.nora-pet-open'),stroke=root.querySelector('.nora-pet-stroke');
    const panel=root.querySelector('.nora-pet-panel'),content=panel.querySelector('.nora-pet-content'),message=panel.querySelector('.nora-pet-message');
    let pet=null,model=null,disposed=false,pending=false,flight=null,valid=false,near=false,route=[],timer=0;
    function reset(){if(!model)return;model.clear();model.body.position.copy(player.position);model.body.position.y=.017;move(model.body.position,.65,0,getZone());route=[new T.Vector3(player.position.x,.017,player.position.z)];}
    function apply(value){
      const species=pet?.species;pet=value;
      if(!pet||pet.expedition_until){model?.dispose();model=null;actions.hidden=true;near=false;return;}
      if(!model||species!==pet.species){model?.dispose();model=create(T,scene,geometry,pet.species);reset();}
    }
    function render(){
      if(!panel.open)return;
      const p=pet,disabled=!valid||pending||!p?.enabled||!!p?.expedition_until;
      content.innerHTML=p?`<h2>${esc(p.name)}</h2><p>${esc(p.species_label)}</p><label>Сытость: ${Number(p.hunger)||0} / 100<progress max="100" value="${Number(p.hunger)||0}"></progress></label><label>Вода: ${Number(p.thirst)||0} / 100<progress max="100" value="${Number(p.thirst)||0}"></progress></label><p>${p.expedition_until?'В походе до '+esc(new Date(p.expedition_until).toLocaleString('ru-RU',{timeZone:'Europe/Moscow'}))+' МСК':'Поход длится 24 часа. Питомец вернётся с находкой.'}</p>${!p.enabled?'<p>Походы временно отключены.</p>':''}<button type="button" class="nora-pet-expedition" ${disabled?'disabled':''}>${pending?'Отправляем…':p.expedition_until?'Питомец в походе':'Отправить в поход'}</button>`:'<p>Питомец пока не появился. Завести его можно в магазине.</p>';
    }
    async function refresh(){
      if(flight)return flight;
      flight=(async()=>{try{const response=await api('nora-game/pet');if(disposed)return;apply(response.pet);valid=true;if(typeof data!=='undefined'&&data)data.pet=pet;}
        catch(error){if(!disposed){valid=false;message.textContent=error.message;}}
        finally{flight=null;if(!disposed)render();}})();return flight;
    }
    on(open,'click',async()=>{if(!near||disposed)return;resetInput();message.textContent='';valid=false;panel.showModal();render();await refresh();});
    on(panel.querySelector('.nora-pet-close'),'click',()=>panel.close());
    on(panel,'close',resetInput);
    on(panel,'cancel',e=>e.stopPropagation());
    on(stroke,'click',()=>{if(near&&model){model.stroke();stroke.blur();}});
    on(content,'click',async event=>{
      if(!event.target.closest('.nora-pet-expedition')||pending||!valid||!pet?.enabled||pet.expedition_until)return;
      pending=true;message.textContent='';render();
      try{
        if(flight)await flight;if(disposed)return;
        const prepared=await api('pet/prepare',{action:'expedition'});if(disposed)return;
        const result=await api('pet/action',{token:prepared.token});if(disposed)return;
        if(!result.ok)throw Error(result.message||'Не удалось отправить питомца');
        model?.dispose();model=null;near=false;actions.hidden=true;valid=false;
        message.textContent=result.message;await refresh();
      }catch(error){if(!disposed){message.textContent=error.message;await refresh();}}
      finally{pending=false;if(!disposed)render();}
    });
    on(document,'visibilitychange',()=>{if(!document.hidden&&!pending)refresh();});
    refresh();
    function update(dt,camera){
      timer+=dt;if(timer>30){timer=0;if(!pending)refresh();}
      if(!model)return;
      const position=model.body.position,last=route[route.length-1];
      if(!last||Math.hypot(player.position.x-last.x,player.position.z-last.z)>.12)route.push(new T.Vector3(player.position.x,.017,player.position.z));
      if(route.length>160||position.distanceTo(player.position)>10)reset();
      const old=position.clone();
      // Follow the owner's recorded route, so corners and tavern furniture are respected.
      let remaining=position.distanceTo(route[0]);
      for(let i=1;i<route.length;i++)remaining+=route[i].distanceTo(route[i-1]);
      if(remaining>1.05){
        const target=route[0],dx=target.x-position.x,dz=target.z-position.z,distance=Math.hypot(dx,dz);
        if(distance<.06){if(route.length>1)route.shift();}
        else {const step=Math.min(distance,remaining-1.05,3.7*dt);move(position,dx/distance*step,dz/distance*step,getZone());}
      }
      const distance=position.distanceTo(old);
      if(distance>.0001){const heading=Math.atan2(position.x-old.x,position.z-old.z);model.body.rotation.y+=Math.atan2(Math.sin(heading-model.body.rotation.y),Math.cos(heading-model.body.rotation.y))*(1-Math.exp(-10*dt));}
      near=Math.hypot(position.x-player.position.x,position.z-player.position.z)<1.8;
      // Do not offer interaction across walls/furniture.
      const probe=position.clone();move(probe,player.position.x-probe.x,player.position.z-probe.z,getZone());near=near&&Math.hypot(probe.x-player.position.x,probe.z-player.position.z)<.1;
      actions.hidden=!near||panel.open;model.animate(dt,distance,camera);
    }
    return {update,reset,panelOpen:()=>panel.open,dispose(){disposed=true;controls.abort();if(panel.open)panel.close();model?.dispose();actions.hidden=true;}};
  }
  return {create,mount};
})();
