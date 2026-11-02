'use strict';
window.NoraVoxel = (() => {
  const unit = .105;
  const colors = { skin: '#f2a07d', shadow: '#d67c64', hair: '#29252c', hairLight: '#39333b', glass: '#171a20', lens: '#e6c3ae', eye: '#24313b', mouth: '#9e5351', white: '#e9e7e1', gray: '#777982', burgundy: '#702a3d', blue: '#344e72', denimGray: '#555965', sole: '#c5c1ba', black: '#24262b', red: '#9c3348', stripe: '#202124', stripeWhite: '#eee8df' };
  return { async mount(canvas, outfit, root) {
    const T = await import('/vendor/three.module.js');
    const renderer = new T.WebGLRenderer({ canvas, antialias: false, alpha: true, powerPreference: 'low-power' });
    renderer.setPixelRatio(Math.min(devicePixelRatio || 1, 1.5));
    renderer.outputColorSpace = T.SRGBColorSpace;
    const scene = new T.Scene(), camera = new T.OrthographicCamera(-2, 2, 2.9, -2.9, .1, 100);
    camera.position.set(0, 3.5, 12); camera.lookAt(0, 2.65, 0);
    scene.add(new T.HemisphereLight(0xffffff, 0x655562, 2.3));
    const light = new T.DirectionalLight(0xffffff, 2.2); light.position.set(-3, 6, 5); scene.add(light);
    const pivot = new T.Group(); scene.add(pivot);
    const cube = new T.BoxGeometry(unit, unit, unit);
    const materials = new Map(), groups = new Map(), voxels = new Map();
    let meshes = [], raf = 0, lastTouch = 0, dragging = false, startX = 0, disposed = false;
    function dot(x, y, z, color) { voxels.set(`${x},${y},${z}`, [x, y, z, color]); }
    function box(x0, x1, y0, y1, z0, z1, color, surface = true) {
      for (let x=x0;x<=x1;x++) for (let y=y0;y<=y1;y++) for (let z=z0;z<=z1;z++)
        if (!surface || x===x0 || x===x1 || y===y0 || y===y1 || z===z0 || z===z1) dot(x,y,z,color);
    }
    function build() {
      for (const m of meshes) { pivot.remove(m); m.dispose(); } meshes=[]; groups.clear(); voxels.clear();
      // Feet and layered soles.
      const shoe = outfit.shoes === 'white_stripes' ? 'white' : outfit.shoes === 'black_stripes' ? 'black' : 'red';
      for (const side of [-1,1]) {
        const x = side*4;
        box(x-3,x+3,0,1,1,9,shoe); box(x-3,x+3,0,0,1,9, outfit.shoes==='red_air'?'black':'sole');
        if (outfit.shoes==='red_air') { for (let z=3;z<=8;z++) dot(x-3,1,z,'stripeWhite'); box(x-2,x+2,2,2,4,8,'red'); }
        else for (let i=0;i<3;i++) { dot(x-3,2,3+i*2,outfit.shoes==='white_stripes'?'stripe':'stripeWhite'); dot(x+3,2,3+i*2,outfit.shoes==='white_stripes'?'stripe':'stripeWhite'); }
      }
      const wide = outfit.pants==='burgundy_wide', pant = outfit.pants==='blue_slim'?'blue':outfit.pants==='gray_slim'?'denimGray':'burgundy';
      for (const side of [-1,1]) { const x=side*4; box(x-(wide?4:3),x+(wide?4:3),2,13,-3,3,pant); box(x-3,x+3,3,3,3,3,pant); }
      box(-8,8,14,25,-4,4,outfit.shirt); box(-8,8,14,14,-4,4,outfit.shirt==='white'?'gray':'black');
      for (const side of [-1,1]) { const x=side*10; box(x-2,x+2,20,25,-3,3,outfit.shirt); box(x-2,x+2,13,19,-2,2,'skin'); box(x-2,x+2,12,13,-2,3,'shadow'); }
      // Raised stitching, ribbed hems, collar and a small chest pocket.
      const shirtTrim = outfit.shirt + 'Trim', shirtLight = outfit.shirt + 'Light';
      box(-8,8,14,14,-4,4,shirtTrim);
      box(-3,3,25,25,4,4,shirtTrim);
      for (const side of [-1,1]) {
        const x=side*10;
        box(x-2,x+2,20,20,-3,3,shirtTrim);
        for (let y=16;y<=22;y++) dot(side*8,y,4,shirtTrim);
        for (let y=15;y<=18;y++) dot(side*(5+(y%2)),y,5,shirtLight);
      }
      box(3,6,21,23,5,5,shirtLight); box(3,6,20,20,5,5,shirtTrim);
      // Denim seams, waistband, rear pockets and stepped knee creases.
      const pantTrim=pant+'Trim', pantLight=pant+'Light';
      box(-7,7,13,13,-3,3,pantTrim);
      for (const side of [-1,1]) {
        const x=side*4, edge=wide?4:3;
        for (let y=3;y<=12;y++) dot(x+side*edge,y,3,pantTrim);
        box(x-2,x+2,9,11,-4,-4,pantLight);
        box(x-2,x+2,8,8,-4,-4,pantTrim);
        for (let i=0;i<4;i++) dot(x-2+i,6+(i%2),4,pantLight);
        box(x-edge,x+edge,2,2,-3,3,pantTrim);
        dot(x,13,4,'sole');
      }
      // Sculpted uppers, tongues, laces and layered sneaker sidewalls.
      for (const side of [-1,1]) {
        const x=side*4, trim=outfit.shoes==='white_stripes'?'gray':'sole';
        box(x-2,x+2,2,3,1,5,shoe);
        box(x-2,x+2,2,2,6,8,shoe);
        box(x-1,x+1,3,3,3,5,trim);
        for (let z=4;z<=7;z++) box(x-1,x+1,3,3,z,z,'stripeWhite');
        if (outfit.shoes==='red_air') {
          for (const edge of [-3,3]) {
            for (let z=2;z<=8;z++) { dot(x+edge,1,z,'sole'); dot(x+edge,2,z,'burgundy'); }
            box(x+edge,x+edge,1,1,2,4,'glass');
          }
        } else {
          for (const edge of [-3,3]) for (let i=0;i<3;i++) {
            dot(x+edge,2,3+i*2,outfit.shoes==='white_stripes'?'stripe':'stripeWhite');
            dot(x+edge,3,2+i*2,outfit.shoes==='white_stripes'?'stripe':'stripeWhite');
          }
        }
      }
      box(-2,2,25,27,-2,2,'skin');
      // Big cubic head, ears, pixel hair and small facial details.
      box(-10,10,28,44,-7,7,'skin'); box(-11,-10,33,37,-2,2,'shadow'); box(10,11,33,37,-2,2,'skin');
      box(-10,10,42,47,-7,7,'hair'); box(-11,11,40,44,-8,-5,'hair');
      for (let x=-10;x<=10;x++) for (let z=-7;z<=7;z++) {
        const h=47+Math.floor(2.5*Math.sin(x*1.8+z*.7)+2*Math.cos(z*1.4-x*.5));
        if ((x+z)%3!==0) dot(x,h,z,((x*z)%5===0)?'hairLight':'hair');
      }
      for (let x=-10;x<=10;x++) if (x%3!==0) box(x,x,39+(x%3),43,7,8,'hair');
      // Rectangular spectacles, two lenses, dark pupils and bridge.
      for (const center of [-5,5]) {
        box(center-4,center+4,33,39,8,8,'glass');
        box(center-3,center+3,34,38,9,9,'lens',false);
        box(center,center+1,35,37,10,10,'eye',false);
      }
      box(-1,1,36,37,9,10,'glass'); box(-1,1,32,34,8,10,'shadow'); box(-2,2,30,30,8,8,'mouth');
      for (const [x,y,z,color] of voxels.values()) {
        if (!groups.has(color)) groups.set(color, []);
        groups.get(color).push([x,y,z]);
      }
      for (const [color, positions] of groups) {
        if (!materials.has(color)) materials.set(color,new T.MeshLambertMaterial({color:colors[color] || colors[color.replace(/Trim|Light/g, '')]}));
        const mesh=new T.InstancedMesh(cube,materials.get(color),positions.length), temp=new T.Object3D();
        positions.forEach(([x,y,z],i)=>{temp.position.set(x*unit,y*unit,z*unit);temp.updateMatrix();mesh.setMatrixAt(i,temp.matrix);const shade=color.endsWith('Trim')?.78:color.endsWith('Light')?1.12:1;const tint=new T.Color().setScalar(shade*(.94+((x*13+y*7+z*3)&3)*.02));mesh.setColorAt(i,tint);});
        mesh.instanceMatrix.needsUpdate=true; mesh.frustumCulled=false; pivot.add(mesh); meshes.push(mesh);
      }
    }
    build();
    function resize() { const w=canvas.clientWidth,h=canvas.clientHeight;if(!w||!h)return;renderer.setSize(w,h,false);const aspect=w/h, halfHeight=Math.max(2.95,1.65/aspect);camera.top=halfHeight;camera.bottom=-halfHeight;camera.left=-halfHeight*aspect;camera.right=halfHeight*aspect;camera.updateProjectionMatrix(); }
    const observer=new ResizeObserver(resize); observer.observe(canvas);resize();
    const changed=()=>build();root.addEventListener('outfit-change',changed);
    canvas.style.touchAction='none';
    canvas.onpointerdown=e=>{dragging=true;startX=e.clientX;canvas.setPointerCapture(e.pointerId);};
    canvas.onpointermove=e=>{if(dragging){pivot.rotation.y+=(e.clientX-startX)*.009;startX=e.clientX;lastTouch=performance.now();}};
    canvas.onpointerup=canvas.onpointercancel=()=>{dragging=false;};
    function tick(t){if(disposed)return;if(!document.hidden){if(!dragging&&t-lastTouch>1300)pivot.rotation.y+=.0025;renderer.render(scene,camera);}raf=requestAnimationFrame(tick);} tick(0);
    return ()=>{disposed=true;cancelAnimationFrame(raf);observer.disconnect();root.removeEventListener('outfit-change',changed);for(const m of meshes)m.dispose();for(const m of materials.values())m.dispose();cube.dispose();renderer.dispose();};
  }};
})();
