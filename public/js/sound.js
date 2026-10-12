// Short synthesised sounds (no audio files to download). Off by default; the choice is
// remembered on this device (REQ-UI-09).

const KEY = "labscloud-chess:sound";

const TONES = {
  move: [[520, 0.06]],
  capture: [
    [330, 0.05],
    [250, 0.07],
  ],
  check: [
    [660, 0.07],
    [880, 0.09],
  ],
  end: [
    [523, 0.12],
    [659, 0.12],
    [784, 0.22],
  ],
};

export function soundEnabled() {
  try {
    return localStorage.getItem(KEY) === "on";
  } catch (error) {
    return false;
  }
}

export function setSoundEnabled(on) {
  try {
    localStorage.setItem(KEY, on ? "on" : "off");
  } catch (error) {
    // private mode: the setting just won't stick
  }
}

let context = null;

function audio() {
  if (context) return context;
  const Ctor = globalThis.AudioContext || globalThis.webkitAudioContext;
  if (!Ctor) return null;
  try {
    context = new Ctor();
  } catch (error) {
    context = null;
  }
  return context;
}

/** Call from a user gesture (e.g. the sound toggle) so iOS lets audio play later. */
export function unlockAudio() {
  const ctx = audio();
  if (ctx && ctx.state === "suspended") ctx.resume().catch(() => {});
}

export function play(kind) {
  if (!soundEnabled()) return;
  const ctx = audio();
  const notes = TONES[kind];
  if (!ctx || !notes) return;
  let at = ctx.currentTime + 0.01;
  for (const [frequency, duration] of notes) {
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = "triangle";
    osc.frequency.value = frequency;
    gain.gain.setValueAtTime(0.0001, at);
    gain.gain.exponentialRampToValueAtTime(0.18, at + 0.01);
    gain.gain.exponentialRampToValueAtTime(0.0001, at + duration);
    osc.connect(gain).connect(ctx.destination);
    osc.start(at);
    osc.stop(at + duration + 0.02);
    at += duration * 0.9;
  }
}

export function vibrate(pattern) {
  try {
    if (navigator.vibrate) navigator.vibrate(pattern);
  } catch (error) {
    // not supported
  }
}
