const WIDTH = 360, HEIGHT = 315;
const wood = ['#b98450', '#a97847', '#bd8e58', '#bc8952', '#a8794f'];
const palettes = [
  ['#fbb9a1', '#d65f4b', '#81292a', '#46191d'],
  ['#bbf7df', '#6ebda9', '#296d68', '#143b3b']
];
export const previewPosition = {
  pawns: [[2, 6], [6, 2]], walls: [[1, 4, 'h'], [3, 5, 'v'], [5, 1, 'h'], [6, 6, 'v']]
};

function project(x, y, height = 0) {
  const scale = .83 + .025 * y;
  return [180 + (x - 4.5) * 33.8 * scale, 34 + (y * 24.6 + y * y * .27) - height * scale];
}

export function buttonPosition(x, y) {
  const [px, py] = project(x, y);
  return 'left:' + (px / WIDTH * 100) + '%;top:' + (py / HEIGHT * 100) + '%';
}

function polygon(ctx, points, color, stroke) {
  ctx.beginPath();
  for (const [i, [x, y]] of points.entries()) {
    if (i) ctx.lineTo(x, y);
    else ctx.moveTo(x, y);
  }
  ctx.closePath();
  ctx.fillStyle = color;
  ctx.fill();
  if (stroke) {
    ctx.strokeStyle = stroke;
    ctx.stroke();
  }
}

function face(ctx, bounds, height, color, stroke) {
  const [x, y, right, bottom] = bounds;
  polygon(ctx, [[x, y], [right, y], [right, bottom], [x, bottom]].map(([a, b]) => project(a, b, height)),
    color, stroke);
}

function box(ctx, bounds, top, bottom, colors) {
  const [x, y, right, far] = bounds;
  polygon(ctx, [project(x, far, bottom), project(right, far, bottom), project(right, far, top),
    project(x, far, top)], colors[1]);
  const side = (x + right) / 2 < 4.5 ? x : right;
  polygon(ctx, [project(side, y, bottom), project(side, far, bottom), project(side, far, top),
    project(side, y, top)], colors[2]);
  face(ctx, bounds, top, colors[0], colors[3]);
}

function shade(ctx, y1, y2, colors) {
  const gradient = ctx.createLinearGradient(0, y1, 0, y2);
  colors.forEach((color, i) => gradient.addColorStop(i / (colors.length - 1), color));
  return gradient;
}

function grain(ctx, bounds, offset, height) {
  const [x, y, right, end] = bounds;
  ctx.lineWidth = .36;
  for (let i = 1; i < 10; i++) {
    const at = y + (end - y) * i / 10;
    const bump = Math.sin(i * 3.7 + offset) * .034;
    const from = x + (i % 3) * .05, to = right - (i % 4) * .07;
    ctx.beginPath();
    ctx.moveTo(...project(from, at, height));
    ctx.bezierCurveTo(...project(from + (to - from) * .3, at + bump, height),
      ...project(from + (to - from) * .77, at - bump, height), ...project(to, at + bump, height));
    ctx.strokeStyle = i % 3 ? '#502b2081' : '#ffe6ad95';
    ctx.stroke();
  }
  ctx.lineWidth = 1;
}

function ellipse(ctx, x, y, rx, ry, fill) {
  ctx.beginPath();
  ctx.ellipse(x, y, rx, ry, 0, 0, 2 * Math.PI);
  ctx.fillStyle = fill;
  ctx.fill();
}

function glow(ctx, x, y, rx, ry, inner) {
  ctx.save();
  ctx.translate(x, y);
  ctx.scale(1, ry / rx);
  const fill = ctx.createRadialGradient(0, 0, 0, 0, 0, rx);
  fill.addColorStop(0, inner);
  fill.addColorStop(1, 'transparent');
  ellipse(ctx, 0, 0, rx, rx, fill);
  ctx.restore();
}

