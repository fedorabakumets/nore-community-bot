'use strict';
window.NoraVoxel = (() => {
  const unit = .105;
  const colors = { skin: '#f2a07d', shadow: '#d67c64', mouth: '#9e5351', white: '#e9e7e1', gray: '#777982', burgundy: '#702a3d', blue: '#344e72', denimGray: '#555965', sole: '#c5c1ba', black: '#24262b', red: '#9c3348', stripe: '#202124', stripeWhite: '#eee8df' };
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
      art = `<path fill="${colors.skin}" d="M11 4h10v11H11z"/><path fill="${hair}" d="M10 3h12v5H10z"/><path fill="#c7b99b" d="${value==='female'?'M9 17h14v5h-3v4h-8v-4H9z':'M7 17h18v6h-4v3H11v-3H7z'}"/>`;
      art += `<path fill="#e3bc82" d="${value==='female'?'M25 20h2v3h3v2h-3v4h-2v-4h-3v-2h3z':'M24 2h6v6h-2V6l-5 5-2-2 5-5h-2z'}"/>`;
    } else if (category === 'hairstyle' || category === 'hair_color') {
      art = `<path fill="${colors.skin}" d="M9 10h14v14H9z"/><path fill="${hair}" d="${style==='bob'?'M7 6h18v3h2v17h-6V13H11v13H5V9h2z':style==='ponytail'?'M7 7h18v3h2v16h-4V14h-2v-3H11v7H7z':'M7 7h3V4h6v2h7v3h2v8h-4v-5h-4v2h-6v4H7z'}"/><path fill="#fff" opacity=".18" d="M10 7h10v2H10z"/>`;
      if(category==='hair_color') art += '<path fill="#e3bc82" d="M25 18h3v3h-3zM22 21h3v3h-3zM19 24h3v3h-3z"/>';
    } else if (category === 'eye_color') {
      art = `<path fill="#e9e7e1" d="M5 11h4V8h14v3h4v10h-4v3H9v-3H5z"/><path fill="${eyeColors[value]||eyeColors.brown}" d="M11 9h10v14H11z"/><path fill="#202124" d="M14 12h4v9h-4z"/><path fill="#fff" d="M12 10h3v3h-3z"/>`;
    } else if (category === 'shirt') {
      art = `<path fill="${colors[value]||colors.white}" d="M11 5H8L2 11l4 6 4-2v12h12V15l4 2 4-6-6-6h-3l-2 3h-6z"/><path fill="#000" opacity=".22" d="M10 24h12v3H10zM13 5h6v3h-6z"/><path fill="#fff" opacity=".25" d="M18 12h3v4h-3z"/>`;
    } else if (category === 'pants') {
      const wide = value === 'burgundy_wide';
      art = `<path fill="${value==='blue_slim'?colors.blue:value==='gray_slim'?colors.denimGray:colors.burgundy}" d="M7 4h18v9l${wide?'2':'-2'} 15h-${wide?'10':'6'}l-1-14-1 14H${wide?'5':'9'}l${wide?'2':'-2'}-15z"/><path fill="#000" opacity=".25" d="M7 4h18v3H7z"/><path fill="#c5c1ba" d="M15 5h2v2h-2z"/>`;
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
      for(const mesh of meshes){mesh.parent.remove(mesh);mesh.dispose();}meshes.length=0;
      voxels.clear();
      section='shoes';
      // Feet and layered soles.
      const shoe = outfit.shoes === 'white_stripes' ? 'white' : outfit.shoes === 'black_stripes' ? 'black' : 'red';
      for (const side of [-1,1]) {
        const x = side*4;
        box(x-3,x+3,0,2,-3,9,shoe); box(x-3,x+3,0,0,-3,9, outfit.shoes==='red_air'?'black':'sole');
        if (outfit.shoes==='red_air') { for (let z=3;z<=8;z++) dot(x-3,1,z,'stripeWhite'); box(x-2,x+2,2,2,4,8,'red'); }
        else for (let i=0;i<3;i++) { dot(x-3,2,3+i*2,outfit.shoes==='white_stripes'?'stripe':'stripeWhite'); dot(x+3,2,3+i*2,outfit.shoes==='white_stripes'?'stripe':'stripeWhite'); }
      }
      section='legs';
      const wide = outfit.pants==='burgundy_wide', pant = outfit.pants==='blue_slim'?'blue':outfit.pants==='gray_slim'?'denimGray':'burgundy';
      for (const side of [-1,1]) { const x=side*4; box(x-(wide?4:3),x+(wide?4:3),2,13,-3,3,pant); box(x-3,x+3,3,3,3,3,pant); }
      section='body';
      // A stepped waist and softer jaw distinguish the two voxel silhouettes.
      if(female) {
        box(-7,7,14,15,-4,4,outfit.shirt); box(-6,6,16,21,-4,4,outfit.shirt); box(-8,8,22,25,-4,4,outfit.shirt);
      } else box(-8,8,14,25,-4,4,outfit.shirt);
      box(female?-7:-8,female?7:8,14,14,-4,4,outfit.shirt==='white'?'gray':'black');
      section='arms';
      for (const side of [-1,1]) { const x=side*10; box(x-2,x+2,20,25,-3,3,outfit.shirt); box(x-2,x+2,13,19,-2,2,'skin'); box(x-2,x+2,12,13,-2,3,'shadow'); }
      // Raised stitching, ribbed hems, collar and a small chest pocket.
      const shirtTrim = outfit.shirt + 'Trim', shirtLight = outfit.shirt + 'Light';
      section='body';
      box(female?-7:-8,female?7:8,14,14,-4,4,shirtTrim);
      box(-3,3,25,25,4,4,shirtTrim);
      for (const side of [-1,1]) {
        const x=side*10;
        section='arms';box(x-2,x+2,20,20,-3,3,shirtTrim);section='body';
        for (let y=16;y<=22;y++) dot(side*(female&&y<22?6:8),y,4,shirtTrim);
        for (let y=15;y<=18;y++) dot(side*(5+(y%2)),y,5,shirtLight);
      }
      box(3,6,21,23,5,5,shirtLight); box(3,6,20,20,5,5,shirtTrim);
      section='body';
      // Denim seams, waistband, rear pockets and stepped knee creases.
      const pantTrim=pant+'Trim', pantLight=pant+'Light';
      box(-7,7,13,13,-3,3,pantTrim);
      section='legs';
      for (const side of [-1,1]) {
        const x=side*4, edge=wide?4:3;
        for (let y=3;y<=12;y++) dot(x+side*edge,y,3,pantTrim);
        box(x-2,x+2,9,11,-4,-4,pantLight);
        box(x-2,x+2,8,8,-4,-4,pantTrim);
        for (let i=0;i<4;i++) dot(x-2+i,6+(i%2),4,pantLight);
        box(x-edge,x+edge,2,2,-3,3,pantTrim);
        dot(x,13,4,'sole');
      }
      section='shoes';
      // Sculpted uppers, tongues, laces and layered sneaker sidewalls.
      for (const side of [-1,1]) {
        const x=side*4, trim=outfit.shoes==='white_stripes'?'gray':'sole';
        box(x-2,x+2,2,3,-3,5,shoe);
        box(x-2,x+2,2,2,6,8,shoe);
        box(x-1,x+1,3,3,3,5,trim);
        for (let z=4;z<=7;z++) box(x-1,x+1,3,3,z,z,'stripeWhite');
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
      // Big cubic head, ears, pixel hair and small facial details.
      box(female?-8:-10,female?8:10,28,30,-7,7,'skin');
      box(-10,10,31,44,-7,7,'skin'); box(-11,-10,33,37,-2,2,'shadow'); box(10,11,33,37,-2,2,'skin');
      box(-10,10,42,47,-7,7,'hair'); box(-11,11,40,44,-8,-5,'hair');
      const hairstyle = outfit.hairstyle || defaults.hairstyle;
      if(hairstyle==='crop') {
        for (let x=-10;x<=10;x++) for (let z=-7;z<=7;z++) {
          const h=47+Math.floor(2.5*Math.sin(x*1.8+z*.7)+2*Math.cos(z*1.4-x*.5));
          if ((x+z)%3!==0) dot(x,h,z,((x*z)%5===0)?'hairLight':'hair');
        }
        for (let x=-10;x<=10;x++) if (x%3!==0) box(x,x,39+(x%3),43,7,8,'hair');
      } else if(hairstyle==='bob') {
        box(-11,11,29,43,-9,-6,'hair');
        for(const side of [-1,1]) {
          box(side<0?-12:9,side<0?-9:12,29,43,-7,7,'hair');
          box(side*11,side*11,30,42,8,8,'hairLight');
        }
        for(let x=-10;x<=10;x++) box(x,x,40+Math.floor((x+10)/7),43,7,8,'hair');
      } else if(hairstyle==='ponytail') {
        box(-10,-8,36,43,-6,7,'hair'); box(8,10,36,43,-6,7,'hair');
        box(-7,3,40,43,7,8,'hair');
        box(-4,4,36,44,-13,-8,'hair'); box(-3,3,26,38,-14,-10,'hair');
        box(-4,4,38,39,-14,-10,'burgundy'); box(-2,-2,27,36,-15,-15,'hairLight');
      }
      // Open eyes: whites, coloured irises, pupils and one pixel of reflected light.
      for (const center of [-5,5]) {
        box(center-2,center+2,34,37,8,8,'white',false);
        box(center-1,center+1,34,37,9,9,'eye',false);
        box(center,center,34,36,10,10,'black',false);
        dot(center-1,37,10,'white');
        box(center-2,center+2,39,39,8,8,'hair');
        if(female) box(center-3,center+2,38,38,8,8,'hair');
      }
      box(-1,1,32,34,8,9,'shadow'); box(-2,2,30,30,8,8,'mouth');
      // Small overlapping joint caps cover the seams while limbs bend.
      for(const side of [-1,1])for(let y=12;y<=14;y++)for(let z=-2;z<=2;z++)for(let x=-2;x<=2;x++)dot(side*4+x,y,z,pant,'thigh'+(side<0?'Left':'Right'));
      for(const side of [-1,1])for(let y=7;y<=8;y++)for(let z=-1;z<=1;z++)for(let x=-2;x<=2;x++)dot(side*4+x,y,z,pant,'thigh'+(side<0?'Left':'Right'));
      for(const side of [-1,1])for(let y=19;y<=20;y++)for(let z=-1;z<=1;z++)for(let x=-1;x<=1;x++)dot(side*10+x,y,z,'skin','arm'+(side<0?'Left':'Right'));
      const temp=new T.Object3D(),tint=new T.Color(),batches=new Map();
      for(const voxel of voxels.values()){const part=voxel[4];if(!batches.has(part))batches.set(part,[]);batches.get(part).push(voxel);}
      for(const [part,items] of batches){
        const mesh=new T.InstancedMesh(cube,material,items.length),origin=origins[part];
        items.forEach(([x,y,z,color],i)=>{
          temp.position.set((x-origin[0])*unit,(y-origin[1])*unit,(z-origin[2])*unit);temp.updateMatrix();mesh.setMatrixAt(i,temp.matrix);
          const shade=color.endsWith('Trim')?.78:color.endsWith('Light')?1.12:1;
          tint.set(palette[color]||palette[color.replace(/Trim|Light/g,'')]);tint.multiplyScalar(shade*(.94+((x*13+y*7+z*3)&3)*.02));mesh.setColorAt(i,tint);
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
