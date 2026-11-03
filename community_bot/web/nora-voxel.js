'use strict';
window.NoraVoxel = (() => {
  const unit = .105;
  const colors = { skin: '#f2a07d', shadow: '#d67c64', cheek: '#e7977e', mouth: '#9e5351', cream: '#e4d7bc', white: '#e9e7e1', gray: '#777982', burgundy: '#702a3d', blue: '#344e72', denimGray: '#555965', sole: '#c5c1ba', black: '#24262b', red: '#9c3348', stripe: '#202124', stripeWhite: '#eee8df' };
  const defaults = { gender: 'male', hairstyle: 'crop', hair_color: 'black', eye_color: 'brown', shirt: 'white', pants: 'blue_slim', shoes: 'white_stripes' };
  const hairColors = {black:'#29252c',chestnut:'#633b30',brown:'#91634a',blonde:'#ddbc76',ginger:'#b75e35',ash:'#b0adb4',rose:'#bc758d',blue:'#536c9b'};
  const eyeColors = {brown:'#68412c',hazel:'#9b7939',green:'#4c8055',blue:'#538cbc',gray:'#8896a0',violet:'#8a65ad'};
  const choices = {
    gender: [['male','Мужской персонаж'],['female','Женский персонаж']],
    hairstyle: [['crop','Короткая'],['bob','Каре'],['ponytail','Хвост']],
    hair_color: [['black','Чёрный'],['chestnut','Каштановый'],['brown','Русый'],['blonde','Блонд'],['ginger','Рыжий'],['ash','Пепельный'],['rose','Розовый'],['blue','Синий']],
    eye_color: [['brown','Карие'],['hazel','Ореховые'],['green','Зелёные'],['blue','Голубые'],['gray','Серые'],['violet','Фиолетовые']],
    shirt: [['white','Белая футболка'],['gray','Серая футболка'],['burgundy','Бордовая футболка']],
    pants: [['blue_slim','Узкие синие джинсы'],['gray_slim','Узкие серые джинсы'],['burgundy_wide','Широкие бордовые джинсы']],
    shoes: [['white_stripes','Белые кроссовки с чёрными полосками'],['black_stripes','Чёрные кроссовки с белыми полосками'],['red_air','Бордово-красные кроссовки с воздушной подошвой']],
  };
  // Small pixel silhouettes share the character's actual colours and item shapes.
  function icon(category, value, outfit = defaults) {
    const hair = hairColors[category === 'hair_color' ? value : outfit.hair_color] || hairColors.black;
    const style = category === 'hairstyle' ? value : outfit.hairstyle;
    let art = '';
    if (category === 'gender') {
      art = `<path fill="${colors.skin}" d="M11 4h10v11H11z"/><path fill="${hair}" d="M10 3h12v5H10z"/><path fill="#c7b99b" d="${value==='female'?'M9 17h14v4h-3v2h2v3H10v-3h2v-2H9z':'M7 17h18v6h-4v3H11v-3H7z'}"/>`;
      art += `<path fill="#e3bc82" d="${value==='female'?'M25 20h2v3h3v2h-3v4h-2v-4h-3v-2h3z':'M24 2h6v6h-2V6l-5 5-2-2 5-5h-2z'}"/>`;
    } else if (category === 'hairstyle' || category === 'hair_color') {
      art = `<path fill="${colors.skin}" d="M9 10h14v14H9z"/><path fill="${hair}" d="${style==='bob'?'M10 4h12v2h3v4h2v14h-3v2h-3V12h-5v-2h-4v3h-1v13H8v-2H6V10h1V6h3z':style==='ponytail'?'M11 4h10v1h3v3h2v3h3v3h2v8h-1v3h-2v3h-3V15h-3v9h-2V13h-4v-2h-3v3h-2v10H9V14H7V8h2V5h2z':'M10 3h9v2h5v3h2v5h-6v-2h-7v3H8v-1H6V8h2V5h2z'}"/><path fill="#fff" opacity=".06" d="M11 5h9v2h-9z"/>`;
      if(style==='ponytail') art += `<path fill="${colors.burgundy}" d="M26 12h5v2h-5z"/>`;
      if(category==='hair_color') art += '<path fill="#e3bc82" d="M25 18h3v3h-3zM22 21h3v3h-3zM19 24h3v3h-3z"/>';
    } else if (category === 'eye_color') {
      art = `<path fill="#e9e7e1" d="M5 11h4V8h14v3h4v10h-4v3H9v-3H5z"/><path fill="${eyeColors[value]||eyeColors.brown}" d="M11 9h10v14H11z"/><path fill="#202124" d="M14 12h4v9h-4z"/><path fill="#fff" d="M12 10h3v3h-3z"/>`;
    } else if (category === 'shirt') {
      const shape=outfit.gender==='female'?'M11 5H8L2 11l4 6 4-2v3h2v4h-2v5h12v-5h-2v-4h2v-3l4 2 4-6-6-6h-3l-2 3h-6z':'M11 5H8L2 11l4 6 4-2v12h12V15l4 2 4-6-6-6h-3l-2 3h-6z';
      art = `<path fill="${colors[value]||colors.white}" d="${shape}"/><path fill="#000" opacity=".10" d="M10 24h12v3H10zM13 5h6v3h-6z"/>`;
      art += `<path fill="${colors.cream}" d="M11 5h2v3h6V5h2v3h-2v2h-6V8h-2zM4 14l2 3 4-2v-2l-4 2zM22 13v2l4 2 2-3-2 1zM10 25h12v2H10z"/>`;
    } else if (category === 'pants') {
      const wide = value === 'burgundy_wide';
      art = `<path fill="${value==='blue_slim'?colors.blue:value==='gray_slim'?colors.denimGray:colors.burgundy}" d="M7 4h18v9l${wide?'2':'-2'} 15h-${wide?'10':'6'}l-1-14-1 14H${wide?'5':'9'}l${wide?'2':'-2'}-15z"/><path fill="#000" opacity=".10" d="M7 4h18v3H7z"/><path fill="#c5c1ba" d="M15 5h2v2h-2z"/>`;
    } else if (category === 'shoes') {
      const fill = value==='white_stripes'?colors.white:value==='black_stripes'?colors.black:colors.red;
      art = `<path fill="${fill}" d="M5 8h9v6l5 3h6l4 4v5H3V13h2z"/><path fill="${value==='white_stripes'?colors.stripe:colors.stripeWhite}" d="M9 15h2v6H9zM13 16h2v5h-2zM17 18h2v3h-2z"/><path fill="${colors.sole}" d="M3 24h26v3H3z"/>`;
    }
    return `<svg viewBox="0 0 32 32" fill="none" shape-rendering="crispEdges" aria-hidden="true">${art}</svg>`;
  }
  function createCharacter(T, outfit) {
    const pivot = new T.Group();
    const cube = new T.BoxGeometry(unit, unit, unit);
    const voxels = new Map();
    const material = new T.MeshLambertMaterial({ color: 0xffffff });
    let section='body', phase=0, gait=0, run=0;
    const meshes=[], joints={}, origins={body:[0,13.5,0]};
    const motion=new T.Group(), hips=new T.Group(), torso=new T.Group();
    motion.name='gaitRoot';hips.name='hips';torso.name='torso';
    pivot.add(motion);motion.add(hips);hips.position.y=13.5*unit;hips.add(torso);joints.body=torso;
    for(const side of [-1,1]){
      const key=side<0?'Left':'Right', thigh=new T.Group(), shin=new T.Group(), foot=new T.Group(), arm=new T.Group(), forearm=new T.Group();
      hips.add(thigh);thigh.position.set(side*4*unit,0,0);thigh.add(shin);shin.position.y=-6*unit;shin.add(foot);foot.position.y=-5*unit;
      torso.add(arm);arm.position.set(side*10*unit,11*unit,0);arm.add(forearm);forearm.position.y=-5*unit;
      for(const [name,node,origin] of [['thigh',thigh,[side*4,13.5,0]],['shin',shin,[side*4,7.5,0]],['foot',foot,[side*4,2.5,0]],['arm',arm,[side*10,24.5,0]],['forearm',forearm,[side*10,19.5,0]]]){node.name=name+key;joints[name+key]=node;origins[name+key]=origin;}
    }
    function dot(x, y, z, color, override) { const side=x<0?'Left':'Right'; const part=override || (section==='shoes'?'foot'+side:section==='legs'?(y>=8?'thigh':'shin')+side:section==='arms'?(y>=20?'arm':'forearm')+side:'body');voxels.set(`${part}:${x},${y},${z}`, [x,y,z,color,part]); }
    function box(x0, x1, y0, y1, z0, z1, color, surface = true) {
      for (let x=x0;x<=x1;x++) for (let y=y0;y<=y1;y++) for (let z=z0;z<=z1;z++)
        if (!surface || x===x0 || x===x1 || y===y0 || y===y1 || y===7 || y===8 || y===19 || y===20 || z===z0 || z===z1) dot(x,y,z,color);
    }
    function build() {
      const palette = {...colors, hair: hairColors[outfit.hair_color] || hairColors.black, eye: eyeColors[outfit.eye_color] || eyeColors.brown};
      const female = outfit.gender === 'female';
      // A relaxed two-degree arm opening keeps the fitted hips clear during sway.
      joints.armLeft.rotation.z=female?-.04:0;joints.armRight.rotation.z=female?.04:0;
      for(const mesh of meshes){mesh.parent.remove(mesh);mesh.dispose();}meshes.length=0;
      voxels.clear();
      section='shoes';
      // Feet and layered soles.
      const shoe = outfit.shoes === 'white_stripes' ? 'white' : outfit.shoes === 'black_stripes' ? 'black' : 'red';
      for (const side of [-1,1]) {
        const x = side*4;
        box(x-3,x+3,0,2,-3,8,shoe);box(x-2,x+2,0,1,9,9,shoe);
        box(x-3,x+3,0,0,-3,8, outfit.shoes==='red_air'?'black':'sole');
        box(x-2,x+2,0,0,9,9,outfit.shoes==='red_air'?'black':'sole');
        if (outfit.shoes==='red_air') { for (let z=3;z<=8;z++) dot(x-3,1,z,'stripeWhite'); box(x-2,x+2,2,2,4,8,'red'); }
        else for (let i=0;i<3;i++) { dot(x-3,2,3+i*2,outfit.shoes==='white_stripes'?'stripe':'stripeWhite'); dot(x+3,2,3+i*2,outfit.shoes==='white_stripes'?'stripe':'stripeWhite'); }
      }
      section='legs';
      const wide = outfit.pants==='burgundy_wide', pant = outfit.pants==='blue_slim'?'blue':outfit.pants==='gray_slim'?'denimGray':'burgundy';
      for (const side of [-1,1]) {
        const x=side*4;
        for(let y=4;y<=13;y++) {
          const edge=(wide&&y>=5&&y<=11)||(female&&y>=11)?4:3;
          const back=female&&y>=10?-4:-3;
          box(x-(side<0?edge:3),x+(side>0?edge:3),y,y,back,3,pant);
          // Seat volume belongs to each thigh, so it follows the existing gait.
          if(female&&y>=11&&y<=12)box(x-2,x+2,y,y,-5,-4,pant);
        }
      }
      section='body';
      // Continuous shirt shell: one-voxel steps at the waist, hips and shoulders.
      // The fitted front grows out of the torso, rather than two attached blocks.
      const shirtWidths=female?[8,8,7,6,5,5,6,7,8,8,8,7]:[7,7,7,8,8,8,8,8,8,8,8,7];
      for(let y=14;y<=25;y++) {
        const width=shirtWidths[y-14],depth=female&&(y===18||y===19)?3:4;
        box(-width,width,y,y,-depth,depth,outfit.shirt);
      }
      if(female) {
        // Broad front plane with a single bevel, not concentric narrow terraces.
        box(-4,4,20,20,5,5,outfit.shirt);
        box(-6,6,21,23,5,6,outfit.shirt);
        box(-4,4,21,23,7,7,outfit.shirt);
        box(-7,7,22,22,5,5,outfit.shirt);
        box(-4,4,22,23,8,8,outfit.shirt);
        box(-5,5,24,24,5,5,outfit.shirt);
        box(-4,4,24,24,6,6,outfit.shirt);
      }
      section='arms';
      for (const side of [-1,1]) {
        const x=side*10;
        box(x-2,x+2,20,24,-3,3,outfit.shirt);
        box(x-1,x+1,25,25,-2,2,outfit.shirt);
        // A one-voxel inner taper leaves clearance beside the wider female hips.
        const inner=female?1:2;
        if(female) {
          box(x-2,x+2,17,19,-2,2,'skin');
          box(x-(side<0?2:inner),x+(side>0?2:inner),12,16,-2,2,'skin');
        } else box(x-2,x+2,12,19,-2,2,'skin');
        box(x-(side<0?2:inner),x+(side>0?2:inner),12,12,3,3,'shadow');
      }
      // Let scene lighting describe the cloth; keep only intentional knit edging.
      section='body';
      const hem=shirtWidths[0];
      box(-hem,hem,14,14,-4,4,'cream');
      box(-2,2,25,25,4,4,'skin');
      box(-3,-3,25,25,4,4,'cream');box(3,3,25,25,4,4,'cream');
      box(-2,2,24,24,5,5,'cream');
      if(!female) dot(0,23,5,'cream');
      for (const side of [-1,1]) {
        const x=side*10;
        section='arms';box(x-2,x+2,20,20,-3,3,'cream');section='body';
      }
      section='body';
      // Quiet denim panels: waistband and broad pockets, no isolated knee marks.
      const pantTrim=pant+'Trim', pantLight=pant+'Light';
      box(female?-8:-7,female?8:7,13,13,female?-4:-3,3,pantTrim);
      section='legs';
      for (const side of [-1,1]) {
        const x=side*4;
        for (let y=4;y<=12;y++) dot(x+side*((wide&&y>=5&&y<=11)||(female&&y>=11)?4:3),y,3,pantTrim);
        if(female) {
          box(x-1,x+1,11,12,-5,-5,pantLight);
        } else {
          box(x-2,x+2,9,11,-3,-3,pantLight);
        }
        box(x-3,x+3,4,4,-3,3,pantTrim);
        box(x-2,x+2,3,4,-2,2,pant);
        dot(x,13,4,'sole');
      }
      section='shoes';
      // Sculpted uppers, tongues, laces and layered sneaker sidewalls.
      for (const side of [-1,1]) {
        const x=side*4;
        box(x-2,x+2,2,3,-3,5,shoe);
        box(x-2,x+2,2,2,6,8,shoe);
        box(x-1,x+1,3,3,3,6,shoe);
        box(x-1,x+1,3,3,4,5,'stripeWhite');
        if (outfit.shoes==='red_air') {
          for (const edge of [-3,3]) {
            for (let z=2;z<=8;z++) { dot(x+edge,1,z,'sole'); dot(x+edge,2,z,'burgundy'); }
            box(x+edge,x+edge,1,1,2,4,'black');
          }
        } else {
          for (const edge of [-3,3]) for (let i=0;i<3;i++) {
            dot(x+edge,2,3+i*2,outfit.shoes==='white_stripes'?'stripe':'stripeWhite');
            dot(x+edge,3,2+i*2,outfit.shoes==='white_stripes'?'stripe':'stripeWhite');
          }
        }
      }
      section='body';
      box(-2,2,25,27,-2,2,'skin');
      // Keep the square head; only the lower jaw and ear edges step inward.
      box(female?-8:-9,female?8:9,28,28,-6,6,'skin');
      box(female?-9:-10,female?9:10,29,30,-7,7,'skin');
      box(-10,10,31,44,-7,7,'skin');
      for(const side of [-1,1]) {
        box(side*11,side*11,33,36,-1,1,'skin');
        box(side*11,side*11,34,35,1,1,'shadow');
        box(side<0?-9:8,side<0?-8:9,32,33,7,7,'cheek');
      }
      // Three broad crown planes replace the staircase of shrinking rings.
      const hairstyle = outfit.hairstyle || defaults.hairstyle;
      box(-10,10,42,44,-7,7,'hair',false);
      for(let y=42;y<=49;y++) {
        const width=y<=45?11:y<=48?10:8,depth=y<=45?8:y<=48?7:5;
        for(let x=-width;x<=width;x++)for(let z=-depth;z<=depth;z++)
          if(Math.abs(x)+Math.abs(z)<=width+depth-3)
            dot(x,y,z,y>=46&&x<2?'hairLight':'hair');
      }
      box(-10,10,39,42,-8,-6,'hair');
      if(hairstyle==='crop') {
        // A swept crown and connected fringe locks give a deliberate parting.
        box(-7,1,50,50,-2,3,'hairLight');
        for(const [left,right,bottom,front] of [[-10,-7,39,8],[-6,2,40,9],[3,10,42,8]])
          box(left,right,bottom,44,7,front,'hair',false);
        for(const side of [-1,1]) {
          box(side<0?-11:10,side<0?-10:11,39,43,-5,4,'hair');
          box(side*10,side*10,38,38,-3,2,'hair');
        }
      } else if(hairstyle==='bob') {
        // Rounded sides flow into the back; the lower edge turns inward.
        for(let y=29;y<=43;y++) {
          const width=y<=30?10:y===31?11:12,back=y<=30?8:y===31?9:10;
          for(let x=-width;x<=width;x++)for(let z=-back;z<=7;z++)
            if((Math.abs(x)>=9||z<=-6)&&Math.abs(x)+Math.abs(z)<=width+back-3)
              dot(x,y,z,x<=-9&&z>=0?'hairLight':'hair');
        }
        for(const [left,right,bottom] of [[-10,-7,39],[-6,2,40],[3,10,42]])
          box(left,right,bottom,44,7,9,'hair',false);
        for(const side of [-1,1])box(side<0?-10:9,side<0?-9:10,30,38,8,8,'hair');
      } else if(hairstyle==='ponytail') {
        box(-11,-9,37,43,-6,7,'hair');box(9,11,37,43,-6,7,'hair');
        for(const [left,right,bottom] of [[-9,-3,40],[-2,3,42],[4,9,40]])
          box(left,right,bottom,44,7,9,'hair',false);
        for(const side of [-1,1]) {
          box(side<0?-11:9,side<0?-9:11,35,40,7,8,'hair');
          box(side<0?-10:9,side<0?-9:10,29,34,7,8,'hair');
        }
        box(-3,3,41,45,-12,-8,'hair');
        box(-3,3,40,41,-13,-10,'burgundy');
        for(let y=26;y<=39;y++) {
          const width=y<=28?2:y<=30?3:4;
          const center=y<=28?-12:-13,depth=2;
          for(let x=-width;x<=width;x++)for(let z=center-depth;z<=center+depth;z++)
            if(Math.abs(x)+Math.abs(z-center)<=width+depth-1)
              dot(x,y,z,x<=-2&&z===center-depth?'hairLight':'hair');
        }
      }
      // All eye pixels share one shallow plane: no protruding pupil stack.
      for (const center of [-5,5]) {
        box(center-2,center+2,34,37,8,8,'white',false);
        box(center-1,center+1,34,37,8,8,'eye',false);
        box(center,center,34,36,8,8,'black',false);
        dot(center-1,37,8,'white');
        box(center-2,center+1,39,39,7,7,'hairTrim');dot(center+2,40,7,'hairTrim');
        if(female) {
          box(center-2,center+2,38,38,8,8,'black');
          dot(center+Math.sign(center)*3,38,8,'black');
        }
      }
      box(0,1,32,33,8,8,'skin');dot(1,32,8,'shadow');
      box(-1,1,30,30,7,7,'mouth');
      // Small overlapping joint caps cover the seams while limbs bend.
      for(const side of [-1,1])for(let y=12;y<=14;y++)for(let z=-2;z<=2;z++)for(let x=-2;x<=2;x++)dot(side*4+x,y,z,pant,'thigh'+(side<0?'Left':'Right'));
      for(const side of [-1,1])for(let y=7;y<=8;y++)for(let z=-1;z<=1;z++)for(let x=-2;x<=2;x++)dot(side*4+x,y,z,pant,'thigh'+(side<0?'Left':'Right'));
      for(const side of [-1,1])for(let y=19;y<=20;y++)for(let z=-1;z<=1;z++)for(let x=-1;x<=1;x++)dot(side*10+x,y,z,'skin','arm'+(side<0?'Left':'Right'));
      const temp=new T.Object3D(),tint=new T.Color(),batches=new Map();
      // Cull only cubes enclosed by their own joint; keep articulated seam caps.
      const neighbors=[[1,0,0],[-1,0,0],[0,1,0],[0,-1,0],[0,0,1],[0,0,-1]];
      // The head is solid. Account for its interior without allocating hidden cubes.
      // These bounds match the main head box above; face/jaw and moving joints stay explicit.
      const inHead=(x,y,z)=>x>=-10&&x<=10&&y>=31&&y<=44&&z>=-7&&z<=7;
      for(const voxel of voxels.values()){
        const [x,y,z,,part]=voxel;
        if(neighbors.every(([dx,dy,dz])=>(part==='body'&&inHead(x+dx,y+dy,z+dz))||voxels.has(`${part}:${x+dx},${y+dy},${z+dz}`)))continue;
        if(!batches.has(part))batches.set(part,[]);batches.get(part).push(voxel);
      }
      for(const [part,items] of batches){
        const mesh=new T.InstancedMesh(cube,material,items.length),origin=origins[part];
        items.forEach(([x,y,z,color],i)=>{
          temp.position.set((x-origin[0])*unit,(y-origin[1])*unit,(z-origin[2])*unit);temp.updateMatrix();mesh.setMatrixAt(i,temp.matrix);
          // Stable, broad tones replace the per-cube checker pattern.
          const shade=color.endsWith('Trim')?.93:color.endsWith('Light')?1.04:1;
          tint.set(palette[color]||palette[color.replace(/Trim|Light/g,'')]);tint.multiplyScalar(shade);mesh.setColorAt(i,tint);
        });
        mesh.instanceMatrix.needsUpdate=true;mesh.frustumCulled=false;joints[part].add(mesh);meshes.push(mesh);
      }
    }
    function walk(distance,dt,sprinting=false){
      run+=((sprinting&&distance>0?1:0)-run)*(1-Math.exp(-8*dt));
      gait+=(Math.min(1,distance/Math.max(dt,.001)/1.7)-gait)*(1-Math.exp(-12*dt));
      phase=(phase+distance/(1.15+run*.55)*Math.PI*2)%(Math.PI*2);
      motion.position.y=(-.1+.015*Math.cos(phase*2))*gait;
      torso.rotation.x=(.025+run*.27)*gait;torso.rotation.z=Math.sin(phase)*.018*gait;
      for(const [key,offset] of [['Left',0],['Right',Math.PI]]){
        const t=((phase+offset)%(Math.PI*2))/(Math.PI*2),stance=.6;
        const swing=t<stance?0:(t-stance)/(1-stance);
        const stride=.42+run*.2;
        const z=(t<stance?stride*(1-2*t/stance):-stride+2*stride*(swing*swing*(3-2*swing)))*gait;
        const lift=Math.sin(swing*Math.PI)*(.24+run*.3)*gait,L1=6*unit,L2=5*unit;
        const down=L1+L2+motion.position.y-lift,r=Math.min(L1+L2-.00001,Math.hypot(down,z));
        const hip=Math.atan2(-z,down)-Math.acos(Math.max(-1,Math.min(1,(L1*L1+r*r-L2*L2)/(2*L1*r))));
        const knee=Math.PI-Math.acos(Math.max(-1,Math.min(1,(L1*L1+L2*L2-r*r)/(2*L1*L2))));
        joints['thigh'+key].rotation.x=gait<.001?0:hip;
        joints['shin'+key].rotation.x=gait<.001?0:knee;
        joints['foot'+key].rotation.x=gait<.001?0:-hip-knee;
        joints['arm'+key].rotation.x=(Math.cos(phase+offset)*.34*(1-run)+run*(.85+Math.sin(phase+offset)*.06))*gait;
        joints['forearm'+key].rotation.x=(-.12*gait-Math.max(0,-z)*.18)*(1-run);
      }
    }
    build();
    return { group: pivot, rebuild: build, walk, setOpacity(value) { const fading=value<.995; if(material.transparent!==fading){material.transparent=fading;material.needsUpdate=true;} material.opacity=value;material.depthWrite=!fading; }, dispose() { for(const mesh of meshes)mesh.dispose(); material.dispose(); cube.dispose(); } };
  }
  return { defaults, choices, icon, createCharacter, async mount(canvas, outfit, root) {
    const T = await import('/vendor/three.module.js');
    const renderer = new T.WebGLRenderer({ canvas, antialias: false, alpha: true, powerPreference: 'low-power' });
    renderer.setPixelRatio(Math.min(devicePixelRatio || 1, 1.5));
    renderer.outputColorSpace = T.SRGBColorSpace;
    const scene = new T.Scene(), camera = new T.OrthographicCamera(-2, 2, 2.9, -2.9, .1, 100);
    camera.position.set(0, 3.5, 12); camera.lookAt(0, 2.65, 0);
    scene.add(new T.HemisphereLight(0xffffff, 0x655562, 2.3));
    const light = new T.DirectionalLight(0xffffff, 2.2); light.position.set(-3, 6, 5); scene.add(light);
    const character = createCharacter(T, outfit), pivot = character.group; scene.add(pivot);
    let raf = 0, lastTouch = 0, dragging = false, startX = 0, disposed = false;
    function resize() { const w=canvas.clientWidth,h=canvas.clientHeight;if(!w||!h)return;renderer.setSize(w,h,false);const aspect=w/h, halfHeight=Math.max(2.95,1.65/aspect);camera.top=halfHeight;camera.bottom=-halfHeight;camera.left=-halfHeight*aspect;camera.right=halfHeight*aspect;camera.updateProjectionMatrix(); }
    const observer=new ResizeObserver(resize); observer.observe(canvas);resize();
    const changed=()=>character.rebuild();root.addEventListener('outfit-change',changed);
    canvas.style.touchAction='none';
    canvas.onpointerdown=e=>{dragging=true;startX=e.clientX;canvas.setPointerCapture(e.pointerId);};
    canvas.onpointermove=e=>{if(dragging){pivot.rotation.y+=(e.clientX-startX)*.009;startX=e.clientX;lastTouch=performance.now();}};
    canvas.onpointerup=canvas.onpointercancel=()=>{dragging=false;};
    function tick(t){if(disposed)return;if(!document.hidden){if(!dragging&&t-lastTouch>1300)pivot.rotation.y+=.0025;renderer.render(scene,camera);}raf=requestAnimationFrame(tick);} tick(0);
    return ()=>{disposed=true;cancelAnimationFrame(raf);observer.disconnect();root.removeEventListener('outfit-change',changed);character.dispose();renderer.dispose();};
  }};
})();