function surface(ctx) {
  glow(ctx, 180, 268, 177, 46, '#10060cef');
  box(ctx, [-.26, -.26, 9.26, 9.26], -3, -17,
    [shade(ctx, 22, 295, ['#623929', '#a96a40', '#75412a']), '#432117', '#633720', '#c98f5a']);
  box(ctx, [-.21, -.2, 9.21, 9.2], 0, -3,
    [shade(ctx, 27, 286, ['#a46d44', '#67402c', '#9b623b']), '#8e5332', '#8f5739', '#dca56e']);
  face(ctx, [0, 0, 9, 9], 0, '#472b22', '#361f19');
  for (let row = 0; row < 9; row++) {
    for (let col = 0; col < 9; col++) {
      const slot = [col + .046, row + .045, col + .954, row + .942];
      const y = project(col, row)[1], i = row * 9 + col;
      box(ctx, slot, 2, 0, [shade(ctx, y, y + 27, ['#d4a674', wood[(row * 3 + col * 7) % wood.length], '#986444']),
        '#75442a', '#855235', '#bd8c59']);
      grain(ctx, [col + .13, row + .15, col + .87, row + .86], i * 1.9, 2);
      if (row === 0 || row === 8) {
        const [x, dy] = project(col + .5, row + .52, 2);
        ellipse(ctx, x, dy, 2.1, 1.2, row === 0 ? '#7d2829' : '#205953');
      }
    }
  }
  // Brass pins in the frame.
  for (const x of [-.12, 9.12]) for (const y of [-.115, 9.115]) {
    const [px, py] = project(x, y, .5);
    ellipse(ctx, px, py, 2.25, 1.65, '#442615');
    ellipse(ctx, px, py - .42, 1.5, .98, '#dfa66d');
  }
}

function pawn(ctx, row, col, seat, lift = 0) {
  const [x, y] = project(col + .5, row + .58, 2);
  const [light, body, dark, rim] = palettes[seat];
  const scale = .78 + row * .033;
  glow(ctx, x + 2, y + 3, 15 * scale, 8 * scale, '#200d0bd8');
  ctx.save();
  ctx.translate(x, y - lift);
  ctx.scale(scale, scale);
  ellipse(ctx, 0, 1, 11, 5, rim);
  ellipse(ctx, 0, -2, 11, 5, shade(ctx, -8, 3, [light, body, dark]));
  ellipse(ctx, 0, -3, 8.6, 3.1, dark);
  const bodyShade = ctx.createLinearGradient(-9, 0, 9, 0);
  [dark, light, body, dark, rim].forEach((color, i) => bodyShade.addColorStop(i / 4, color));
  ctx.beginPath();
  ctx.moveTo(-8.5, -3);
  ctx.bezierCurveTo(-8, -10, -3.2, -12, -4.3, -18);
  ctx.lineTo(4.3, -18);
  ctx.bezierCurveTo(3.2, -12, 8, -10, 8.5, -3);
  ctx.ellipse(0, -3, 8.5, 3.3, 0, 0, Math.PI);
  ctx.closePath();
  ctx.fillStyle = bodyShade;
  ctx.fill();
  ellipse(ctx, 0, -17, 5.8, 2.3, bodyShade);
  const head = ctx.createRadialGradient(-2.5, -26, .3, 0, -23, 7.5);
  head.addColorStop(0, light);
  head.addColorStop(.52, body);
  head.addColorStop(1, dark);
  ellipse(ctx, 0, -23.4, 7, 7.1, head);
  ctx.restore();
}

