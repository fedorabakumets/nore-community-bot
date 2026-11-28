// Run with node tests/nora_appearance.mjs. Uses real Three.js geometry, no GPU or network.
import assert from 'node:assert/strict';
import {readFile, writeFile, mkdtemp, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import vm from 'node:vm';

const web = new URL('../community_bot/web/', import.meta.url);
const temp = await mkdtemp(join(tmpdir(), 'nora-appearance-'));
try {
  await writeFile(join(temp, 'three.core.mjs'), await readFile(new URL('vendor/three.core.js', web)));
  const module = (await readFile(new URL('vendor/three.module.js', web), 'utf8')).replaceAll('./three.core.js', './three.core.mjs');
  await writeFile(join(temp, 'three.module.mjs'), module);
  const T = await import(pathToFileURL(join(temp, 'three.module.mjs')).href);
  const context = {window:{}};
  vm.runInNewContext(await readFile(new URL('nora-voxel.js', web), 'utf8'), context);
  const {defaults, choices, createCharacter, icon} = context.window.NoraVoxel;
  function voxels(character, part) {
    character.group.updateMatrixWorld(true);
    const result = new Map(), matrix = new T.Matrix4(), point = new T.Vector3(), color = new T.Color();
    character.group.traverse(mesh => {
      if (!mesh.isInstancedMesh || (part && mesh.parent.name!==part)) return;
      for(let i=0;i<mesh.count;i++) {
        mesh.getMatrixAt(i, matrix); matrix.premultiply(mesh.matrixWorld);
        point.setFromMatrixPosition(matrix); mesh.getColorAt(i, color);
        const key = point.toArray().map(n => Math.round(n/.105)).join(',');
        result.set(key, color.toArray().map(n=>n.toFixed(5)).join(','));
      }
    });
    return result;
  }
  const outfit = {...defaults}, character = createCharacter(T, outfit), initial = voxels(character);
  const fadeMeshes=[];character.group.traverse(m=>{if(m.isInstancedMesh)fadeMeshes.push(m);});
  const fadeMaterial=fadeMeshes[0].material, version=fadeMaterial.version;
  for(const value of [0,.05,.3,.8,1]){
    character.setOpacity(value);
    assert.ok(fadeMeshes.every(m=>m.visible===(value>.001)));
    assert.equal(fadeMaterial.transparent,false);assert.equal(fadeMaterial.depthWrite,true);
    assert.equal(fadeMaterial.version,version,'fade does not recompile/switch transparency mode');
  }
  const skinSample=initial.get('0,33,8');assert.ok(skinSample,'nose provides a visible skin sample');
  assert.ok(initial.has('-7,35,8'), 'eye whites are visible');
  assert.ok(initial.has('-5,35,8'), 'pupil is visible on the eye plane');
  assert.notEqual(initial.get('-5,35,8'), initial.get('-6,35,8'), 'pupil contrasts with iris');
  assert.notEqual(initial.get('-7,35,8'), initial.get('-6,35,8'), 'iris contrasts with whites');
  assert.ok(![...initial.keys()].some(key=>{const [x,y,z]=key.split(',').map(Number);return Math.abs(x)<=8&&y>=30&&y<=38&&z>8;}), 'face relief is at most one voxel');
  assert.equal(initial.has('0,36,9'), false, 'no glasses bridge');
  assert.equal(initial.has('-9,38,8'), false, 'no glasses frames at temples');
  const signatures = new Set();
  for (const [style] of choices.hairstyle) {
    outfit.hairstyle = style; character.rebuild();
    const pixels = voxels(character);
    signatures.add([...pixels.keys()].sort().join('|'));
    if(style==='bob') assert.ok(pixels.has('-10,29,0'), 'bob has tapered long side panels');
    if(style==='ponytail') {
      assert.ok(pixels.has('0,26,-12'), 'ponytail extends below head at back');
      assert.ok(pixels.has('-9,29,8')&&pixels.has('9,29,8'), 'front strands frame both sides');
      for(const side of [-1,1])assert.equal(pixels.get(`${side*10},41,7`),pixels.get('3,49,0'),'ponytail sides join the fringe without scalp pinholes');
    }
    for(const [key,color] of pixels) {
      const [x,y,z]=key.split(',').map(Number);
      if(y<42)continue;
      assert.notEqual(color,skinSample,'hair covers the upper scalp, including bevel corners');
      assert.ok([[1,0,0],[-1,0,0],[0,1,0],[0,-1,0],[0,0,1],[0,0,-1]].some(([dx,dy,dz])=>pixels.has(`${x+dx},${y+dy},${z+dz}`)), 'hair has no floating top pixels');
    }
  }
  assert.equal(signatures.size, 3, 'all three hairstyles have distinct geometry');
  for(const field of ['hair_color','eye_color']) {
    const samples = new Set();
    for(const [value] of choices[field]) {
      outfit[field]=value; character.rebuild();
      const pixels=voxels(character);
      const sample=pixels.get(field==='hair_color'?'3,49,0':'-6,35,8');
      assert.ok(sample,'colour sample is on the visible shell');samples.add(sample);
      assert.equal(pixels.get('0,20,4'), initial.get('0,20,4'), 'appearance colours leave clothing unchanged');
      assert.ok(icon(field,value,outfit).includes('<svg'), 'colour has a visual icon');
    }
    assert.equal(samples.size, choices[field].length, field+' changes actual voxel colours');
  }
  outfit.gender='female'; character.rebuild();
  const female=voxels(character);
  assert.ok(initial.has('8,18,4') && !female.has('8,18,4'), 'female has a different waist');
  assert.ok(initial.has('9,28,0') && !female.has('9,28,0'), 'female has a softer jaw');
  assert.ok(female.has('0,22,8')&&!initial.has('0,22,8'), 'female chest projects two voxels beyond V1');
  assert.ok(female.has('0,20,5')&&female.has('7,22,5'), 'chest steps into the shirt at bottom and sides');
  for(let x=-3;x<=3;x++)assert.ok(female.has(`${x},22,8`),'front volume is one connected band, not separate blocks');
  assert.ok(female.has('8,15,4')&&!female.has('6,18,3'), 'hips are wider and waist is narrower than V1');
  function fittedSilhouette(character) {
    const body=voxels(character,'torso');
    const profile=new Map();
    for(const key of body.keys()) {
      const [x,y,z]=key.split(',').map(Number);
      if(y<14||y>25)continue;
      if(!profile.has(y))profile.set(y,{width:0,back:Infinity,front:-Infinity});
      const row=profile.get(y);row.width=Math.max(row.width,Math.abs(x));row.back=Math.min(row.back,z);row.front=Math.max(row.front,z);
    }
    assert.equal(profile.get(18).width,5,'waist is eleven voxels across');
    assert.equal(profile.get(18).back,-3,'waist also tapers in profile');
    assert.equal(profile.get(18).front,3,'no detached fold protrudes at the waist');
    assert.equal(profile.get(14).width,8,'hip hem is seventeen voxels across');
    for(let y=15;y<=18;y++)assert.ok(Math.abs(profile.get(y).width-profile.get(y-1).width)<=1,'waist to hips uses single-voxel steps');
    assert.equal(profile.get(22).front,8,'chest silhouette remains visible with every shirt');
    for(let y=14;y<=25;y++) {
      const row=profile.get(y),depth=y===18||y===19?3:4;
      for(let x=-row.width;x<=row.width;x++) {
        assert.ok(body.has(`${x},${y},${-depth}`),'back shell has no missing columns');
        assert.ok(Array.from({length:9-depth},(_,i)=>i+depth).some(z=>body.has(`${x},${y},${z}`)),'front shell has no missing columns');
      }
    }
    for(const side of [-1,1]) {
      const thigh=voxels(character,'thigh'+(side<0?'Left':'Right'));
      assert.ok(thigh.has(`${side*4},11,-5`),'rear seat is actual geometry on the moving thigh');
      assert.ok(thigh.has(`${side*8},13,-4`),'upper pants meet the widened hip hem');
    }
  }
  fittedSilhouette(character);
  const expectedChoices = {
    gender:['male','female'], hairstyle:['crop','bob','ponytail'],
    hair_color:['black','chestnut','brown','blonde','ginger','ash','rose','blue'],
    eye_color:['brown','hazel','green','blue','gray','violet'], shirt:['white','gray','burgundy'],
    pants:['blue_slim','gray_slim','burgundy_wide'], shoes:['white_stripes','black_stripes','red_air'],
  };
  for(const [field,values] of Object.entries(expectedChoices)) {
    assert.deepEqual(Array.from(choices[field],item=>item[0]), values, field+' retains saved identifiers');
    for(const value of values) assert.ok(icon(field,value,outfit).includes('<svg'), field+' has a thumbnail');
  }
  let maxVoxels=0;
  // Every shape combination, including previously saved clothing-only profiles.
  for(const [gender] of choices.gender)for(const [hairstyle] of choices.hairstyle)
    for(const [shirt] of choices.shirt)for(const [pants] of choices.pants)for(const [shoes] of choices.shoes) {
      Object.assign(outfit,{gender,hairstyle,shirt,pants,shoes});character.rebuild();
      let count=0,meshCount=0;const materials=new Set(),geometries=new Set();
      character.group.traverse(mesh=>{
        if(!mesh.isMesh)return;
        assert.ok(mesh.isInstancedMesh,'all geometry remains instanced');
        count+=mesh.count;meshCount++;materials.add(mesh.material);geometries.add(mesh.geometry);
        assert.equal(mesh.geometry.parameters.width,.105,'voxel size is unchanged');
        assert.ok([...mesh.instanceColor.array].every(Number.isFinite),'all colour variants resolve');
      });
      assert.equal(meshCount,11,'joint batches stay constant');
      assert.equal(materials.size,1,'all joints share one material');assert.equal(geometries.size,1,'all joints share one cube');
      maxVoxels=Math.max(maxVoxels,count);
      assert.ok(count<5000,'V4 removes hidden scalp faces and stays below five thousand instances');
      const pixels=voxels(character);
      if(gender==='female')fittedSilhouette(character);
      assert.ok(pixels.has('0,24,5'),'every shirt keeps its collar');
      const body=voxels(character,'torso');
      assert.ok(![...body.keys()].some(key=>{
        const [x,y,z]=key.split(',').map(Number);
        return Math.abs(x)<10&&y>31&&y<44&&Math.abs(z)<7;
      }),'solid head interior never consumes rendered instances');
      // Surface continuity and macro planes, independently of the construction boxes.
      const crownWidths=[];
      for(let y=44;y<=49;y++) {
        const row=[...body.keys()].map(key=>key.split(',').map(Number)).filter(p=>p[1]===y&&p[2]===0);
        crownWidths.push(Math.max(...row.map(p=>Math.abs(p[0]))));
      }
      assert.ok(new Set(crownWidths).size<=3,'crown reads as at most three broad tiers');
      assert.ok(crownWidths.at(-1)>=8,'simplified crown retains a broad top volume');
      const cloth=body.get('0,17,4');
      for(const side of [-1,1])for(let y=15;y<=17;y++)
        assert.equal(body.get(`${side*5},${y},4`),cloth,'no isolated bright cloth stripes');
      if(gender==='female')for(let x=-4;x<=4;x++)for(let y=22;y<=23;y++)
        assert.equal(body.get(`${x},${y},8`),cloth,'chest has one broad continuous front plane');
    }
  for(const [gender] of choices.gender)for(const [hairstyle] of choices.hairstyle) {
    const samples=new Set();Object.assign(outfit,{gender,hairstyle});
    for(const [hair_color] of choices.hair_color) {
      outfit.hair_color=hair_color;character.rebuild();
      const pixels=voxels(character),sample=pixels.get('3,49,0');
      assert.ok(sample,'every hairstyle has an exposed crown');samples.add(sample);
      for(const x of [4,5])assert.equal(pixels.get(`${x},49,0`),sample,'hair uses broad tones without a per-cube checker');
    }
    assert.equal(samples.size,8,'every hairstyle in either gender remains recolourable');
  }
  const legacy=createCharacter(T,{shirt:'white',pants:'blue_slim',shoes:'white_stripes'});
  assert.deepEqual(voxels(legacy),initial,'old clothing-only profiles still render the default appearance');legacy.dispose();
  // Exercise full gait cycles with real transformed cubes at each joint seam.
  function points(node,origin) {
    const result=[],matrix=new T.Matrix4(),point=new T.Vector3();
    for(const mesh of node.children)if(mesh.isInstancedMesh)for(let i=0;i<mesh.count;i++) {
      mesh.getMatrixAt(i,matrix);matrix.premultiply(mesh.matrixWorld);point.setFromMatrixPosition(matrix);
      if(point.distanceTo(origin)<.42)result.push(point.clone());
    }
    return result;
  }
  // Conservative cube bounds in torso space catch visible arm/figure penetration.
  // Exclude shoulder and elbow caps, whose small overlaps are intentional.
  function cells(node,torso,select=()=>true) {
    const result=[],matrix=new T.Matrix4(),relative=new T.Matrix4();
    const inverse=new T.Matrix4().copy(torso.matrixWorld).invert();
    const cube=new T.Box3(new T.Vector3(-.0525,-.0525,-.0525),new T.Vector3(.0525,.0525,.0525));
    for(const mesh of node.children)if(mesh.isInstancedMesh) {
      relative.copy(inverse).multiply(mesh.matrixWorld);
      for(let i=0;i<mesh.count;i++) {
        mesh.getMatrixAt(i,matrix);
        if(select(matrix.elements[12]/.105,matrix.elements[13]/.105,matrix.elements[14]/.105))
          result.push(cube.clone().applyMatrix4(matrix.premultiply(relative)));
      }
    }
    return result;
  }
  function penetrates(a,b) {
    return ['x','y','z'].every(axis=>Math.min(a.max[axis],b.max[axis])-Math.max(a.min[axis],b.min[axis])>1e-5);
  }
  for(const [gender] of choices.gender)for(const [pants] of choices.pants) {
    Object.assign(outfit,{gender,pants});character.rebuild();
    const resources=[];character.group.traverse(mesh=>{if(mesh.isInstancedMesh)resources.push([mesh,mesh.count,mesh.instanceMatrix.array,mesh.geometry,mesh.material]);});
    for(const sprint of [false,true])for(let frame=0;frame<90;frame++) {
      character.animateMotion((sprint?3:1.7)/60,1/60,sprint);character.group.updateMatrixWorld(true);
      for(const side of ['Left','Right']) {
        const foot=character.group.getObjectByName('foot'+side),q=foot.getWorldQuaternion(new T.Quaternion());
        assert.ok(Math.abs(q.x)<1e-6,'foot remains level through the IK stride');
        if(frame%15)continue;
        for(const [parent,child] of [['torso','arm'],['arm','forearm'],['torso','thigh'],['thigh','shin'],['shin','foot']]) {
          const a=character.group.getObjectByName(parent==='torso'?parent:parent+side),b=character.group.getObjectByName(child+side);
          const origin=b.getWorldPosition(new T.Vector3()),left=points(a,origin),right=points(b,origin);
          assert.ok(left.some(p=>right.some(q=>p.distanceTo(q)<.16)),`${gender} ${pants} ${child} seam stays connected`);
        }
        if(gender==='female') {
          const torso=character.group.getObjectByName('torso');
          const figure=cells(torso,torso,(_x,y,z)=>(y+13.5>=14&&y+13.5<=16)||(y+13.5>=20&&y+13.5<=24&&z>4));
          figure.push(...cells(character.group.getObjectByName('thigh'+side),torso,(_x,y)=>y>=-3.5));
          for(const limb of ['arm','forearm']) {
            const arm=cells(character.group.getObjectByName(limb+side),torso);
            const touching=arm.find(a=>figure.some(b=>penetrates(a,b)));
            assert.ok(!touching,`${pants} ${sprint?'run':'walk'} frame ${frame}: ${limb}${side} clears chest and hips; ${JSON.stringify(touching)}`);
          }
        }
      }
    }
    for(const [mesh,count,matrices,geometry,material] of resources) {
      assert.equal(mesh.count,count);assert.equal(mesh.instanceMatrix.array,matrices,'animation does not reallocate instances');
      assert.equal(mesh.geometry,geometry);assert.equal(mesh.material,material);
      assert.ok(mesh.matrixWorld.elements.every(Number.isFinite),'animated transforms stay finite');
    }
  }
  const other=createCharacter(T,defaults);
  assert.equal(voxels(other).get('3,49,0'),initial.get('3,49,0'),'characters do not share mutable colour state');
  let released=0;
  character.group.traverse(node=>{if(node.isInstancedMesh)node.addEventListener('dispose',()=>released++);});
  character.rebuild();
  assert.equal(released,11,'rebuild releases every previous instanced body mesh');
  character.dispose(); other.dispose();
  console.log(`NORA appearance: 162 shape combinations, V4 macro crown/chest planes and quiet cloth, hair coverage/broad tones, V2 chest/waist/hips/rear shell, arm clearance, flat eyes, connected hair, all colours, saved IDs/legacy outfits, articulated seams, IK and cleanup passed; max ${maxVoxels} voxels, 11 shared-geometry batches.`);
} finally {
  await rm(temp,{recursive:true,force:true});
}
