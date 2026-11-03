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
  function voxels(character) {
    character.group.updateMatrixWorld(true);
    const result = new Map(), matrix = new T.Matrix4(), point = new T.Vector3(), color = new T.Color();
    character.group.traverse(mesh => {
      if (!mesh.isInstancedMesh) return;
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
    }
    for(const key of pixels.keys()) {
      const [x,y,z]=key.split(',').map(Number);
      if(y<42)continue;
      assert.ok([[1,0,0],[-1,0,0],[0,1,0],[0,-1,0],[0,0,1],[0,0,-1]].some(([dx,dy,dz])=>pixels.has(`${x+dx},${y+dy},${z+dz}`)), 'hair has no floating top pixels');
    }
  }
  assert.equal(signatures.size, 3, 'all three hairstyles have distinct geometry');
  for(const field of ['hair_color','eye_color']) {
    const samples = new Set();
    for(const [value] of choices[field]) {
      outfit[field]=value; character.rebuild();
      const pixels=voxels(character);
      samples.add(pixels.get(field==='hair_color'?'0,44,-8':'-6,35,8'));
      assert.equal(pixels.get('0,20,4'), initial.get('0,20,4'), 'appearance colours leave clothing unchanged');
      assert.ok(icon(field,value,outfit).includes('<svg'), 'colour has a visual icon');
    }
    assert.equal(samples.size, choices[field].length, field+' changes actual voxel colours');
  }
  outfit.gender='female'; character.rebuild();
  const female=voxels(character);
  assert.ok(initial.has('8,18,4') && !female.has('8,18,4'), 'female has a different waist');
  assert.ok(initial.has('9,28,0') && !female.has('9,28,0'), 'female has a softer jaw');
  assert.ok(female.has('0,22,6')&&!initial.has('0,22,6'), 'female chest has real depth');
  assert.ok(female.has('0,21,5')&&female.has('6,22,5'), 'chest steps into the shirt at bottom and sides');
  assert.ok(female.has('7,15,4')&&!female.has('7,18,4'), 'hips taper into the waist');
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
      assert.ok(count<6500,'geometry stays below the previous smallest 6829-voxel model');
      const pixels=voxels(character);
      if(gender==='female')assert.ok(pixels.has('0,22,6'),'every shirt preserves fitted volume');
      assert.ok(pixels.has('0,24,5'),'every shirt keeps its collar');
    }
  for(const [gender] of choices.gender)for(const [hairstyle] of choices.hairstyle) {
    const samples=new Set();Object.assign(outfit,{gender,hairstyle});
    for(const [hair_color] of choices.hair_color) {
      outfit.hair_color=hair_color;character.rebuild();samples.add(voxels(character).get('0,44,-8'));
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
  for(const [gender] of choices.gender)for(const [pants] of choices.pants) {
    Object.assign(outfit,{gender,pants});character.rebuild();
    const resources=[];character.group.traverse(mesh=>{if(mesh.isInstancedMesh)resources.push([mesh,mesh.count,mesh.instanceMatrix.array,mesh.geometry,mesh.material]);});
    for(const sprint of [false,true])for(let frame=0;frame<90;frame++) {
      character.walk((sprint?3:1.7)/60,1/60,sprint);character.group.updateMatrixWorld(true);
      for(const side of ['Left','Right']) {
        const foot=character.group.getObjectByName('foot'+side),q=foot.getWorldQuaternion(new T.Quaternion());
        assert.ok(Math.abs(q.x)<1e-6,'foot remains level through the IK stride');
        if(frame%15)continue;
        for(const [parent,child] of [['torso','arm'],['arm','forearm'],['torso','thigh'],['thigh','shin'],['shin','foot']]) {
          const a=character.group.getObjectByName(parent==='torso'?parent:parent+side),b=character.group.getObjectByName(child+side);
          const origin=b.getWorldPosition(new T.Vector3()),left=points(a,origin),right=points(b,origin);
          assert.ok(left.some(p=>right.some(q=>p.distanceTo(q)<.16)),`${gender} ${pants} ${child} seam stays connected`);
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
  assert.equal(voxels(other).get('0,44,-8'),initial.get('0,44,-8'),'characters do not share mutable colour state');
  let released=0;
  character.group.traverse(node=>{if(node.isInstancedMesh)node.addEventListener('dispose',()=>released++);});
  character.rebuild();
  assert.equal(released,11,'rebuild releases every previous instanced body mesh');
  character.dispose(); other.dispose();
  console.log(`NORA appearance: 162 shape combinations, fitted chest, flat eyes, connected hair, all colours, saved IDs/legacy outfits, articulated seams, IK and cleanup passed; max ${maxVoxels} voxels, 11 shared-geometry batches.`);
} finally {
  await rm(temp,{recursive:true,force:true});
}
