'use strict';
window.NoraBurrowTrail = (() => {
  async function load() {
    const response=await fetch('/nora-burrow-trail.json');
    if(!response.ok)throw Error(NoraI18n.t("Не удалось загрузить лесную дорожку."));
    return response.json();
  }

  function create(T,geometry,material,lobby,zone,layout) {
    const {start,first,spacing,doorZ,knockRadius,minZ,maxZ}=layout;
    const group=new T.Group(), plane=new T.PlaneGeometry(1,1);
    group.name='nora-burrow-trail';lobby.add(group);
    const tiles=new Map(), matrix=new T.Object3D(),color=new T.Color();
    const litMaterial=new T.MeshBasicMaterial({color:'#ffffff'});
    const boxStart=zone.boxes.length, cameraStart=zone.cameraBoxes.length;
    const edges=[
      [start+.34,1_000_001,minZ-5,minZ-.34],
      [start+.34,1_000_001,maxZ+.34,maxZ+8],
    ];
    const formatter=new Intl.NumberFormat(NoraI18n.locale);
    let houses=[],indices=new Map(),focus=-1;

    function blocksMesh(blocks,mat) {
      const mesh=new T.InstancedMesh(geometry,mat,blocks.length);
      blocks.forEach(([x,y,z,w,h,d,tint],i)=>{
        matrix.position.set(x,y,z);matrix.scale.set(w,h,d);matrix.updateMatrix();
        mesh.setMatrixAt(i,matrix.matrix);
        if(tint)mesh.setColorAt(i,color.set(tint));
      });
      mesh.computeBoundingSphere();
      return mesh;
    }
    function texture(width,height,paint) {
      const canvas=document.createElement('canvas');
      canvas.width=width;canvas.height=height;
      paint(canvas.getContext('2d'));
      const map=new T.CanvasTexture(canvas);
      map.colorSpace=T.SRGBColorSpace;map.anisotropy=4;
      return map;
    }
    function surface(map,w,h,transparent=false) {
      const mesh=new T.Mesh(plane,new T.MeshBasicMaterial({map,transparent,depthWrite:!transparent}));
      mesh.scale.set(w,h,1);
      return mesh;
    }
    function board(label,x,z) {
      const sign=surface(texture(640,128,ctx=>{
        ctx.fillStyle='#533a35';ctx.fillRect(0,0,640,128);
        ctx.fillStyle='#ae7954';ctx.fillRect(6,6,628,116);
        ctx.fillStyle='#43333a';ctx.fillRect(13,13,614,102);
        ctx.fillStyle='#ffdcaa';ctx.textAlign='center';ctx.font='bold 62px sans-serif';
        ctx.fillText(label,320,86,594);
      }),3.45,.69);
      sign.position.set(x,1.7,z+.085);
      const posts=blocksMesh([
        [x-1.27,.79,z,.13,1.58,.14,'#624638'],
        [x+1.27,.79,z,.13,1.58,.14,'#624638'],
        [x,1.7,z,3.45,.7,.15,'#6d4d3d'],
      ],material);
      zone.boxes.push([x-1.73,x+1.73,z-.08,z+.08,2.05]);
      zone.cameraBoxes.push([x-1.73,x+1.73,0,2.05,z-.08,z+.08]);
      group.add(posts,sign);
      return [posts,sign];
    }
    const signs=[
      ...board(NoraI18n.t("НОРКИ  →"),2.4,-1.9),
      ...board(NoraI18n.t("НОРКИ  →"),14,-2),
      ...board(NoraI18n.t("←  ПОРТАЛЫ И ЛАВКА"),-2.3,-1.9),
    ];
    const entrance=blocksMesh(Array.from({length:16},(_,i)=>
      [i+.5,.016,1.12,.98,.032,2.16,['#79747e','#685f6d','#827980'][i%3]]),material);
    group.add(entrance);
    const signBoxes=zone.boxes.slice(boxStart),signCameras=zone.cameraBoxes.slice(cameraStart);
    const glowMap=texture(96,96,ctx=>{
      const glow=ctx.createRadialGradient(48,48,0,48,48,48);
      glow.addColorStop(0,'rgba(255,193,117,.54)');
      glow.addColorStop(.48,'rgba(251,173,94,.23)');
      glow.addColorStop(1,'rgba(255,164,83,0)');
      ctx.fillStyle=glow;ctx.fillRect(0,0,96,96);
    });
    const lightPool=new T.MeshBasicMaterial({map:glowMap,transparent:true,depthWrite:false,polygonOffset:true,polygonOffsetFactor:-2});
    const lights=Array.from({length:2},()=>{
      const light=new T.PointLight('#ffc48a',17,7.4);
      light.visible=false;group.add(light);return light;
    });

    function groundName(house,x) {
      const {name,likes,cookies,messages}=house;
      const plaque=surface(texture(768,320,ctx=>{
        ctx.fillStyle='#827880';ctx.fillRect(0,0,768,320);
        ctx.fillStyle='#292631';ctx.fillRect(5,5,758,310);
        ctx.strokeStyle='#b19a81';ctx.lineWidth=2;ctx.strokeRect(12,12,744,296);
        ctx.textAlign='center';ctx.textBaseline='middle';ctx.font='bold 72px sans-serif';
        ctx.fillStyle='#141119';ctx.fillText(name,384,69,548);
        ctx.fillStyle='#ffe3b1';ctx.fillText(name,384,66,548);
        ctx.fillStyle='#736477';ctx.fillRect(128,113,512,2);
        if(likes===null){
          ctx.fillStyle='#e4d6cf';ctx.font='bold 37px sans-serif';
          ctx.fillText(NoraI18n.t("Счётчики скрыты"),384,212);return;
        }
        [[NoraI18n.t("Лайки"),likes],[NoraI18n.t("Печеньки"),cookies],[NoraI18n.t("Сообщения"),messages]].forEach(([label,value],i)=>{
          const y=154+i*54;
          ctx.textAlign='left';ctx.fillStyle='#ebd3b7';ctx.font='bold 38px sans-serif';
          ctx.fillText(label,145,y,238);
          ctx.textAlign='right';ctx.fillStyle='#fff3db';ctx.font='bold 46px sans-serif';
          ctx.fillText(formatter.format(value),623,y,222);
        });
      }),2.85,1.88);
      plaque.name='nora-house-plaque-'+name;
      plaque.rotation.x=-Math.PI/2;plaque.position.set(x,.056,-.76);
      return plaque;
    }
    function cottage(block,lit,x,index) {
      const facade=['#ac8462','#a99077','#9b7b66'][index%3];
      const roof=['#6e3b4e','#405a54','#6c4a41'][index%3];
      const centerZ=doorZ-1.65;
      const b=(dx,y,z,w,h,d,c)=>block(x+dx,y,z,w,h,d,c);
      b(0,.17,centerZ,4.36,.34,3.46,'#706370');
      b(0,1.3,centerZ-.08,4.08,2.32,3.12,facade);
      for(let row=0;row<6;row++)b(0,.41+row*.35,doorZ,4.06,.035,.05,'#6a504c');
      for(const edge of [-1,1]){
        b(edge*2.03,1.31,doorZ,.18,2.32,.16,'#513b37');
        b(edge*1.24,1.42,doorZ+.025,.91,.89,.14,'#4b363c');
        lit.push([x+edge*1.24,1.42,doorZ+.102,.7,.68,.04,'#d79b64']);
        b(edge*1.24,1.42,doorZ+.13,.065,.68,.04,'#684b45');
        b(edge*1.24,1.42,doorZ+.13,.7,.07,.04,'#684b45');
        b(edge*1.24,.91,doorZ+.08,1.02,.13,.29,'#754d4b');
      }
      b(0,1.17,doorZ+.095,1.15,1.98,.2,'#47323a');
      for(let slat=-2;slat<=2;slat++)
        b(slat*.177,1.18,doorZ+.205,.163,1.7,.05,slat%2?'#825441':'#95664b');
      b(0,2.16,doorZ+.2,1.28,.14,.29,'#6a483c');
      b(.32,1.03,doorZ+.253,.11,.11,.06,'#ecc37b');
      b(0,.11,doorZ+.31,1.32,.22,.64,'#a58b86');
      b(0,.045,doorZ+.65,1.57,.09,.66,'#887983');
      for(let step=0;step<7;step++){
        const side=2.37-step*.33;
        if(step>0)b(0,2.37+step*.173,centerZ,side*2,.19,3.62,facade);
        for(const sign of [-1,1])b(side*sign,2.52+step*.19,centerZ,.39,.21,3.96,roof);
      }
      b(0,3.85,centerZ,.52,.18,3.99,roof);
      b(1.24,3.19,centerZ-.77,.46,1.53,.44,'#796674');
      b(1.24,4,centerZ-.77,.61,.16,.59,'#968087');
    }
    function build(index,hasHouse,end) {
      const x=first+spacing*index,center=index===0?(start+x+spacing/2)/2:x;
      const width=index===0?x+spacing/2-start:spacing;
      const blocks=[],lit=[],emit=(...box)=>blocks.push(box);
      emit(center,-.27,(maxZ+minZ)/2,width,.54,maxZ-minZ,'#36474a');
      for(let n=0;n<Math.ceil(width);n++){
        const px=center-width/2+n+.5;
        for(let j=-2;j<3;j++)emit(Math.min(px,center+width/2-.46),.015,j+.5,.95,.03,.956,
          ['#817680','#6d6471','#776e78'][(n+j+5)%3]);
      }
      const boxes=[],cameras=[];
      function solid(x,z,w,d,h) {
        boxes.push([x-w/2,x+w/2,z-d/2,z+d/2]);
        cameras.push([x-w/2,x+w/2,0,h,z-d/2,z+d/2]);
      }
      function tree(x,z,height) {
        emit(x,height*.42,z,.45,height*.9,.5,'#493f48');
        for(let layer=0;layer<4;layer++){
          const s=2.62-layer*.56;
          emit(x,height*(.66+layer*.15),z,s,.69,s,['#304749','#365759','#4b6861','#58716a'][layer]);
        }
      }
      for(const side of [-1,1]){
        const z=side<0?minZ+.26:maxZ-.25;
        for(let i=0;i<4;i++)emit(center-width/2+width*(i+.5)/4,.22,z,width/4+.014,.44,.53,
          ['#4c535a','#63606b','#545a63'][(i+index)%3]);
        for(let i=0;i<3;i++){
          const px=center-width/2+width*(i+.65)/3;
          const pz=z+side*(.45+(index+i)%2*.5);
          tree(px,pz,3.2+(index+i)%3*.52);
        }
      }
      if(end){
        emit(x+4.75,-.33,-1,2.5,.66,13.5,'#36474a');
        for(let z=-6;z<=5;z++){
          emit(x+3.52,.23,z,.66,.46,1.05,z%3?'#59606a':'#68616c');
          if(z%2===0)tree(x+4.72,z,3.8+Math.abs(z%3)*.46);
        }
      }
      const lampX=x+1.72,lampZ=2.55;
      emit(lampX,.15,lampZ,.42,.3,.42,'#6b5a62');
      emit(lampX,1.12,lampZ,.13,2.24,.13,'#4a404d');
      for(const y of [2.13,2.64])emit(lampX,y,lampZ,.53,.12,.51,'#5a4550');
      for(const a of [-.21,.21])for(const b of [-.21,.21])emit(lampX+a,2.39,lampZ+b,.055,.49,.055,'#5a4550');
      lit.push([lampX,2.39,lampZ,.28,.39,.28,'#ffcf8f']);
      solid(lampX,lampZ,.36,.36,2.7);
      if(hasHouse){
        cottage(emit,lit,x,index);
        solid(x,doorZ-1.63,4.17,3.28,3.7);
        emit(x,.021,-.76,2.98,.042,2,'#6d626d');
      }
      const mesh=blocksMesh(blocks,material);
      const warm=blocksMesh(lit,litMaterial);
      const pool=new T.Mesh(plane,lightPool);
      pool.rotation.x=-Math.PI/2;pool.scale.set(6.25,6.25,1);pool.position.set(lampX,.049,lampZ-.68);
      group.add(mesh,warm,pool);
      return {mesh,warm,pool,boxes,cameras,lampX,lampZ,hasHouse,end};
    }
    function removePlaque(tile) {
      if(!tile.plaque)return;
      tile.plaque.removeFromParent();tile.plaque.material.map.dispose();tile.plaque.material.dispose();
      tile.plaque=null;
    }
    function clear(tile) {
      removePlaque(tile);tile.mesh.removeFromParent();tile.mesh.dispose();
      tile.warm.removeFromParent();tile.warm.dispose();tile.pool.removeFromParent();
    }
    function update(x) {
      const last=Math.max(0,houses.length-1);
      const current=Math.max(-2,Math.min(last,Math.round((x-first)/spacing)));
      if(focus===current&&tiles.size)return;
      focus=current;
      const low=Math.max(0,current-5),high=Math.min(last,current+5);
      for(const [index,tile] of tiles)if(index<low||index>high||tile.hasHouse!==!!houses[index]||tile.end!==(index===last)){
        clear(tile);tiles.delete(index);
      }
      zone.boxes.splice(boxStart,Infinity,...signBoxes,...edges);
      zone.cameraBoxes.splice(cameraStart,Infinity,...signCameras);
      for(let index=low;index<=high;index++){
        const house=houses[index];
        if(!tiles.has(index))tiles.set(index,build(index,!!house,index===last));
        const tile=tiles.get(index);
        const label=house&&JSON.stringify(house);
        if(house&&tile.label!==label){
          removePlaque(tile);tile.label=label;
          tile.plaque=groundName(house,first+index*spacing);group.add(tile.plaque);
        }
        zone.boxes.push(...tile.boxes);zone.cameraBoxes.push(...tile.cameras);
      }
      const closest=[...tiles.values()].sort((a,b)=>Math.abs(a.lampX-x)-Math.abs(b.lampX-x));
      lights.forEach((light,i)=>{
        const tile=closest[i];
        light.visible=!!tile&&Math.abs(tile.lampX-x)<20;
        if(tile)light.position.set(tile.lampX,2.37,tile.lampZ);
      });
    }
    function setHouses(next,x) {
      houses=next;
      indices=new Map(houses.map((house,i)=>[house.name,i]));
      zone.maxX=first+Math.max(0,houses.length-1)*spacing+spacing/2-.4;
      focus=null;update(x);
    }
    function nearby({x,z}) {
      const index=Math.round((x-first)/spacing),house=houses[index];
      if(!house||z<doorZ+.28)return null;
      const px=first+index*spacing;
      return Math.hypot(x-px,z-doorZ)<knockRadius-.3?{house,x:px,z:doorZ}:null;
    }
    function doorstep(name) {
      const index=indices.get(name);
      return index===undefined?null:{x:first+index*spacing,z:doorZ+1.45};
    }
    setHouses([],0);
    return {setHouses,update,nearby,doorstep,start,dispose(){
      for(const tile of tiles.values())clear(tile);
      for(const sign of signs){
        if(sign.isInstancedMesh)sign.dispose();
        else {sign.material.map.dispose();sign.material.dispose();}
      }
      entrance.dispose();plane.dispose();litMaterial.dispose();glowMap.dispose();lightPool.dispose();
      for(const light of lights)light.dispose();
      group.removeFromParent();
    }};
  }
  return {load,create};
})();
