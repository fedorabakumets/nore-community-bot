'use strict';
window.NoraObservatory = (() => {
  const title = 'Звёздная обсерватория';
  const room = 'observatory';
  const instructions = [
    'Разгонись и перепрыгни разлом. Зажги первый маяк.',
    'На мосту пережди луч, обойди его сбоку или перепрыгни.',
    'Поднимись по ступеням к третьему маяку.',
    'Последний прыжок — к телескопу.',
  ];

  async function load() {
    const response = await fetch('/nora-observatory.json');
    if (!response.ok) throw Error('Не удалось загрузить обсерваторию');
    return response.json();
  }

  function create(T, geometry, layout) {
    const {portal: entrance, platforms, checkpoints, beams, bounds, reward} = layout;
    const course = new T.Group(), portal = new T.Group();
    course.name = 'nora-observatory'; course.visible = false;
    portal.name = 'nora-observatory-portal'; portal.position.set(entrance.x, 0, entrance.z);
    const materials = [], textures = [], meshes = [];
    const stone = new T.MeshLambertMaterial();
    const light = new T.MeshBasicMaterial();
    materials.push(stone, light);
    const frame = [], frameLight = [], rocks = [], inlay = [], sparks = [];
    const box = (list, x, y, z, w, h, d, col) => list.push([x, y, z, w, h, d, col]);

    // Stepped stone arch, a translucent veil and the in-world wayfinding sign.
    box(frame, 0, .06, 0, 2.7, .12, .8, '#393349');
    box(frame, 0, 2.49, 0, 2.4, .34, .46, '#4a435a');
    box(frame, 0, 2.75, 0, 1.58, .22, .45, '#57516e');
    for (const side of [-1, 1]) {
      for (let i = 0; i < 6; i++) {
        const x = side * (i < 5 ? 1.06 : .9);
        box(frame, x, .29 + .37 * i, 0, .35, .38, .5, i % 2 ? '#514864' : '#383449');
        box(frameLight, x, .29 + .37 * i, .259, .075, .18, .04, '#70edda');
      }
      box(frameLight, side * .59, 2.48, .247, .68, .045, .04, '#70edda');
    }
    for (let i = 0; i < 4; i++) {
      box(frameLight, 0, .024, .61 + .34 * i, .36 + i * .13, .027, .065, '#7bcbbd');
    }

    function batch(parent, material, pieces) {
      const mesh = new T.InstancedMesh(geometry, material, pieces.length);
      const model = new T.Object3D(), color = new T.Color();
      pieces.forEach(([x, y, z, w, h, d, col], i) => {
        model.position.set(x, y, z); model.scale.set(w, h, d); model.updateMatrix();
        mesh.setMatrixAt(i, model.matrix); mesh.setColorAt(i, color.set(col));
      });
      mesh.computeBoundingSphere(); parent.add(mesh); meshes.push(mesh);
      return mesh;
    }

    function sign(parent, at, lines, scale) {
      const canvas = document.createElement('canvas');
      canvas.width = 512; canvas.height = 128;
      const ctx = canvas.getContext('2d');
      ctx.fillStyle = '#171b2b'; ctx.fillRect(0, 0, 512, 128);
      ctx.fillStyle = '#68cbbb'; ctx.fillRect(0, 0, 512, 5); ctx.fillRect(0, 123, 512, 5);
      ctx.textAlign = 'center'; ctx.fillStyle = '#f3e8cc'; ctx.font = 'bold 34px monospace';
      const subtitle = lines.at(-1);
      lines.slice(0, -1).forEach((line, i) => ctx.fillText(line, 256, (lines.length === 3 ? 38 : 51) + i * 34, 478));
      ctx.fillStyle = '#a1e5d8'; ctx.font = '24px monospace';
      ctx.fillText(subtitle, 256, lines.length === 3 ? 107 : 96, 480);
      const texture = new T.CanvasTexture(canvas); texture.colorSpace = T.SRGBColorSpace;
      const material = new T.SpriteMaterial({map: texture, depthWrite: false});
      const sprite = new T.Sprite(material);
      sprite.position.set(...at); sprite.scale.set(scale, scale / (lines.length === 3 ? 3 : 4), 1); parent.add(sprite);
      materials.push(material); textures.push(texture);
    }

    batch(portal, stone, frame);
    batch(portal, light, frameLight);
    const veilMaterial = new T.MeshBasicMaterial({
      color: '#1a9f9c', transparent: true, opacity: .6, depthWrite: false,
    });
    const veil = new T.Mesh(geometry, veilMaterial);
    veil.position.set(0, 1.23, 0); veil.scale.set(1.86, 2.25, .08); portal.add(veil);
    materials.push(veilMaterial);
    sign(portal, [0, 2.35, .68], ['ЗВЁЗДНАЯ', 'ОБСЕРВАТОРИЯ', `Первый финиш · ${reward} печенек`], 2.85);

    const boxes = platforms.map(([x, z, y, w, d], i) => {
      const beacon = checkpoints.includes(i);
      const edge = beacon ? '#8bcdbb' : '#6c84ac';
      box(rocks, x, y - .2, z, w, .4, d, i === 5 ? '#343c56' : '#444865');
      box(rocks, x, y - .56, z, w * .88, .34, d * .81, '#363650');
      box(rocks, x + .05, y - .84, z, w * .63, .26, d * .6, '#25273f');
      box(rocks, x - .12, y - 1.08, z, w * .38, .28, d * .33, '#242237');
      const columns = Math.ceil(w / .52), rows = Math.ceil(d / .52);
      for (let a = 0; a < columns; a++) for (let b = 0; b < rows; b++) {
        const tile = ['#555977', '#505672', '#494e6b', '#58607a'][(a * 11 + b * 13 + i) % 4];
        box(rocks, x - w / 2 + w * (a + .5) / columns, y - .023,
          z - d / 2 + d * (b + .5) / rows, w / columns - .018, .049, d / rows - .018, tile);
      }
      for (const side of [-1, 1]) {
        box(inlay, x + side * (w / 2 - .055), y + .006, z, .065, .02, d - .12, edge);
        box(inlay, x, y + .006, z + side * (d / 2 - .055), w - .12, .02, .065, edge);
      }
      return [x - w / 2, x + w / 2, z - d / 2, z + d / 2, y];
    });
    // Mark the route even with fog or in first-person view.
    for (const [i, x, z, rotation] of [[0, 0, 9, 0], [4, 0, 1.4, 0], [6, .6, -7.75, -Math.PI / 2]]) {
      const arrow = new T.Group(); arrow.position.set(x, platforms[i][2] + .026, z); arrow.rotation.y = rotation;
      const stem = new T.Mesh(geometry, light);
      stem.position.z = .1; stem.scale.set(.08, .024, .51); arrow.add(stem);
      for (const side of [-1, 1]) {
        const wing = new T.Mesh(geometry, light);
        wing.position.set(side * .12, 0, -.16);
        wing.rotation.y = side * Math.PI / 4; wing.scale.set(.075, .024, .35); arrow.add(wing);
      }
      course.add(arrow);
    }
    const beaconMaterial = new T.MeshBasicMaterial({color: '#75f7d7'});
    const unlitMaterial = new T.MeshBasicMaterial({color: '#594e7e'});
    materials.push(beaconMaterial, unlitMaterial);
    const crystals = checkpoints.slice(1, -1).map((index) => {
      const [x, z, y, w] = platforms[index];
      const crystal = new T.Mesh(geometry, unlitMaterial);
      crystal.position.set(x - w / 2 + .29, y + .83, z);
      crystal.scale.set(.29, .47, .29); course.add(crystal);
      box(rocks, crystal.position.x, y + .27, z, .28, .54, .28, '#5f5775');
      return crystal;
    });
    sign(course, [0, 3.85, -.6], ['ИМПУЛЬСНЫЙ МОСТ', 'Светлеет → включается'], 2.82);
    sign(course, [2.9, 3.9, -7.6], ['ЗВЁЗДНАЯ ЛЕСТНИЦА', 'Поднимайся по ступеням →'], 2.82);
    sign(course, [3.25, 6.1, -21.0], ['ТЕЛЕСКОП', 'Финиш за третьим маяком'], 3.2);

    // Separate rails for the beam emitters, and a voxel telescope pointed at the sky.
    const beamMeshes = beams.map(([x, z, y, w]) => {
      for (const side of [-1, 1]) {
        box(rocks, x + side * w / 2, y + .28, z, .18, .56, .21, '#544361');
        box(inlay, x + side * w / 2, y + .39, z, .19, .16, .22, '#be8ca5');
      }
      const material = new T.MeshBasicMaterial({transparent: true, depthWrite: false});
      materials.push(material);
      const mesh = new T.Mesh(geometry, material);
      mesh.position.set(x, y + .23, z); mesh.scale.set(w, .17, .27); course.add(mesh);
      return mesh;
    });
    const telescope = new T.Group();
    telescope.position.set(3.25, 4.64, -20.94); telescope.rotation.x = -.47; telescope.rotation.y = -.36;
    batch(telescope, stone, [
      [0, 0, 0, .62, .62, 1.76, '#625477'],
      [0, 0, -.76, .89, .89, .38, '#8b7899'],
      [0, 0, .92, .34, .34, .38, '#a28379'],
    ]);
    batch(telescope, light, [[0, 0, -.96, .56, .56, .06, '#91f7db']]);
    course.add(telescope);
    box(rocks, 3.25, 4.04, -20.94, .38, .94, .38, '#7a677f');

    for (let i = 0; i < 64; i++) {
      const side = i % 2 ? 1 : -1;
      const x = side * (6 + (i * 19 % 28) / 2.5), z = 12 - (i * 23 % 59) * .74;
      const h = .8 + (i * 13 % 19) / 6.5;
      box(rocks, x, -4.5 + h / 2, z, .7 + i % 4, h, 1.4, i % 3 ? '#23263a' : '#3d3351');
      box(sparks, Math.sin(i * 17.8) * 26, 4 + (i * 29 % 97) * .22,
        18 - (i * 31 % 101) * .64, .045 + i % 4 * .022, .05, .06,
        i % 7 ? '#a99ac6' : '#f4dbaf');
    }
    batch(course, stone, rocks);
    batch(course, light, inlay);
    const starsMaterial = new T.MeshBasicMaterial({fog: false});
    materials.push(starsMaterial);
    batch(course, starsMaterial, sparks);

    function beamPhase(beam, seconds) {
      return ((seconds + beam[4]) % 4 + 4) % 4;
    }

    return {
      portal, course, entrance, reward, safe: checkpoints.map(i => platforms[i]),
      zone: {limitX: bounds.x, limitZ: bounds.z, boxes, cameraBoxes: []},
      belowCourse: bounds.minY + .2,
      hitBeam({x, y, z}, seconds) {
        return beams.some(beam => {
          const [bx, bz, by, w] = beam, phase = beamPhase(beam, seconds);
          return phase >= 1 && phase < 2.65 && Math.abs(x - bx) < w / 2 + .04 &&
            Math.abs(z - bz) < .17 && y < by + .34;
        });
      },
      updatePortal(time) { veilMaterial.opacity = .52 + Math.sin(time / 680) * .12; },
      update(seconds, checkpoint) {
        beamMeshes.forEach((mesh, i) => {
          const phase = beamPhase(beams[i], seconds), active = phase >= 1 && phase < 2.65;
          mesh.scale.y = active ? .17 : .026;
          mesh.material.color.set(active ? '#f281b3' : '#efba82');
          mesh.material.opacity = active ? .84 : phase >= .5 && phase < 1 ? .65 : .12;
        });
        crystals.forEach((crystal, i) => {
          crystal.material = i < checkpoint ? beaconMaterial : unlitMaterial;
          crystal.rotation.set(Math.PI / 4, seconds * .75, Math.PI / 5);
        });
      },
      dispose() {
        for (const mesh of meshes) mesh.dispose();
        for (const material of materials) material.dispose();
        for (const texture of textures) texture.dispose();
      },
    };
  }

  return {title, room, instructions, load, create};
})();
