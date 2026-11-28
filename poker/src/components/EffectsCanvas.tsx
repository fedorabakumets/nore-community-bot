"use client";

import { useEffect, useRef } from "react";

type EffectKind = "deal" | "chips" | "street" | "win";

interface EffectState {
  handId: string;
  boardCount: number;
  pot: number;
  winnerKey: string;
  winnerSeat: number;
}

interface Particle {
  x: number;
  y: number;
  vx: number;
  vy: number;
  life: number;
  maxLife: number;
  size: number;
  rotation: number;
  spin: number;
  color: string;
  shape: "circle" | "chip" | "card";
  targetX?: number;
  targetY?: number;
}

const PALETTE = ["#e5bb77", "#a7c8ff", "#c24a55", "#f3e8d0"];

function effectFrom(previous: EffectState, next: EffectState): EffectKind | null {
  if (next.winnerKey && next.winnerKey !== previous.winnerKey) return "win";
  if (next.handId && next.handId !== previous.handId) return "deal";
  if (next.boardCount > previous.boardCount) return "street";
  if (next.pot > previous.pot) return "chips";
  return null;
}

type Point = { x: number; y: number };

function makeParticles(kind: EffectKind, width: number, origin: Point, target?: Point): Particle[] {
  const config = {
    deal: { count: 24, speed: 3.2, lift: 1.8, life: 38 },
    chips: { count: 22, speed: 2.2, lift: 2.2, life: 42 },
    street: { count: 42, speed: 4.2, lift: 3.2, life: 58 },
    win: { count: 92, speed: 7.2, lift: 7.6, life: 100 },
  }[kind];

  return Array.from({ length: config.count }, (_, index) => {
    const angle = Math.random() * Math.PI * 2;
    const speed = Math.random() * config.speed;
    const maxLife = config.life * (.72 + Math.random() * .55);
    const streamsToWinner = kind === "win" && index % 3 !== 0;
    return {
      x: origin.x + width * (Math.random() - .5) * .08,
      y: origin.y,
      vx: Math.cos(angle) * speed,
      vy: Math.sin(angle) * speed - Math.random() * config.lift,
      life: maxLife,
      maxLife,
      size: 1.5 + Math.random() * (kind === "win" ? 4.5 : 3),
      rotation: Math.random() * Math.PI,
      spin: (Math.random() - .5) * .18,
      color: PALETTE[index % PALETTE.length],
      shape: kind === "deal" && index % 6 === 0 ? "card" : streamsToWinner || (kind === "chips" && index % 3 === 0) ? "chip" : "circle",
      targetX: streamsToWinner && target ? target.x + (Math.random() - .5) * 28 : undefined,
      targetY: streamsToWinner && target ? target.y + (Math.random() - .5) * 20 : undefined,
    };
  });
}

export function EffectsCanvas({ handId, boardCount, pot, winnerKey, winnerSeat }: EffectState) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const previousRef = useRef<EffectState | null>(null);

  useEffect(() => {
    const next = { handId, boardCount, pot, winnerKey, winnerSeat };
    const previous = previousRef.current;
    previousRef.current = next;
    if (!previous || document.hidden || matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const kind = effectFrom(previous, next);
    if (!kind) return;

    const canvas = canvasRef.current;
    const context = canvas?.getContext("2d");
    if (!canvas || !context) return;

    const density = Math.min(window.devicePixelRatio, 2);
    const bounds = canvas.getBoundingClientRect();
    const { width, height } = bounds;
    const center = (selector: string): Point | undefined => {
      const rect = canvas.parentElement?.querySelector(selector)?.getBoundingClientRect();
      if (rect) return { x: rect.left - bounds.left + rect.width / 2, y: rect.top - bounds.top + rect.height / 2 };
    };
    const origin = center("[data-poker-pot]") ?? { x: width / 2, y: height / 2 };
    const target = center(`[data-poker-seat="${winnerSeat}"]`);
    canvas.width = Math.round(width * density);
    canvas.height = Math.round(height * density);
    context.setTransform(density, 0, 0, density, 0, 0);

    const particles = makeParticles(kind, width, origin, target);
    let raf = 0;
    let stopped = false;
    let lastTime = performance.now();
    let flash = kind === "win" ? .24 : .12;
    const stop = () => {
      stopped = true;
      cancelAnimationFrame(raf);
      context.clearRect(0, 0, width, height);
    };
    const onVisibility = () => { if (document.hidden) stop(); };
    const render = (time: number) => {
      if (stopped) return;
      const delta = Math.min(2, Math.max(.4, (time - lastTime) / 16.667));
      lastTime = time;
      context.clearRect(0, 0, width, height);
      if (flash > .005) {
        const glow = context.createRadialGradient(origin.x, origin.y, 0, origin.x, origin.y, width * .32);
        glow.addColorStop(0, kind === "win" ? `rgba(229,187,119,${flash})` : `rgba(167,200,255,${flash})`);
        glow.addColorStop(1, "rgba(0,0,0,0)");
        context.fillStyle = glow;
        context.fillRect(0, 0, width, height);
        flash *= Math.pow(.9, delta);
      }
      let alive = false;
      for (const particle of particles) {
        if (particle.life <= 0) continue;
        alive = true;
        if (particle.targetX !== undefined && particle.targetY !== undefined && particle.life < particle.maxLife * .86) {
          const pull = .012 + (1 - particle.life / particle.maxLife) * .025;
          particle.vx += (particle.targetX - particle.x) * pull * delta;
          particle.vy += (particle.targetY - particle.y) * pull * delta;
          particle.vx *= Math.pow(.88, delta);
          particle.vy *= Math.pow(.88, delta);
        } else {
          particle.vy += (kind === "win" ? .11 : .075) * delta;
          particle.vx *= Math.pow(.987, delta);
        }
        particle.x += particle.vx * delta;
        particle.y += particle.vy * delta;
        particle.rotation += particle.spin * delta;
        particle.life -= delta;
        const alpha = Math.min(1, particle.life / 18, (particle.maxLife - particle.life) / 8);
        context.save();
        context.globalAlpha = alpha;
        context.translate(particle.x, particle.y);
        context.rotate(particle.rotation);
        context.fillStyle = particle.color;
        if (particle.shape === "card") context.fillRect(-particle.size * .7, -particle.size, particle.size * 1.4, particle.size * 2);
        else if (particle.shape === "chip") {
          context.beginPath();
          context.ellipse(0, 0, particle.size * 1.4, particle.size * .55, 0, 0, Math.PI * 2);
          context.fill();
        } else {
          context.beginPath();
          context.arc(0, 0, particle.size, 0, Math.PI * 2);
          context.fill();
        }
        context.restore();
      }
      if (alive) raf = requestAnimationFrame(render);
      else stop();
    };

    addEventListener("resize", stop);
    document.addEventListener("visibilitychange", onVisibility);
    raf = requestAnimationFrame(render);
    return () => {
      stop();
      removeEventListener("resize", stop);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [handId, boardCount, pot, winnerKey, winnerSeat]);

  return <canvas ref={canvasRef} aria-hidden="true" />;
}
