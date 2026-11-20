const StorageKey = 'nora-barricade-sound';
const AudioEngine = window.AudioContext || window.webkitAudioContext;
const mediaSupported = () => typeof window.Audio === 'function';
const soundUrl = event => '/barricade-sfx/' + event + '.wav';
let enabled = true;
let context, master, wood, fallback, fallbackReady, engineFailed;
try {enabled = localStorage.getItem(StorageKey) !== 'off';} catch {}

const melodies = {
  start: [246.94, 329.63, 392],
  win: [392, 493.88, 587.33, 783.99],
  loss: [293.66, 220, 174.61],
  option: [523.25],
};

function setup() {
  context = new AudioEngine();
  master = context.createGain();
  master.gain.value = enabled ? .68 : 0;
  master.connect(context.destination);
  const length = Math.ceil(context.sampleRate * .085);
  wood = context.createBuffer(1, length, context.sampleRate);
  const samples = wood.getChannelData(0);
  for (let i = 0; i < length; i++) samples[i] = (2 * Math.random() - 1) * (1 - i / length) ** 3;
}

function tryFallback(event) {
  if (!mediaSupported()) return;
  if (!fallback) {
    fallback = new window.Audio();
    fallback.volume = .64;
  }
  const url = soundUrl(event);
  if (!fallback.src.endsWith(url)) fallback.src = url;
  else fallback.currentTime = 0;
  fallback.play()?.then(() => {fallbackReady = true;}, () => {});
}

export function unlock() {
  if (!enabled) return;
  if (AudioEngine && !engineFailed) {
    try {
      if (!context) setup();
      if (context.state !== 'running') context.resume().catch(() => {});
      return;
    } catch {
      engineFailed = true;
      context = null;
      master = null;
    }
  }
  if (!fallbackReady) tryFallback('option');
}

export function soundEnabled() {
  return enabled && supported();
}

export function supported() {
  return Boolean(AudioEngine) || mediaSupported();
}

export function toggleSound() {
  enabled = !enabled;
  try {localStorage.setItem(StorageKey, enabled ? 'on' : 'off');} catch {}
  if (enabled) unlock();
  else fallback?.pause();
  if (master) master.gain.setValueAtTime(enabled ? .68 : 0, context.currentTime);
  if (enabled) cue('option');
}

function tone(time, frequency, duration, volume, end = frequency) {
  const pitch = context.createOscillator();
  const level = context.createGain();
  pitch.type = 'sine';
  pitch.frequency.setValueAtTime(frequency, time);
  pitch.frequency.exponentialRampToValueAtTime(end, time + duration);
  level.gain.setValueAtTime(.001, time);
  level.gain.exponentialRampToValueAtTime(volume, time + .009);
  level.gain.exponentialRampToValueAtTime(.001, time + duration);
  pitch.connect(level).connect(master);
  pitch.start(time);
  pitch.stop(time + duration);
  pitch.onended = () => {pitch.disconnect();level.disconnect();};
}

function knock(time, frequency, volume) {
  const source = context.createBufferSource();
  const body = context.createBiquadFilter();
  const level = context.createGain();
  source.buffer = wood;
  body.type = 'bandpass';
  body.frequency.value = frequency * 3;
  body.Q.value = .9;
  level.gain.value = volume;
  source.connect(body).connect(level).connect(master);
  source.start(time);
  source.onended = () => {source.disconnect();body.disconnect();level.disconnect();};
  tone(time, frequency, .075, volume * .34, frequency * .67);
}

export function cue(event) {
  if (!enabled || document.hidden) return;
  if (!AudioEngine || engineFailed) {
    if (fallback) tryFallback(event);
    return;
  }
  if (context?.state !== 'running') return;
  const time = context.currentTime + .015;
  if (event === 'move') knock(time, 266, .16);
  else if (event === 'wall') {
    knock(time, 182, .22);
    knock(time + .042, 147, .12);
  } else {
    const duration = event === 'loss' ? .29 : .24;
    melodies[event]?.forEach((frequency, i) => tone(time + i * .092, frequency, duration, .055));
  }
}
