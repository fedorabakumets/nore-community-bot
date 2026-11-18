'use strict';
window.NoraObservatory = (() => {
  const title = 'Воспоминание', room = 'observatory';
  const chapters = [
    ['Двор под грозой', 'Держись вдали от знаков на земле. Подними печать у ворот.'],
    ['Крипта колоколов', 'На камне высечено: «Что оставил огонь? Что скрыло тропу? Что разбудило небо?»'],
    ['Галерея стражей', 'Пережди стражей за простенками и зажги фонарь у дальних ворот.'],
    ['Разбитая часовня', 'Пересеки двор и стой в круге у алтаря, пока ритуал не закончится.'],
  ];

  async function load() {
    const response = await fetch('/nora-observatory.json?v=memory');
    if (!response.ok) throw Error('Не удалось загрузить воспоминание');
    return response.json();
  }

  function create(T, geometry, layout) {
    const {portal: entrance, walls, gates, safe, bounds, relics, strikes, guardians} = layout;
    const reduced = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
    const course = new T.Group();
    course.name = 'nora-observatory'; course.visible = false;
    const materials = [], textures = [], meshes = [], geometries = [];
    const stone = new T.MeshLambertMaterial(), glow = new T.MeshBasicMaterial();
    materials.push(stone, glow);
    const blocks = [], accents = [];
    const box = (list, x, y, z, w, h, d, color) => list.push([x, y, z, w, h, d, color]);
    function batch(parent, material, pieces) {
      const mesh = new T.InstancedMesh(geometry, material, pieces.length);
      const model = new T.Object3D(), tint = new T.Color();
      pieces.forEach(([x, y, z, w, h, d, color], i) => {
        model.position.set(x, y, z); model.scale.set(w, h, d); model.updateMatrix();
        mesh.setMatrixAt(i, model.matrix); mesh.setColorAt(i, tint.set(color));
      });
      mesh.computeBoundingSphere(); parent.add(mesh); meshes.push(mesh);
      return mesh;
    }

    const floor = ['#393640', '#3f3a43', '#353540', '#48404a', '#343740'];
    const stoneColors = ['#504956', '#47404d', '#3d3845', '#5c5260'];
    for (let x = -8; x < 8; x++) for (let z = -53; z < 35; z++) {
      const seed = Math.abs(x * 541 + z * 137 + x * z * 11);
      const crypt = z < 9 && z >= -9;
      box(blocks, x + .5, -.15, z + .5, 1, .30, 1, crypt ? stoneColors[seed % 4] : floor[seed % 5]);
      if (!crypt && seed % 17 < 3) {
        box(accents, x + .58, .004, z + .52, .64, .012, .65, seed % 2 ? '#282937' : '#2e303d');
      }
      if (Math.abs(x + .5) > 7.3 && z % 2 === 0) {
        const h = 1.2 + seed % 13 * .22;
        box(blocks, Math.sign(x) * 8.36, h / 2, z, .64, h, 2.06, stoneColors[seed % 4]);
        if (z % 6 === 0) {
          box(blocks, Math.sign(x) * 8.32, 2.4, z, 1.2, 4.8, 1.2, '#332d3a');
          box(blocks, Math.sign(x) * 8.27, 4.9, z, 1.43, .35, 1.42, '#514858');
        }
      }
    }
    const boxes = [], cameraBoxes = [];
    for (const side of [-1, 1]) {
      for (const z of [21, 16.8, -33.5, -44.5]) {
        const x = side * (z === 21 ? 2.55 : z > 10 ? 4.4 : 6.5);
        box(blocks, x, .23, z, 1.0, .46, 1.22, '#514758');
        box(blocks, x, 1.17, z, .48, 1.63, .51, '#3f3443');
        box(blocks, x, 1.96, z, .69, .27, .63, '#675568');
        box(accents, x, 2.19, z, .23, .28, .22, '#b88165');
        box(accents, x - side * .07, 2.36, z, .13, .13, .13, '#e7bc8c');
      }
      for (const z of [20.8, 13.1, -31.8, -42.8]) {
        const x = side * 8.2;
        box(blocks, x, 2.6, z, .43, 5.2, .48, '#2d2634');
        for (let branch = 0; branch < 5; branch++) {
          const spread = 1 + branch % 3;
          box(blocks, x + side * (spread * .35 - .3), 3 + branch * .65,
            z + branch % 2 * .58, 1.6 - branch * .12, .26, .31, '#362b38');
        }
      }
      for (let z = -8; z <= 8; z += 4) {
        box(blocks, side * 7.48, 2.65, z, .85, 5.3, .56, '#534453');
        box(blocks, side * 5, 4.91, z, 5.2, .36, .59, '#504251');
        box(blocks, side * 2.8, 5.22, z, 4.9, .39, .67, '#473947');
        box(accents, side * 7.02, 2.77, z, .1, .28, .19, '#ae7b69');
      }
    }
    function collision(x, z, w, d, h) {
      const edges = [x - w / 2, x + w / 2, z - d / 2, z + d / 2];
      cameraBoxes.push([edges[0], edges[1], 0, h, edges[2], edges[3]]);
      return edges;
    }
    for (const [x, z, w, d] of walls) {
      const h = Math.abs(x) < 1 ? 3.8 : 2.7;
      boxes.push(collision(x, z, w, d, h));
      box(blocks, x, h / 2, z, w, h, d, '#49424e');
      for (let y = .55; y < h - .1; y += .53) box(blocks, x, y, z, w + .024, .027, d + .024, '#2d2935');
      box(blocks, x, h, z, w + .15, .23, d + .14, '#59515f');
    }
    const gateParts = gates.map((z, index) => {
      for (const side of [-1, 1]) {
        box(blocks, side * 4.48, 2, z, .75, 4, .94, '#635264');
        box(blocks, side * 3.76, 3.68, z, 1.76, .74, .96, '#5b4e5e');
        box(accents, side * 4.1, 2.37, z + .49, .15, .34, .06, '#b08464');
      }
      box(blocks, 0, 4.26, z, 7.18, .5, .9, '#4d4253');
      box(blocks, 0, 4.59, z, 3, .17, .91, '#5f5262');
      const bars = [];
      for (let i = -8; i <= 8; i++) {
        box(bars, i * .51, 1.81, z, .14, 3.62, .36, '#24212e');
        box(bars, i * .51, 2.35, z + .19, .09, .13, .024, '#ad7964');
      }
      box(bars, 0, 1.36, z, 8.7, .18, .28, '#695263');
      const group = new T.Group();
      group.name = 'memory-gate-' + (index + 1); course.add(group);
      batch(group, stone, bars);
      return {group, edges: [-9, 9, z - .36, z + .36]};
    });

    function label(text, x, y, z) {
      const canvas = document.createElement('canvas');
      canvas.width = 384; canvas.height = 64;
      const ctx = canvas.getContext('2d');
      ctx.fillStyle = '#211925'; ctx.fillRect(0, 0, 384, 64);
      ctx.fillStyle = '#dcb291'; ctx.font = 'bold 27px monospace'; ctx.textAlign = 'center';
      ctx.fillText(text, 192, 41, 362);
      const map = new T.CanvasTexture(canvas); map.colorSpace = T.SRGBColorSpace;
      const material = new T.SpriteMaterial({map, depthWrite: false, transparent: true, opacity: .87});
      const sprite = new T.Sprite(material);
      sprite.position.set(x, y, z); sprite.scale.set(2.56, .42, 1); course.add(sprite);
      textures.push(map); materials.push(material);
    }
    for (const [id, [x, z, text]] of Object.entries(relics)) {
      box(blocks, x, .22, z, .6, .44, .6, '#4f4653');
      box(blocks, x, .73, z, .42, .62, .43, '#574951');
      box(accents, x, 1.12, z, .22, .22, .22, id === 'lantern' ? '#e6a05b' : '#bc8f74');
      if (layout.bellOrder.includes(id)) {
        box(blocks, x, 1.63, z, 1.20, .14, .27, '#543844');
        box(blocks, x, 1.34, z, .43, .48, .48, '#a1785d');
        box(blocks, x, 1.12, z, .62, .12, .61, '#9c6e57');
        label(text, x, 1.97, z);
      }
    }
    const [altarX, altarZ] = safe.at(-1);
    for (let i = 0; i < 20; i++) {
      const a = i / 20 * Math.PI * 2;
      box(accents, altarX + Math.cos(a) * 1.23, .018, altarZ + Math.sin(a) * 1.23,
        .19, .036, .19, i % 2 ? '#bd816b' : '#76586f');
    }
    box(blocks, 0, .41, altarZ - 2.3, 2.9, .81, 1.05, '#5d4c5e');
    box(blocks, 0, .86, altarZ - 2.3, 3.07, .21, 1.16, '#75616e');
    for (const side of [-1, 1]) {
      for (let i = 0; i < 3; i++) {
        const x = side * (3.4 + i * .42), z = -48.5 + i * 2.2;
        box(blocks, x, .28, z, 1.3, .56, 1.48, '#524652');
        box(blocks, x, 1.43, z, .71, 1.8, .7, '#36303b');
        box(blocks, x, 2.44, z, .66, .72, .64, '#443845');
        box(accents, x, 2.43, z + .33, .32, .047, .038, '#825264');
      }
    }
    for (let i = 0; i < 48; i++) {
      const sign = i % 2 ? 1 : -1, z = 27 - (i * 37 % 78);
      if (z < 9 && z > -9) continue;
      const x = sign * (7 + (i % 4) * .24), h = .38 + (i % 7) * .15;
      box(blocks, x, h / 2, z, .43, h, .24, '#565062');
      box(blocks, x, h * .83, z, .72, .12, .26, '#413946');
      if (i % 3 === 0) box(accents, x, .15, z + .52, .12, .3, .11, '#a97866');
    }
    batch(course, stone, blocks); batch(course, glow, accents);

    const shadows = guardians.map(([z]) => {
      const group = new T.Group();
      group.name = 'memory-guardian'; group.position.z = z; course.add(group);
      batch(group, stone, [
        [0, .42, 0, .96, .85, .8, '#231e2a'],[0, 1.24, 0, .67, .88, .61, '#392b3b'],
        [0, 1.94, 0, .69, .55, .62, '#281e29'],[.46, 1.38, .01, .29, .81, .32, '#3f2c3b'],
        [-.46, 1.38, .01, .29, .81, .32, '#3f2c3b'], [0, 2.26, 0, .37, .21, .39, '#392b3b'],
      ]);
      batch(group, glow, [[0, 1.98, .322, .46, .075, .027, '#d36d6f']]);
      return group;
    });
    const warningGeo = new T.RingGeometry(.86, 1, 24);
    geometries.push(warningGeo);
    const stormMarks = strikes.map(([x, z, radius]) => {
      const material = new T.MeshBasicMaterial({color: '#be7779', transparent: true, opacity: .25, depthWrite: false});
      materials.push(material);
      const mark = new T.Mesh(warningGeo, material);
      mark.rotation.x = -Math.PI / 2; mark.position.set(x, .026, z); mark.scale.setScalar(radius); course.add(mark);
      return mark;
    });

    const boltGeometry = new T.BufferGeometry();
    const boltPoints = new Float32Array(54);
    boltGeometry.setAttribute('position', new T.BufferAttribute(boltPoints, 3));
    const boltMaterial = new T.LineBasicMaterial({color: '#b1a2cd', transparent: true, opacity: 0, depthWrite: false, fog: false});
    const bolt = new T.LineSegments(boltGeometry, boltMaterial); bolt.frustumCulled = false; course.add(bolt);
    materials.push(boltMaterial); geometries.push(boltGeometry);
    const rainCount = reduced ? 0 : 180;
    const rainGeometry = new T.BufferGeometry(), rainPoints = new Float32Array(rainCount * 6);
    rainGeometry.setAttribute('position', new T.BufferAttribute(rainPoints, 3));
    const rainMaterial = new T.LineBasicMaterial({color: '#9791af', transparent: true, opacity: .38, depthWrite: false});
    const rain = new T.LineSegments(rainGeometry, rainMaterial);
    rain.frustumCulled = false; course.add(rain); materials.push(rainMaterial); geometries.push(rainGeometry);

    function lightning(x, z, pulse, sky) {
      let tipX = x, tipZ = z;
      for (let i = 0; i < 9; i++) {
        const y = i * (sky ? 2.5 : 1.6);
        const nextX = x + Math.sin(i * 6.9 + z) * (i % 3 + .45);
        const nextZ = z + Math.cos(i * 5.1 + x) * .7;
        boltPoints.set([tipX,y,tipZ,nextX,y + (sky ? 2.5 : 1.6),nextZ], i * 6);
        tipX = nextX; tipZ = nextZ;
      }
      boltGeometry.attributes.position.needsUpdate = true;
      boltMaterial.opacity = reduced ? 0 : .72 * pulse;
    }
    let lastStorm = null;
    function update(seconds, position) {
      guardians.forEach(([z, span, period, offset], i) => {
        const phase = (((seconds + offset) % period + period) % period) / period;
        const shadow = shadows[i];
        shadow.position.x = span * (1 - 4 * Math.abs(.5 - phase));
        shadow.position.y = reduced ? 0 : .08 + Math.sin(seconds * 3 + i) * .055;
        // The watcher turns toward nearby footsteps.
        shadow.rotation.y = Math.atan2(position.x - shadow.position.x, position.z - z);
      });
      let flash = null;
      strikes.forEach(([x, z, radius, period, offset], i) => {
        const phase = ((seconds + offset) % period + period) % period;
        const warning = phase > period - 1.85, hit = phase >= period - .72 && phase < period - .10;
        const mark = stormMarks[i];
        mark.material.color.set(hit ? '#d9b5b0' : warning ? '#cf686b' : '#83596a');
        mark.material.opacity = hit ? .89 : warning ? .72 : .35;
        if (hit && Math.abs(position.z - z) < 16) {
          flash = {x, z, pulse: .85, key: i + ':' + Math.floor((seconds + offset) / period)};
        }
      });
      const skyPhase = ((seconds % 9) + 9) % 9;
      if (!flash && skyPhase < .48) {
        const sign = Math.floor(seconds / 9) % 2 ? 1 : -1;
        flash = {x: position.x + sign * 5.4, z: position.z - 24, pulse: 1 - skyPhase / .48,
          key: 'sky:' + Math.floor(seconds / 9), sky: true};
      }
      if (flash) lightning(flash.x, flash.z, flash.pulse, flash.sky);
      else boltMaterial.opacity = 0;
      for (let i = 0; i < rainCount; i++) {
        const y = ((i * 7.13 - seconds * 12) % 10 + 10) % 10;
        const x = position.x + Math.sin(i * 17.1) * 11 - y * .13;
        const z = position.z + Math.cos(i * 8.3) * 14;
        rainPoints.set([x,y,z,x - .1,y + .49,z - .035], i * 6);
      }
      rainGeometry.attributes.position.needsUpdate = true;
      const thunder = flash && flash.key !== lastStorm;
      if (flash) lastStorm = flash.key;
      return {thunder, light: reduced ? 0 : (flash?.pulse ?? 0)};
    }

    return {
      entrance, course, safe,
      zone: {limitX: bounds.x, limitZ: bounds.z, boxes: [...boxes], cameraBoxes},
      checkpoint(index) {
        for (const [i, gate] of gateParts.entries()) gate.group.visible = i >= index;
        this.zone.boxes = [...boxes, ...gateParts.filter(gate => gate.group.visible).map(gate => gate.edges)];
      },
      actionAt(position, checkpoint) {
        const available = checkpoint === 0 ? ['seal'] : checkpoint === 1 ? layout.bellOrder : checkpoint === 2 ? ['lantern'] : [];
        for (const id of available) {
          const [x, z, text] = relics[id];
          if (Math.hypot(position.x - x, position.z - z) < 1.35) return {id, text, x, z};
        }
        return null;
      },
      update,
      dispose() {
        for (const mesh of meshes) mesh.dispose();
        for (const material of materials) material.dispose();
        for (const texture of textures) texture.dispose();
        for (const geometry of geometries) geometry.dispose();
      },
    };
  }

  return {title, room, chapters, load, create};
})();