function wall(ctx, [row, col, axis], height = 12, preview = false) {
  const h = axis === 'h';
  const x = col + (h ? .06 : .93), y = row + (h ? .93 : .06);
  const bound = [x, y, x + (h ? 1.88 : .14), y + (h ? .14 : 1.88)];
  const y1 = project(x, y, height)[1], y2 = project(bound[2], bound[3], 0)[1];
  ctx.save();
  if (preview) ctx.globalAlpha = .52;
  face(ctx, [x, y, bound[2] + .13, bound[3] + .14], 1, '#29160ec4');
  box(ctx, bound, height, 1, ['#efc078', shade(ctx, y1, y2, ['#c59452', '#936035', '#684126']),
    shade(ctx, y1, y2, ['#bd8449', '#9a6136', '#63402b']), '#e1a964']);
  if (h) {
    const [left, lower, right, bottom] = bound;
    grain(ctx, [left + .01, lower + .01, right - .02, bottom - .01], row + col, height);
  }
  const [px, py] = project(x + (h ? .13 : .07), y + (h ? .07 : .14), height);
  ellipse(ctx, px, py, 1.2, .88, '#795030');
  ctx.restore();
}

function drawing(canvas) {
  const ctx = canvas.getContext('2d');
  let base;
  return (state, options = {}) => {
    if (!base || base.width !== canvas.width) {
      base = document.createElement('canvas');
      base.width = canvas.width;
      base.height = canvas.height;
      const back = base.getContext('2d');
      back.scale(base.width / WIDTH, base.height / HEIGHT);
      surface(back);
    }
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(base, 0, 0);
    ctx.setTransform(canvas.width / WIDTH, 0, 0, canvas.height / HEIGHT, 0, 0);
    const depth = state.walls.map((w, i) => ({y: w[0] + (w[2] === 'h' ? 1 : 1.75),
      draw: () => wall(ctx, w, options.newWall === i ? options.wallHeight : 12)}));
    if (options.preview) depth.push({y: options.preview[0] + 1, draw: () => wall(ctx, options.preview, 12, true)});
    for (const [seat, [row, col]] of state.pawns.entries()) {
      depth.push({y: row + .58, draw: () => pawn(ctx, row, col, seat, options.lift?.[seat])});
    }
    depth.sort((a, b) => a.y - b.y).forEach(item => item.draw());
  };
}

export function attachBoard(canvas) {
  const draw = drawing(canvas);
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  let frame, position, preview, shown, motion;
  function paint(time) {
    if (!position) return;
    if (!motion) {
      shown = position;
      draw(position, {preview});
      return;
    }
    const t = Math.min(1, (time - motion.at) / 350), ease = 1 - (1 - t) ** 3;
    shown = {...position, pawns: position.pawns.map((pair, i) =>
      pair.map((v, j) => motion.prior.pawns[i][j] + (v - motion.prior.pawns[i][j]) * ease))};
    const lift = position.pawns.map((p, i) =>
      p.some((v, j) => v !== motion.prior.pawns[i][j]) ? Math.sin(Math.PI * t) * 8 : 0);
    draw(shown, {preview, lift, newWall: motion.newWall, wallHeight: 12 + (1 - ease) * 18});
    if (t < 1) frame = requestAnimationFrame(paint);
    else motion = null;
  }
  function resize() {
    const width = Math.max(1, Math.min(1100, Math.round(canvas.clientWidth * Math.min(2, devicePixelRatio || 1))));
    if (width === canvas.width && canvas.height === Math.round(width * HEIGHT / WIDTH)) return;
    canvas.width = width;
    canvas.height = Math.round(width * HEIGHT / WIDTH);
    cancelAnimationFrame(frame);
    paint(performance.now());
  }
  const observer = new ResizeObserver(resize);
  observer.observe(canvas);
  resize();
  return {
    update(next, ghost = null, animate = true) {
      const changed = next !== position;
      if (changed) {
        motion = position && animate && !reduced.matches && JSON.stringify(position) !== JSON.stringify(next)
          ? {at: performance.now(), prior: shown || position,
            newWall: next.walls.length > position.walls.length ? next.walls.length - 1 : -1} : null;
      }
      position = next;
      preview = ghost;
      cancelAnimationFrame(frame);
      paint(performance.now());
    },
    close() {observer.disconnect();cancelAnimationFrame(frame);}
  };
}

// The catalogue cover is rendered from the same geometry as the playable board.
export function drawCover(canvas) {
  drawing(canvas)(previewPosition);
}
