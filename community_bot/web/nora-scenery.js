'use strict';
window.NoraScenery = (() => {
  const tavernOffset=-4.95, portalZ={home:6.75,lobby:9.75};
  function create(T, geometry, material) {
    let blocks = [], solids = [], cameraBoxes = [];
    const outdoorZone={limit:7.35, boxes:[], cameraBoxes:[]}, indoorZone={limitX:4.25,limitZ:4.55,boxes:[],cameraBoxes:[]};
    function box(x,y,z,w,h,d,color){blocks.push([x,y,z,w,h,d,color]);}
    function solid(x,y,z,w,h,d){solids.push([x-w/2,x+w/2,z-d/2,z+d/2]);cameraBoxes.push([x-w/2,x+w/2,y-h/2,y+h/2,z-d/2,z+d/2]);}
    function cameraOnly(x,y,z,w,h,d){cameraBoxes.push([x-w/2,x+w/2,y-h/2,y+h/2,z-d/2,z+d/2]);}
    function mesh(){const result=new T.InstancedMesh(geometry,material,blocks.length),o=new T.Object3D(),c=new T.Color();blocks.forEach(([x,y,z,w,h,d,color],i)=>{o.position.set(x,y,z);o.scale.set(w,h,d);o.updateMatrix();result.setMatrixAt(i,o.matrix);c.set(color);result.setColorAt(i,c);});result.computeBoundingSphere();return result;}
    function bush(x,z,size=1){for(let a=-2;a<=2;a++)for(let b=0;b<3;b++)for(let c=-2;c<=2;c++){if(Math.abs(a)+Math.abs(c)+b>4)continue;box(x+a*.22*size,.13+b*.22*size,z+c*.22*size,.215*size,.215*size,.215*size,['#3b7841','#519847','#70af51'][Math.abs(a+b+c)%3]);}}
    function flower(x,z,color){box(x,.2,z,.07,.4,.07,'#3c803f');box(x,.42,z,.12,.12,.12,'#f8cd70');for(const [a,b] of [[1,0],[-1,0],[0,1],[0,-1]])box(x+a*.11,.41,z+b*.11,.13,.1,.13,color);box(x+.1,.17,z,.22,.06,.1,'#65a749');}
    function tree(x,z,i){for(let y=0;y<9;y++)box(x,.15+y*.3,z,.38,.3,.38,y%3?'#805438':'#aa7950');for(let a=-3;a<=3;a++)for(let b=-2;b<=3;b++)for(let c=-3;c<=3;c++){if(Math.abs(a)+Math.abs(c)+Math.max(0,b)>7||(Math.abs(a)<3&&Math.abs(c)<3&&b>-2&&b<3))continue;box(x+a*.42,3.1+b*.42,z+c*.42,.43,.43,.43,['#3e7741','#508e48','#65a653','#80b15c'][Math.abs(a*7+b*3+c+i)%4]);}cameraOnly(x,2.5,z,2.8,4.8,2.8);}
    function distantTree(x,z,i){
      const h=3.8+(Math.abs(i*13)%7)*.3;
      box(x,.7,z,.5,2.4,.5,'#63795a');
      box(x,h*.65,z,2.5,h*.55,2.5,['#5b815c','#638764','#6c9168'][Math.abs(i)%3]);
      box(x-.65,h*.84,z+.25,1.5,h*.37,1.8,'#739671');
      box(x+.6,h*.72,z-.45,1.7,h*.45,1.6,'#648861');
    }
    // Dense natural perimeter, with forest terraces continuing into the fog.
    for(let edge=0;edge<4;edge++)for(let i=-7;i<=7;i++){
      const x=edge<2?i:(edge===2?-8:8),z=edge<2?(edge===0?-8:8):i;
      box(x,.32,z,1,.64,.65,i%3?'#788577':'#8a9482');bush(x,z,1.2);
      if(i%2===0)flower(x+(edge<2?.25:.6),z+(edge<2?.6:.25),i%4?'#e8b0c1':'#f1e2a1');
    }
    for(let edge=0;edge<4;edge++)for(let i=-2;i<=2;i++){
      const x=edge<2?i*3.6+(edge*.9):(edge===2?-10.5:10.5),z=edge<2?(edge===0?-10.5:10.5):i*3.6;
      tree(x,z,edge+i);bush(x+.8,z-1,1.4);
    }
    for(let x=-32;x<=32;x+=4)for(let z=-32;z<=32;z+=4){
      if(Math.abs(x)<10&&Math.abs(z)<10)continue;
      box(x,-1.4,z,4,1.8,4,['#629249','#6e9b50','#578d47'][Math.abs(x+z)%3]);
      if((x+z)%8===0){if(Math.max(Math.abs(x),Math.abs(z))<16)tree(x+.6,z+.4,x+z);else distantTree(x+.6,z+.4,x+z);}
    }
    // Staggered low-detail silhouettes close gaps without multiplying detailed foliage.
    for(const radius of [13,18,24,30])for(let edge=0;edge<4;edge++)for(let i=-radius;i<=radius;i+=2.7){
      const shift=Math.sin(i*7+edge)*.6;
      const x=edge<2?i+shift:(edge===2?-radius:radius),z=edge<2?(edge===0?-radius:radius):i+shift;
      distantTree(x,z,Math.round(i*3)+edge);
    }
    for(const [x,z] of [[-6,1],[5,-1],[4,4],[-4,4],[1,-5],[-4,-4]]){bush(x,z,.8);for(let i=0;i<3;i++)flower(x+.7+i*.23,z+.3-i*.3,['#eb939f','#e9c55f','#c7b2e6'][i]);}
    const tavernStart=blocks.length;
    // Tavern: pale irregular masonry, oak framing and a tiled stepped roof.
    for(let x=-11;x<=11;x++)for(let y=0;y<11;y++){
      const px=x*.25,py=.125+y*.25;
      for(const side of [-1,1]){
        if(side===1&&Math.abs(px)<.65&&py<2)continue;
        const window=Math.abs(Math.abs(px)-1.75)<.5&&py>.9&&py<1.95;
        if(!window)box(px,py,side*2.25,.25,.25,.25,['#d8c596','#c6b187','#e7d7ac','#b9a27d'][Math.abs(x*7+y*3)%4]);
      }
    }
    for(const side of [-1,1])for(let z=-8;z<=8;z++)for(let y=0;y<11;y++){
      const py=.125+y*.25;
      if(!(Math.abs(Math.abs(z*.25)-1)<.5&&py>.9&&py<1.95))box(side*2.875,py,z*.25,.25,.25,.25,['#d8c596','#c6b187','#e3cfa2'][Math.abs(z+y)%3]);
    }
    for(const x of [-2.75,2.75])for(const z of [-2.25,2.25])for(let y=0;y<11;y++)box(x,.125+y*.25,z,.4,.25,.4,y%3?'#8a8c80':'#a8a89a');
    for(const z of [-2.4,2.4])box(0,2.77,z,5.8,.18,.22,'#604333');
    for(let x=-12;x<=12;x++)for(let z=-10;z<=10;z++){
      const py=2.95+(12-Math.abs(x))*.16;
      box(x*.26,py,z*.26,.27,.18,.27,['#5b4144','#65484a','#73504d','#4c373f'][Math.abs(x*7+z*3)%4]);
      if(z===10&&Math.abs(x)<11)box(x*.26,py-.22,z*.26,.26,.3,.18,'#d4be93');
    }
    for(let x=-10;x<=10;x++)for(let y=2.9;y<2.85+(12-Math.abs(x))*.16;y+=.25)
      for(const z of [-2.25,2.25])box(x*.26,y,z,.26,.25,.25,(x+Math.round(y*4))%3?'#d4be93':'#b9a17b');
    box(0,3.7,2.4,.55,.65,.12,'#614333');box(0,3.7,2.48,.3,.4,.06,'#34282e');
    box(1.05,1.8,2.6,.22,.3,.22,'#edc57c');box(1.05,2,2.6,.32,.1,.32,'#594331');
    box(1.05,2.05,2.42,.12,.12,.48,'#594331');
    for(let y=0;y<9;y++)box(-1.7,3.45+y*.25,-1.2,.65,.25,.65,y%2?'#939081':'#b2ac96');box(-1.7,5.67,-1.2,.85,.2,.85,'#6d6c64');
    const windows=[];
    function facadeWindow(x,z,angle,index){
      const c=Math.cos(angle),n=Math.sin(angle);
      function detail(u,y,v,w,h,d,color){box(x+u*c+v*n,y,z-u*n+v*c,Math.abs(c)*w+Math.abs(n)*d,h,Math.abs(n)*w+Math.abs(c)*d,color);}
      detail(0,1.4,.13,1.05,1.12,.12,'#382931');
      windows.push({x:x+.22*n,z:z+.22*c,angle});
      for(const u of [-.55,.55])detail(u,1.4,.25,.15,1.25,.18,'#62442f');
      for(const y of [.82,1.98])detail(0,y,.25,1.25,.14,.18,'#76513a');
      detail(0,1.4,.29,.075,1.05,.08,'#48352d');detail(0,1.4,.29,1.05,.075,.08,'#48352d');
      detail(0,.78,.3,1.42,.16,.65,'#a48a60');
      for(const u of [-.43,.43])detail(u,.61,.16,.14,.3,.23,'#70503b');
      // Pots and a bottle sit directly on the sill rather than hovering.
      detail(-.3,.97,.38,.28,.22,.28,index%2?'#927054':'#ad7656');
      detail(-.3,1.16,.38,.18,.2,.18,'#6e8c50');detail(-.3,1.29,.38,.12,.1,.12,'#d9ae73');
      detail(.3,.99,.38,.14,.26,.14,'#58796c');detail(.3,1.16,.38,.08,.08,.08,'#7b9171');
    }
    for(const side of [-1,1])for(const x of [-1.75,1.75])facadeWindow(x,side*2.25,side===1?0:Math.PI,windows.length);
    for(const side of [-1,1])for(const z of [-1,1])facadeWindow(side*2.875,z,side*Math.PI/2,windows.length);
    // Timber ties, stone footing and eaves join the masonry and roof.
    for(const side of [-1,1]){
      box(0,.12,side*2.3,5.9,.24,.28,'#8d8c7b');box(side*2.9,.12,0,.28,.24,4.6,'#8d8c7b');
      box(side*2.9,2.77,0,.24,.2,4.9,'#604333');
    }
    for(let x=-2;x<=2;x++)box(x*.23,1,2.26,.23,2,.12,x%2?'#71503b':'#805c40');
    for(const x of [-.7,.7])box(x,1.05,2.4,.18,2.1,.2,'#503a30');box(0,2.1,2.4,1.6,.2,.2,'#503a30');box(.35,1,2.44,.12,.12,.12,'#cf9b4b');box(0,.04,2.7,1.7,.08,.5,'#b7b3a4');
    // Wooden hanging sign and paving leading to the door.
    box(2.3,2.6,2.5,.16,.16,.7,'#50392d');
    box(2.3,2.35,2.8,.12,.7,.12,'#50392d');box(1.95,2.6,2.8,.8,.12,.12,'#50392d');box(1.8,2.25,2.8,.75,.4,.13,'#90643c');box(1.8,2.25,2.88,.35,.08,.04,'#dfc38a');
    for(let z=3;z<7;z++)for(let x=-1;x<=1;x++)box(x*.45,.012,z*.8,.43,.025,.7,['#a8a99a','#b5b29c','#999f8b'][(x+z+3)%3]);
    solid(0,1.6,0,6,3.2,4.7);cameraOnly(0,3.8,0,6.6,2,5.6);
    for(const block of blocks.slice(tavernStart))block[2]+=tavernOffset;
    for(const window of windows)window.z+=tavernOffset;
    solids[0][2]+=tavernOffset;solids[0][3]+=tavernOffset;
    for(const bounds of cameraBoxes.slice(-2)){bounds[4]+=tavernOffset;bounds[5]+=tavernOffset;}
    // Original trees are solid too, including their canopies for the camera.
    for(const [x,z] of [[-5.7,-5.6],[5.2,-4.7],[-5.6,5.3],[5.5,5.7]]){solid(x,1,z,.6,2,.6);cameraOnly(x,2.8,z,3,2.6,3);}
    outdoorZone.boxes=solids;outdoorZone.cameraBoxes=cameraBoxes;
    const outdoor=mesh();
    const windowMaterial=new T.MeshBasicMaterial({color:'#ffffff'});
    const glow=new T.InstancedMesh(geometry,windowMaterial,windows.length),windowMatrix=new T.Object3D(),warm=new T.Color();
    glow.name='nora-tavern-windows';glow.frustumCulled=false;
    windows.forEach((w,i)=>{windowMatrix.position.set(w.x,1.4,w.z);windowMatrix.rotation.y=w.angle;windowMatrix.scale.set(.97,1.03,.04);windowMatrix.updateMatrix();glow.setMatrixAt(i,windowMatrix.matrix);glow.setColorAt(i,warm.set('#e8ad62'));});
    outdoor.add(glow);
    blocks=[];solids=[];cameraBoxes=[];
    // Separate furnished room: the roof stays overhead and never obscures its contents.
    for(let x=-9;x<=9;x++)for(let z=-10;z<=10;z++)box(x*.5,-.08,z*.5,.49,.16,.49,(x+z)%3?'#956b46':'#a97d51');
    for(const x of [-4.7,4.7]){box(x,1.7,0,.3,3.4,10.4,'#ad916b');solid(x,1.7,0,.3,3.4,10.4);}
    for(const z of [-5.2,5.2]){box(0,1.7,z,9.6,3.4,.3,'#c6ab80');solid(0,1.7,z,9.6,3.4,.3);}
    box(0,3.6,0,9.7,.25,10.7,'#604532');cameraOnly(0,3.6,0,9.7,.25,10.7);
    for(let z=-4;z<=4;z+=2)box(0,3.38,z,9.4,.22,.25,'#513a2d');
    for(const x of [-4.45,4.45])for(let y=.25;y<=3.25;y+=.5)box(x,y,0,.12,.07,10,'#816548');
    function furniture(x,y,z,w,h,d,color){box(x,y,z,w,h,d,color);solid(x,y,z,w,h,d);}
    function barrel(x,z){for(let y=0;y<4;y++){box(x,.13+y*.26,z,y===0||y===3?.65:.78,.26,y===0||y===3?.65:.78,'#91613b');}for(const y of [.25,.78])box(x,y,z,.81,.08,.81,'#55504a');solid(x,.5,z,.85,1,.85);}
    function chair(x,z){cameraOnly(x,.6,z,.65,1.2,.65);furniture(x,.38,z,.55,.14,.55,'#7c5035');box(x,.8,z-.23,.55,.8,.12,'#6c482f');for(const a of [-.2,.2])for(const b of [-.2,.2])box(x+a,.18,z+b,.1,.36,.1,'#62412d');}
    for(const [x,z] of [[-2.2,1.5],[2.25,.5],[1.9,-2.7]]){
      furniture(x,.85,z,1.6,.18,1.25,'#855a37');for(const a of [-.6,.6])for(const b of [-.45,.45])box(x+a,.4,z+b,.16,.8,.16,'#69482f');
      chair(x-.25,z+1.1);chair(x+.25,z-1.1);
      box(x-.35,1,z+.15,.24,.16,.24,'#d8be8c');box(x+.35,1,z-.25,.16,.3,.16,'#5b7541');box(x+.25,.97,z+.22,.4,.06,.3,'#c89d67');
    }
    furniture(-3.1,.65,-2.6,1.25,1.3,3.6,'#765033');box(-3.1,1.34,-2.6,1.55,.15,3.8,'#ab7a48');
    for(let z=-4;z<=-1;z+=.45)box(-3.1,1.57,z,.16,.32,.16,z%1?'#64805a':'#b8915b');
    for(const [x,z] of [[-3.6,4],[3.6,3.8],[-3.7,-4.4],[3.6,-4.4]])barrel(x,z);
    // Collection rack replaces the fireplace: records below, trophies and finds above.
    furniture(.1,1.42,-4.78,2.7,2.84,.38,'#49372d');
    for(const x of [-1.25,1.45])box(x,1.42,-4.45,.14,2.84,.64,'#b08a56');
    for(const y of [.14,.98,1.82,2.76])box(.1,y,-4.4,2.7,.13,.8,'#977044');
    for(const x of [-.6,.8])box(x,1.45,-4.5,.08,.65,.45,'#765339');
    box(.1,2.88,-4.52,2.9,.16,.78,'#c09b65');
    for(const x of [-3.8,3.8]){box(x,2.3,-4.95,1.2,.12,.35,'#65452e');for(let i=0;i<4;i++)box(x-.4+i*.25,2.5,-4.88,.14,.32,.14,['#748352','#b16f4e','#d0ac72','#577373'][i]);}
    // Scattered sacks, books, crates and rugs retain a clear center aisle.
    furniture(3.7,.3,-2.2,.7,.6,.7,'#9a7044');box(3.7,.64,-2.2,.75,.1,.75,'#6b4c34');
    for(const [x,z] of [[-4,2.5],[3.7,2],[-2.2,-4.4]]){box(x,.22,z,.55,.44,.45,'#baa57c');box(x,.47,z,.24,.1,.24,'#8d7958');solid(x,.22,z,.55,.44,.45);}
    box(0,.012,1.2,1.2,.02,3.8,'#923f43');for(let z=-.5;z<=3;z+=.3)box(0,.027,z,1.1,.01,.05,'#c7a26c');
    box(0,1.1,5.02,1.5,2.2,.08,'#76503a');box(.45,1,4.95,.12,.12,.12,'#d9ad5f');
    // Record console on four feet in the middle of the room.
    furniture(0,.55,0,1.15,.7,.84,'#704832');box(0,.94,0,1.27,.12,.94,'#aa7c4c');
    for(const x of [-.46,.46])for(const z of [-.3,.3])box(x,.12,z,.14,.24,.14,'#513a2d');
    box(0,.55,.43,.87,.42,.035,'#392e2b');
    for(let x=-3;x<=3;x++)box(x*.115,.55,.46,.035,.34,.025,'#bb945b');
    box(.39,1.05,-.21,.08,.12,.08,'#d0ae6c');box(.28,1.11,-.06,.28,.045,.045,'#d0ae6c');box(.16,1.09,.02,.055,.07,.12,'#d0ae6c');
    indoorZone.boxes=solids;indoorZone.cameraBoxes=cameraBoxes;
    const indoor=mesh();indoor.visible=false;
    const discGeometry=new T.CylinderGeometry(.38,.38,.035,32),discMaterial=new T.MeshLambertMaterial({color:'#242329'});
    const record=new T.Mesh(discGeometry,discMaterial);record.name='nora-record';record.position.set(-.08,1.025,0);indoor.add(record);
    const labelGeometry=new T.CylinderGeometry(.12,.12,.01,24),labelMaterial=new T.MeshBasicMaterial({color:'#b56d69'});
    const label=new T.Mesh(labelGeometry,labelMaterial);label.position.y=.023;record.add(label);
    const mark=new T.Mesh(geometry,labelMaterial);mark.position.set(.24,.022,0);mark.scale.set(.11,.012,.035);record.add(mark);
    let recordsDisposed=false,coverTexture=null;
    const coverMaterial=new T.MeshLambertMaterial({color:'#b94b67'});
    const recordFaceGeometry=new T.CircleGeometry(.378,32);
    const recordFace=new T.Mesh(recordFaceGeometry,coverMaterial);recordFace.rotation.x=-Math.PI/2;recordFace.position.y=.019;recordFace.visible=false;record.add(recordFace);
    if(window.NoraRecords&&typeof Image!=='undefined'){
      const image=new Image();image.onload=()=>{
        if(recordsDisposed)return;
        const canvas=document.createElement('canvas');canvas.width=canvas.height=48;
        window.NoraRecords.drawCover(canvas.getContext('2d'),image);
        coverTexture=new T.CanvasTexture(canvas);coverTexture.magFilter=T.NearestFilter;coverTexture.minFilter=T.NearestFilter;coverTexture.colorSpace=T.SRGBColorSpace;
        coverMaterial.map=coverTexture;coverMaterial.color.set('#ffffff');coverMaterial.needsUpdate=true;
      };image.src='/game/dedzytwo-cover.png';
    }
    const sleeveGeometry=new T.BoxGeometry(.56,.56,.045),faceGeometry=new T.PlaneGeometry(.5,.5);
    function sleeve(id){
      const group=new T.Group(),jacket=new T.Mesh(sleeveGeometry,id==='dedzytwo'?coverMaterial:labelMaterial);
      group.add(jacket);
      if(id==='dedzytwo'){const face=new T.Mesh(faceGeometry,coverMaterial);face.position.z=.026;group.add(face);}
      const vinyl=new T.Mesh(discGeometry,discMaterial);vinyl.rotation.x=Math.PI/2;vinyl.position.set(.22,0,0);vinyl.scale.setScalar(.68);group.add(vinyl);
      const sticker=new T.Mesh(labelGeometry,id==='dedzytwo'?coverMaterial:labelMaterial);sticker.position.y=.023;vinyl.add(sticker);
      return group;
    }
    const shelfRecords={};
    for(const id of ['standard','dedzytwo']){const item=sleeve(id);item.name='nora-shelf-'+id;item.position.set(id==='standard'?-.53:.58,.6,-4.13);item.visible=false;indoor.add(item);shelfRecords[id]=item;}
    const carriedRecord=new T.Group();carriedRecord.name='nora-carried-record';
    const carried={standard:sleeve('standard'),dedzytwo:sleeve('dedzytwo')};
    for(const item of Object.values(carried)){item.scale.setScalar(.65);item.visible=false;carriedRecord.add(item);}
    function setRecords(state){
      record.visible=!!state.player;
      recordFace.visible=state.player==='dedzytwo';
      label.visible=mark.visible=state.player!=='dedzytwo';
      for(const id of ['standard','dedzytwo']){shelfRecords[id].visible=state.shelf.includes(id);carried[id].visible=state.hand===id;}
    }
    const noteMaterial=new T.MeshBasicMaterial({color:'#ffffff',transparent:true,depthWrite:false});
    const notes=new T.InstancedMesh(geometry,noteMaterial,12*4),o=new T.Object3D();notes.name='nora-music-notes';notes.frustumCulled=false;indoor.add(notes);
    notes.instanceMatrix.setUsage(T.DynamicDrawUsage);let elapsed=0;
    const reduced=window.matchMedia?.('(prefers-reduced-motion: reduce)').matches||false;
    const colors=['#e6ad69','#b989bd','#77b8ad','#d77d84','#a7ba71','#8ba7cd'];
    function update(dt,inside,daylight,camera,playing=true){
      elapsed+=dt;
      if(!inside){
        windows.forEach((w,i)=>{const pulse=reduced?1:.94+.045*Math.sin(elapsed*1.3+i*2.1)+.015*Math.sin(elapsed*2.7+i);warm.set('#edb86d').multiplyScalar(pulse*(1-daylight*.22));glow.setColorAt(i,warm);});
        glow.instanceColor.needsUpdate=true;
      }
      notes.visible=playing;
      if(!inside||!playing)return;
      if(!reduced)record.rotation.y-=dt*1.45;
      for(let i=0;i<12;i++){
        const phase=(elapsed*.28+i/12)%1,fade=Math.sin(phase*Math.PI),a=i*2.399;
        const x=-.08+Math.sin(a+phase*2)*(.12+phase*.35),y=1.12+phase*1.85,z=Math.cos(a+phase*2)*(.1+phase*.25);
        // Four cubes make a beamed eighth note, facing the active camera.
        for(let part=0;part<4;part++){
          o.position.set(x,y,z);if(camera)o.quaternion.copy(camera.quaternion);
          const u=[-.035,.015,.06,.085][part],v=[-.045,.045,.115,.08][part];
          o.translateX(u);o.translateY(v);o.scale.set((part===0?.085:part===1?.025:.07)*fade,(part===1?.18:.035)*fade,.025*fade);
          if(reduced)o.scale.setScalar(0);
          o.updateMatrix();notes.setMatrixAt(i*4+part,o.matrix);notes.setColorAt(i*4+part,warm.set(colors[i%colors.length]).multiplyScalar(.5+.5*fade));
        }
      }
      notes.instanceMatrix.needsUpdate=true;notes.instanceColor.needsUpdate=true;
    }
    blocks=[];solids=[];cameraBoxes=[];
    const lobbyZone={limitX:16.35,limitZ:11.35,boxes:solids,cameraBoxes};
    for(let x=-18;x<18;x++)for(let z=-13;z<13;z++){
      const tone=Math.abs(x*17+z*13)%3;
      box(x+.5,-.25,z+.5,1,.5,1,['#3e4949','#414d4e','#374447'][tone]);
      if(Math.abs(x+.5)>16.5||Math.abs(z+.5)>11.5)
        box(x+.5,-.85,z+.5,1,.7,1,'#34343e');
      if(x===0||x===-1||z===0||z===-1||(
        x>=-11&&x<11&&z>=-7&&z<7&&(x===-11||x===10||z===-7||z===6)))
        box(x+.5,.015,z+.5,.96,.03,.96,['#626071','#777384','#555765'][tone]);
    }
    for(let x=-26;x<26;x+=2)for(let z=-22;z<22;z+=2){
      if(Math.abs(x+.5)<18&&Math.abs(z+.5)<13)continue;
      box(x+1,-1.35,z+1,2,1.45,2,(x+z)%3?'#313a40':'#354047');
    }
    for(let edge=0;edge<4;edge++){
      const end=edge<2?18:13;
      for(let i=-end;i<=end;i++){
        const x=edge<2?i:(edge===2?-17:17),z=edge<2?(edge===0?-12:12):i;
        box(x,.25,z,1.03,.5,.85,i%3?'#4f535f':'#636173');
        if(i%2===0)bush(x,z,.85);
      }
      for(let i=-end;i<=end;i+=3){
        const x=edge<2?i:(edge===2?-19:19),z=edge<2?(edge===0?-14:14):i;
        for(const layer of [0,1]){
          const start=blocks.length;
          distantTree(x+(edge<2?layer:Math.sign(x)*layer*5),z+(edge<2?Math.sign(z)*layer*5:layer),i+edge);
          const height=1.1+Math.abs(i*7+edge*3+layer*5)%9*.31;
          for(const [index,block] of blocks.slice(start).entries()){
            block[1]*=height;block[4]*=height;
            block[6]=['#3e3547','#303f48','#3f5258','#35454d'][index];
          }
        }
      }
    }
    const flameMaterial=new T.MeshBasicMaterial({color:'#ffd18a'});
    const lanterns=new T.Group();
    for(const x of [-12,-4,4,12])for(const z of [-5,5]){
      box(x,.39,z,2.25,.15,.65,'#624943');
      box(x,.67,z-.28,2.25,.48,.12,'#59454a');
      for(const dx of [-.85,.85])box(x+dx,.16,z,.18,.32,.53,'#797282');
      solid(x,.45,z,2.25,.9,.65);
      const lx=x+Math.sign(x)*1.8;
      box(lx,1.05,z,.17,2.1,.17,'#3f3b4b');
      for(const y of [1.83,2.37])box(lx,y,z,.48,.12,.48,'#4d4757');
      for(const dx of [-.2,.2])for(const dz of [-.2,.2])box(lx+dx,2.1,z+dz,.05,.49,.05,'#534759');
      solid(lx,1,z,.32,2,.32);
      const flame=new T.Mesh(geometry,flameMaterial);
      flame.position.set(lx,2.1,z);flame.scale.set(.29,.42,.29);lanterns.add(flame);
      const light=new T.PointLight('#ffc082',7,4.5);light.position.copy(flame.position);lanterns.add(light);
    }
    const lobby=mesh();lobby.add(lanterns);lobby.visible=false;
    const portal=new T.Group();
    portal.name='nora-world-portal';
    // Stepped stone surround and brass inlays from the NORA cover.
    blocks=[];
    const stone=['#58675c','#69776a','#48574e'];
    const brass='#ba9b60';
    box(0,.07,0,2.60,.14,.76,stone[2]);
    box(0,2.75,0,1.66,.38,.71,stone[0]);
    box(0,2.91,0,1.66,.06,.72,stone[1]);
    for(const side of [-1,1]){
      box(side*1.07,1.13,0,.45,2.06,.65,stone[2]);
      box(side*1.17,1.13,0,.24,2.06,.73,stone[0]);
      box(side*.91,2.24,0,.48,.38,.68,stone[1]);
      box(side*.72,2.51,0,.48,.26,.70,stone[0]);
      box(side*1.09,.19,0,.42,.15,.75,stone[1]);
      for(const y of [.52,1.47])box(side*1.05,y,0,.38,.13,.75,brass);
      for(const y of [.83,1.82])box(side*1.12,y,0,.28,.034,.74,stone[1]);
      box(0,2.74,side*.365,.39,.16,.03,brass);
      box(0,2.74,side*.383,.12,.08,.015,'#d6b77c');
    }
    const portalStone=mesh();
    const rimMaterial=new T.MeshBasicMaterial({color:'#542232'});
    const coreMaterial=new T.MeshBasicMaterial({color:'#ac4959'});
    const highlightMaterial=new T.MeshBasicMaterial({
      color:'#ffb38d',transparent:true,opacity:.66,depthWrite:false,
    });
    function portalBox(mat,x,y,z,w,h,d){
      const part=new T.Mesh(geometry,mat);part.position.set(x,y,z);part.scale.set(w,h,d);portal.add(part);return part;
    }
    // Recessed wine-red edge, rose-colored surface, and an offset pixel reflection.
    for(const [mat,width,bottom,shoulder,top,depth] of [
      [rimMaterial,1.86,.12,2.27,2.61,.34],
      [coreMaterial,1.51,.15,2.06,2.45,.38],
    ]){
      portalBox(mat,0,(bottom+shoulder)/2,0,width,shoulder-bottom,depth);
      portalBox(mat,0,(shoulder+top)/2,0,width-.52,top-shoulder,depth);
    }
    for(const side of [-1,1])for(const [x,y,w,h] of [
      [-.33,.40,.14,.16],[-.33,.96,.14,.76],[-.22,1.43,.36,.18],[-.07,1.66,.14,.32],
    ])portalBox(highlightMaterial,x*side,y,side*.196,w,h,.012);
    const portalLight=new T.PointLight('#ef6575',8,5);
    portalLight.position.set(0,1.32,-.45);portal.add(portalLight);
    const lobbyPortal=portal.clone(), lobbyPortalStone=portalStone.clone();
    portal.add(portalStone);lobbyPortal.add(lobbyPortalStone);
    portal.position.z=portalZ.home;lobbyPortal.position.z=portalZ.lobby;
    outdoor.add(portal);lobby.add(lobbyPortal);
    for(const [zone,z] of [[outdoorZone,portalZ.home],[lobbyZone,portalZ.lobby]]){
      zone.boxes.push([-1.3,1.3,z-.38,z+.38]);
      zone.cameraBoxes.push([-1.3,1.3,0,2.94,z-.38,z+.38]);
    }
    let portalTime=0;
    function updatePortal(dt){
      if(reduced)return;
      portalTime+=dt;
      highlightMaterial.opacity=.61+.13*Math.sin(portalTime*2);
    }
    return {outdoor,indoor,lobby,lobbyZone,updatePortal,outdoorZone,indoorZone,update,setRecords,carriedRecord,dispose(){recordsDisposed=true;coverTexture?.dispose();coverMaterial.dispose();recordFaceGeometry.dispose();sleeveGeometry.dispose();faceGeometry.dispose();outdoor.dispose();indoor.dispose();lobby.dispose();flameMaterial.dispose();portalStone.dispose();lobbyPortalStone.dispose();rimMaterial.dispose();coreMaterial.dispose();highlightMaterial.dispose();glow.dispose();windowMaterial.dispose();notes.dispose();noteMaterial.dispose();discGeometry.dispose();discMaterial.dispose();labelGeometry.dispose();labelMaterial.dispose();}};
  }
  return {create,tavernOffset,portalZ};
})();
