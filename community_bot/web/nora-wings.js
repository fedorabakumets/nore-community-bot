'use strict';
window.NoraWings = (() => {
  // The raven's membrane masks come from wings.png by Legeukko (MIT).
  // See /game/wings-license.txt for the source and license.
  const catalog = {
    raven: {
      name: 'Ворон', palette: ['#1b1b23','#353743','#535663','#737786'],
      root: ['11111111110','1111222211.','.13322221..','..2332211..','...23311...','....2311...'],
      tip: ['11111111110','1111222211.','.13332211..','...233211..','....2311...','......11...'],
      lift: .48, bend: .38, speed: 2.2,
    },
    flame: {
      name: 'Пламя', palette: ['#672129','#a72d29','#ed5d30','#ffc060'],
      root: ['.1111111110','11333333211','12322222111','.232221111.','..32111.11.','...211...1.','....1......'],
      tip: ['01111111110','...1122331.','111233331..','123332211..','.232211111.','..211...111','...1......1'],
      lift: .63, bend: .5, speed: 3.3,
    },
    frost: {
      name: 'Иней', palette: ['#345b81','#5596b6','#a9def0','#effbff'],
      root: ['..111111110','11333333221','1223222211.','.12322111..','.122211.1..','..1211..1..','..11.......','..1........'],
      tip: ['00011111110','.....11331.','..111333211','1133332211.','12222211...','.12211.11..','..111...1..','...1.......'],
      lift: .36, bend: .67, speed: 1.75,
    },
  };
  const resources = new Map();

  // Extrude each visible texel, omitting faces between adjacent texels.
  function extrude(T, rows) {
    const points = [], uv = [];
    function face(a,b,c,d,index) {
      for (const point of [a,b,c,a,c,d]) {
        points.push(...point);
        uv.push((Number(index)+.5)/4,.5);
      }
    }
    rows.forEach((row,y) => Array.from(row).forEach((index,x) => {
      if (index==='.') return;
      const top=.5-y, bottom=top-1, right=x+1, depth=.44;
      const a=[x,top,depth], b=[x,bottom,depth], c=[right,bottom,depth], d=[right,top,depth];
      const e=[x,top,-depth], f=[x,bottom,-depth], g=[right,bottom,-depth], h=[right,top,-depth];
      face(a,b,c,d,index);face(h,g,f,e,index);
      if (y===0 || rows[y-1][x]==='.') face(e,a,d,h,'0');
      if (y===rows.length-1 || rows[y+1][x]==='.') face(b,f,g,c,'0');
      if (x===0 || row[x-1]==='.') face(e,f,b,a,'0');
      if (x===row.length-1 || row[x+1]==='.') face(d,c,g,h,'0');
    }));
    const geo=new T.BufferGeometry();
    geo.setAttribute('position',new T.Float32BufferAttribute(points,3));
    geo.setAttribute('uv',new T.Float32BufferAttribute(uv,2));
    geo.computeVertexNormals();
    return geo;
  }

  function attach(T, torso, id, unit, bodyMaterial) {
    const style=catalog[id];
    if (!Object.hasOwn(catalog,id)) return null;
    let asset=resources.get(id);
    if (!asset) {
      const rgba=style.palette.flatMap(hex=>[1,3,5].map(i=>parseInt(hex.slice(i,i+2),16)).concat(255));
      const map=new T.DataTexture(new Uint8Array(rgba),4,1);
      map.colorSpace=T.SRGBColorSpace;
      map.magFilter=map.minFilter=T.NearestFilter;
      map.needsUpdate=true;
      asset={map, root:extrude(T,style.root), tip:extrude(T,style.tip), users:0};
      resources.set(id,asset);
    }
    asset.users++;
    const material=bodyMaterial.clone();
    material.map=asset.map;
    material.onBeforeCompile=bodyMaterial.onBeforeCompile;
    material.customProgramCacheKey=bodyMaterial.customProgramCacheKey;
    const mount=new T.Group();
    mount.name='wings';torso.add(mount);
    mount.position.set(0,12*unit,-5*unit);
    mount.scale.setScalar(1.18*unit);
    const sides=[-1,1].map(sign=>{
      const hinge=new T.Group(), spar=new T.Group(), tipHinge=new T.Group();
      hinge.position.x=sign*3;
      spar.scale.x=sign;
      spar.rotation.z=sign*style.lift;
      tipHinge.position.x=9.5;
      tipHinge.rotation.z=-style.bend;
      mount.add(hinge);hinge.add(spar);
      spar.add(new T.Mesh(asset.root,material),tipHinge);
      tipHinge.add(new T.Mesh(asset.tip,material));
      return {sign,hinge,tipHinge};
    });
    let phase=0, spread=0;
    return {
      tick(dt,airborne=false) {
        spread+=((airborne?1:0)-spread)*(1-Math.exp(-9*dt));
        phase=(phase+dt*style.speed*(1+1.9*spread))%(2*Math.PI);
        for (const {sign,hinge,tipHinge} of sides) {
          // Sweep stays behind the shoulder line throughout the cycle.
          hinge.rotation.y=sign*(.52-.20*spread+Math.sin(phase)*(.13+.16*spread));
          tipHinge.rotation.y=.12+Math.sin(phase-.75)*(.09+.13*spread);
        }
      },
      setOpacity(value) { material.opacity=value;mount.visible=value>.001; },
      dispose() {
        torso.remove(mount);material.dispose();
        if (--asset.users===0) {
          asset.root.dispose();asset.tip.dispose();asset.map.dispose();resources.delete(id);
        }
      },
    };
  }

  function icon(id='raven') {
    const {root,tip,palette}=catalog[id];
    const section=(rows,offset,raise)=>rows.map((row,y)=>Array.from(row,(color,x)=>
      color==='.'?'':`<rect x="${offset+x}" y="${y+raise-Math.floor(x/3)}" width="1" height="1" fill="${palette[color]}"/>`
    ).join('')).join('');
    const art=section(root,0,6)+section(tip,10,4);
    return `<svg viewBox="0 0 46 14" shape-rendering="crispEdges" aria-hidden="true"><g transform="translate(24 2)">${art}</g><g transform="translate(22 2) scale(-1 1)">${art}</g></svg>`;
  }
  return {catalog,attach,icon};
})();
