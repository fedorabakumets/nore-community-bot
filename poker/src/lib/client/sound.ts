"use client";

let context: AudioContext | null = null;

function audio(): AudioContext | null {
  if (typeof window === "undefined") return null;
  context ??= new AudioContext();
  if (context.state === "suspended") void context.resume();
  return context;
}

function tone(ctx: AudioContext, frequency: number, start: number, duration: number, volume: number, type: OscillatorType = "sine") {
  const oscillator = ctx.createOscillator();
  const gain = ctx.createGain();
  oscillator.type = type;
  oscillator.frequency.setValueAtTime(frequency, start);
  oscillator.frequency.exponentialRampToValueAtTime(frequency * .94, start + duration);
  gain.gain.setValueAtTime(.0001, start);
  gain.gain.exponentialRampToValueAtTime(volume, start + .006);
  gain.gain.exponentialRampToValueAtTime(.0001, start + duration);
  oscillator.connect(gain).connect(ctx.destination);
  oscillator.start(start);
  oscillator.stop(start + duration + .02);
}

function noise(ctx: AudioContext, start: number, duration: number, volume: number) {
  const buffer = ctx.createBuffer(1, Math.ceil(ctx.sampleRate * duration), ctx.sampleRate);
  const data = buffer.getChannelData(0);
  for (let index = 0; index < data.length; index += 1) data[index] = (Math.random() * 2 - 1) * (1 - index / data.length);
  const source = ctx.createBufferSource();
  const filter = ctx.createBiquadFilter();
  const gain = ctx.createGain();
  source.buffer = buffer;
  filter.type = "bandpass";
  filter.frequency.value = 1450;
  filter.Q.value = .7;
  gain.gain.setValueAtTime(volume, start);
  gain.gain.exponentialRampToValueAtTime(.0001, start + duration);
  source.connect(filter).connect(gain).connect(ctx.destination);
  source.start(start);
}

export function playSound(kind: "card" | "chip" | "turn" | "win"): void {
  const ctx = audio();
  if (!ctx) return;
  const now = ctx.currentTime;

  if (kind === "card") {
    noise(ctx, now, .075, .055);
    tone(ctx, 118, now, .09, .025, "triangle");
    return;
  }
  if (kind === "chip") {
    tone(ctx, 1260, now, .055, .035, "triangle");
    tone(ctx, 860, now + .035, .07, .04, "square");
    return;
  }
  if (kind === "turn") {
    tone(ctx, 587, now, .13, .035);
    tone(ctx, 784, now + .09, .22, .045);
    return;
  }
  [392, 494, 659, 784].forEach((frequency, index) => tone(ctx, frequency, now + index * .075, .46, .045, index % 2 ? "triangle" : "sine"));
  noise(ctx, now + .08, .18, .018);
}
