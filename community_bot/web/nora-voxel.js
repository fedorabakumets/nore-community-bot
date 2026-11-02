'use strict';
window.NoraVoxel = (() => {
  const unit = .105;
  const colors = { skin: '#f2a07d', shadow: '#d67c64', hair: '#29252c', hairLight: '#39333b', glass: '#171a20', lens: '#e6c3ae', eye: '#24313b', mouth: '#9e5351', white: '#e9e7e1', gray: '#777982', burgundy: '#702a3d', blue: '#344e72', denimGray: '#555965', sole: '#c5c1ba', black: '#24262b', red: '#9c3348', stripe: '#202124', stripeWhite: '#eee8df' };
  return { async mount(canvas, outfit, root) {
    const T = await import('/vendor/three.module.js');
    const renderer = new T.WebGLRenderer({ canvas, antialias: false, alpha: true, powerPreference: 'low-power' });
    renderer.setPixelRatio(Math.min(devicePixelRatio || 1, 1.5));
    renderer.outputColorSpace = T.SRGBColorSpace;
    const scene = new T.Scene(), camera = new T.PerspectiveCamera(35, 1, .1, 100);
    camera.position.set(4, 3.5, 9.5); camera.lookAt(0, 2.5, 0);
    scene.add(new T.HemisphereLight(0xffffff, 0x655562, 2.3));
    const light = new T.DirectionalLight(0xffffff, 2.2); light.position.set(-3, 6, 5); scene.add(light);
    const pivot = new T.Group(); scene.add(pivot);
    const cube = new T.BoxGeometry(unit, unit, unit);
    const materials = new Map(), groups = new Map();
    let meshes = [], raf = 0, lastTouch = 0, dragging = false, startX = 0, disposed = false;
    function dot(x, y, z, color) { if (!groups.has(color)) groups.set(color, []); groups.get(color).push([x, y, z]); }
    function box(x0, x1, y0, y1, z0, z1, color, surface = true) {
      for (let x=x0;x<=x1;x++) for (let y=y0;y<=y1;y++) for (let z=z0;z<=z1;z++)
        if (!surface || x===x0 || x===x1 || y===y0 || y===y1 || z===z0 || z===z1) dot(x,y,z,color);
    }
    function build() {
      for (const m of meshes) { pivot.remove(m); m.dispose(); } meshes=[]; groups.clear();
      // Feet and layered soles.
      const shoe = outfit.shoes === 'white_stripes' ? 'white' : outfit.shoes === 'black_stripes' ? 'black' : 'red';
      for (const side of [-1,1]) {
        const x = side*4;
        box(x-3,x+3,0,1,1,9,shoe); box(x-3,x+3,0,0,1,9, outfit.shoes==='red_air'?'black':'sole');
        if (outfit.shoes==='red_air') { for (let z=3;z<=8;z++) dot(x-3,1,z,'stripeWhite'); box(x-2,x+2,2,2,4,8,'red'); }
        else for (let i=0;i<3;i++) { dot(x-3,2,3+i*2,outfit.shoes==='white_stripes'?'stripe':'stripeWhite'); dot(x+3,2,3+i*2,outfit.shoes==='white_stripes'?'stripe':'stripeWhite'); }
      }
      const wide = outfit.pants==='burgundy_wide', pant = outfit.pants==='blue_slim'?'blue':outfit.pants==='gray_slim'?'denimGray':'burgundy';
      for (const side of [-1,1]) { const x=side*4; box(x-(wide?4:3),x+(wide?4:3),2,13,-3,3,pant); box(x-3,x+3,3,3,3,3,'shadow'); }
      box(-8,8,14,25,-4,4,outfit.shirt); box(-8,8,14,14,-4,4,outfit.shirt==='white'?'gray':'black');
      for (const side of [-1,1]) { const x=side*10; box(x-2,x+2,20,25,-3,3,outfit.shirt); box(x-2,x+2,13,19,-2,2,'skin'); box(x-2,x+2,12,13,-2,3,'shadow'); }
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
      for (const [color, positions] of groups) {
        if (!materials.has(color)) materials.set(color,new T.MeshLambertMaterial({color:colors[color]}));
        const mesh=new T.InstancedMesh(cube,materials.get(color),positions.length), temp=new T.Object3D();
        positions.forEach(([x,y,z],i)=>{temp.position.set(x*unit,y*unit,z*unit);temp.updateMatrix();mesh.setMatrixAt(i,temp.matrix);});
        mesh.instanceMatrix.needsUpdate=true; mesh.frustumCulled=false; pivot.add(mesh); meshes.push(mesh);
      }
    }
    build();
    function resize() { const w=canvas.clientWidth,h=canvas.clientHeight;if(!w||!h)return;renderer.setSize(w,h,false);camera.aspect=w/h;camera.updateProjectionMatrix(); }
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
