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
  assert.ok(initial.has('-5,35,10'), 'pupil is visible');
  assert.equal(initial.has('0,36,9'), false, 'no glasses bridge');
  assert.equal(initial.has('-9,38,8'), false, 'no glasses frames at temples');
  const signatures = new Set();
  for (const [style] of choices.hairstyle) {
    outfit.hairstyle = style; character.rebuild();
    const pixels = voxels(character);
    signatures.add([...pixels.keys()].sort().join('|'));
    if(style==='bob') assert.ok(pixels.has('-12,29,0'), 'bob has long side panels');
    if(style==='ponytail') assert.ok(pixels.has('0,26,-14'), 'ponytail extends below head at back');
  }
  assert.equal(signatures.size, 3, 'all three hairstyles have distinct geometry');
  for(const field of ['hair_color','eye_color']) {
    const samples = new Set();
    for(const [value] of choices[field]) {
      outfit[field]=value; character.rebuild();
      const pixels=voxels(character);
      samples.add(pixels.get(field==='hair_color'?'0,44,-8':'-6,35,9'));
      assert.equal(pixels.get('0,20,4'), initial.get('0,20,4'), 'appearance colours leave clothing unchanged');
      assert.ok(icon(field,value,outfit).includes('<svg'), 'colour has a visual icon');
    }
    assert.equal(samples.size, choices[field].length, field+' changes actual voxel colours');
  }
  outfit.gender='female'; character.rebuild();
  const female=voxels(character);
  assert.ok(initial.has('8,18,4') && !female.has('8,18,4'), 'female has a different waist');
  assert.ok(initial.has('10,28,0') && !female.has('10,28,0'), 'female has a softer jaw');
  const other=createCharacter(T,defaults);
  assert.equal(voxels(other).get('0,44,-8'),initial.get('0,44,-8'),'characters do not share mutable colour state');
  let released=0;
  character.group.traverse(node=>{if(node.isInstancedMesh)node.addEventListener('dispose',()=>released++);});
  character.rebuild();
  assert.equal(released,11,'rebuild releases every previous instanced body mesh');
  character.dispose(); other.dispose();
  console.log('NORA appearance: distinct models and hairstyles, all hair/eye colours, no glasses, isolated palettes and mesh cleanup passed.');
} finally {
  await rm(temp,{recursive:true,force:true});
}
