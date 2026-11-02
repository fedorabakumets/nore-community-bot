'use strict';
window.NoraScenery = (() => {
  function create(T, geometry, material) {
    let blocks = [], solids = [], cameraBoxes = [];
    const outdoorZone={limit:7.35, boxes:[], cameraBoxes:[]}, indoorZone={limitX:4.25,limitZ:4.55,boxes:[],cameraBoxes:[]};
    function box(x,y,z,w,h,d,color){blocks.push([x,y,z,w,h,d,color]);}
    function solid(x,y,z,w,h,d){solids.push([x-w/2,x+w/2,z-d/2,z+d/2]);cameraBoxes.push([x-w/2,x+w/2,y-h/2,y+h/2,z-d/2,z+d/2]);}
    function cameraOnly(x,y,z,w,h,d){cameraBoxes.push([x-w/2,x+w/2,y-h/2,y+h/2,z-d/2,z+d/2]);}
    function mesh(){const result=new T.InstancedMesh(geometry,material,blocks.length),o=new T.Object3D(),c=new T.Color();blocks.forEach(([x,y,z,w,h,d,color],i)=>{o.position.set(x,y,z);o.scale.set(w,h,d);o.updateMatrix();result.setMatrixAt(i,o.matrix);c.set(color);result.setColorAt(i,c);});result.computeBoundingSphere();return result;}
    function bush(x,z,size=1){for(let a=-2;a<=2;a++)for(let b=0;b<3;b++)for(let c=-2;c<=2;c++){if(Math.abs(a)+Math.abs(c)+b>4)continue;box(x+a*.22*size,.13+b*.22*size,z+c*.22*size,.23*size,.23*size,.23*size,['#3b7841','#519847','#70af51'][Math.abs(a+b+c)%3]);}}
    function flower(x,z,color){box(x,.2,z,.07,.4,.07,'#3c803f');box(x,.42,z,.12,.12,.12,'#f8cd70');for(const [a,b] of [[1,0],[-1,0],[0,1],[0,-1]])box(x+a*.11,.41,z+b*.11,.13,.1,.13,color);box(x+.1,.17,z,.22,.06,.1,'#65a749');}
    function tree(x,z,i){for(let y=0;y<9;y++)box(x,.15+y*.3,z,.38,.3,.38,y%3?'#805438':'#aa7950');for(let a=-3;a<=3;a++)for(let b=-2;b<=3;b++)for(let c=-3;c<=3;c++){if(Math.abs(a)+Math.abs(c)+Math.max(0,b)>7||(Math.abs(a)<3&&Math.abs(c)<3&&b>-2&&b<3))continue;box(x+a*.42,3.1+b*.42,z+c*.42,.43,.43,.43,['#3e7741','#508e48','#65a653','#80b15c'][Math.abs(a*7+b*3+c+i)%4]);}cameraOnly(x,2.5,z,2.8,4.8,2.8);}
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
    for(let x=-20;x<=20;x+=4)for(let z=-20;z<=20;z+=4){
      if(Math.abs(x)<10&&Math.abs(z)<10)continue;
      box(x,-1.4,z,4,1.8,4,['#629249','#6e9b50','#578d47'][Math.abs(x+z)%3]);
      if((x+z)%8===0)tree(x+.6,z+.4,x+z);
    }
    for(const [x,z] of [[-6,1],[5,-1],[4,4],[-4,4],[1,-5],[-4,-4]]){bush(x,z,.8);for(let i=0;i<3;i++)flower(x+.7+i*.23,z+.3-i*.3,['#eb939f','#e9c55f','#c7b2e6'][i]);}
    // Center tavern: pale irregular masonry, oak framing and a tiled stepped roof.
    for(let x=-11;x<=11;x++)for(let y=0;y<11;y++){
      const px=x*.25,py=.125+y*.25;
      for(const side of [-1,1]){
        if(side===1&&Math.abs(px)<.65&&py<2)continue;
        const window=side===1&&Math.abs(Math.abs(px)-1.75)<.5&&py>.9&&py<1.95;
        if(!window)box(px,py,side*2.25,.25,.25,.25,['#d8c596','#c6b187','#e7d7ac','#b9a27d'][Math.abs(x*7+y*3)%4]);
      }
    }
    for(const side of [-1,1])for(let z=-8;z<=8;z++)for(let y=0;y<11;y++)box(side*2.875,.125+y*.25,z*.25,.25,.25,.25,['#d8c596','#c6b187','#e3cfa2'][Math.abs(z+y)%3]);
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
    for(let y=0;y<6;y++)box(-1.7,4.2+y*.25,-1.2,.65,.25,.65,y%2?'#939081':'#b2ac96');box(-1.7,5.67,-1.2,.85,.2,.85,'#6d6c64');
    for(const x of [-1.75,1.75]){
      box(x,1.4,2.39,.95,.95,.08,'#382931');box(x,1.4,2.46,.75,.7,.05,'#af7547');
      for(const dx of [-.5,.5])box(x+dx,1.4,2.48,.15,1.15,.17,'#70503b');
      for(const y of [.88,1.92])box(x,y,2.48,1.15,.16,.2,'#76513a');
      box(x,1.4,2.5,.09,.9,.08,'#48352d');box(x,1.4,2.5,.9,.09,.08,'#48352d');
    }
    for(let x=-2;x<=2;x++)box(x*.23,1,2.26,.23,2,.12,x%2?'#71503b':'#805c40');
    for(const x of [-.7,.7])box(x,1.05,2.4,.18,2.1,.2,'#503a30');box(0,2.1,2.4,1.6,.2,.2,'#503a30');box(.35,1,2.44,.12,.12,.12,'#cf9b4b');box(0,.04,2.7,1.7,.08,.5,'#b7b3a4');
    // Wooden hanging sign and paving leading to the door.
    box(2.3,2.35,2.8,.12,.7,.12,'#50392d');box(1.95,2.6,2.8,.8,.12,.12,'#50392d');box(1.8,2.25,2.8,.75,.4,.13,'#90643c');box(1.8,2.25,2.88,.35,.08,.04,'#dfc38a');
    for(let z=3;z<7;z++)for(let x=-1;x<=1;x++)box(x*.45,.012,z*.8,.43,.025,.7,['#a8a99a','#b5b29c','#999f8b'][(x+z+3)%3]);
    solid(0,1.6,0,6,3.2,4.7);cameraOnly(0,3.8,0,6.6,2,5.6);
    // Original trees are solid too, including their canopies for the camera.
    for(const [x,z] of [[-5.7,-5.6],[5.2,-4.7],[-5.6,5.3],[5.5,5.7]]){solid(x,1,z,.6,2,.6);cameraOnly(x,2.8,z,3,2.6,3);}
    outdoorZone.boxes=solids;outdoorZone.cameraBoxes=cameraBoxes;
    const outdoor=mesh();blocks=[];solids=[];cameraBoxes=[];
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
    // Fireplace, mantle, logs and glowing embers at the far wall.
    furniture(.1,.8,-4.7,1.75,1.6,.65,'#77776c');box(.1,.65,-4.32,1.1,.95,.1,'#342a27');box(.1,.32,-4.18,.9,.18,.35,'#70472f');box(-.1,.5,-4.13,.22,.35,.2,'#e98b45');box(.22,.47,-4.13,.22,.25,.2,'#f2c76a');box(.1,1.64,-4.6,2,.2,.9,'#72543b');
    for(const x of [-3.8,3.8]){box(x,2.3,-4.95,1.2,.12,.35,'#65452e');for(let i=0;i<4;i++)box(x-.4+i*.25,2.5,-4.88,.14,.32,.14,['#748352','#b16f4e','#d0ac72','#577373'][i]);}
    // Scattered sacks, books, crates and rugs retain a clear center aisle.
    furniture(3.7,.3,-2.2,.7,.6,.7,'#9a7044');box(3.7,.64,-2.2,.75,.1,.75,'#6b4c34');
    for(const [x,z] of [[-4,2.5],[3.7,2],[-2.2,-4.4]]){box(x,.22,z,.55,.44,.45,'#baa57c');box(x,.47,z,.24,.1,.24,'#8d7958');solid(x,.22,z,.55,.44,.45);}
    box(0,.012,1.2,1.2,.02,3.8,'#923f43');for(let z=-.5;z<=3;z+=.3)box(0,.027,z,1.1,.01,.05,'#c7a26c');
    box(0,1.1,5.02,1.5,2.2,.08,'#76503a');box(.45,1,4.95,.12,.12,.12,'#d9ad5f');
    indoorZone.boxes=solids;indoorZone.cameraBoxes=cameraBoxes;
    const indoor=mesh();indoor.visible=false;
    return {outdoor,indoor,outdoorZone,indoorZone,dispose(){outdoor.dispose();indoor.dispose();}};
  }
  return {create};
})();
