/**
 * Small, dependency-free Web Audio layer.
 *
 * Browsers only allow audio after a user gesture, so the app arms this on the
 * first pointerdown. The ambient pad is deliberately quiet; every sound can be
 * muted from the header and the choice is remembered locally.
 */

type SfxKind = "night" | "day" | "vote" | "death" | "turn" | "join";

let context: AudioContext | null = null;
let master: GainNode | null = null;
let ambient: {
  oscillators: OscillatorNode[];
  gain: GainNode;
} | null = null;

let enabled =
  typeof localStorage === "undefined"
    ? true
    : localStorage.getItem("wolfarena.audio") !== "off";

function ensureContext(): AudioContext {
  if (context === null) {
    context = new AudioContext();
    master = context.createGain();
    master.gain.value = 0.7;
    master.connect(context.destination);
  }
  if (context.state === "suspended") {
    void context.resume();
  }
  return context;
}

function tone(
  frequency: number,
  duration: number,
  type: OscillatorType,
  at: number,
  volume: number,
): void {
  if (context === null || master === null) {
    return;
  }
  const oscillator = context.createOscillator();
  const envelope = context.createGain();
  oscillator.type = type;
  oscillator.frequency.setValueAtTime(frequency, at);
  envelope.gain.setValueAtTime(0.0001, at);
  envelope.gain.exponentialRampToValueAtTime(volume, at + 0.02);
  envelope.gain.exponentialRampToValueAtTime(0.0001, at + duration);
  oscillator.connect(envelope);
  envelope.connect(master);
  oscillator.start(at);
  oscillator.stop(at + duration + 0.05);
}

export function audioEnabled(): boolean {
  return enabled;
}

export function setAudioEnabled(value: boolean): void {
  enabled = value;
  if (typeof localStorage !== "undefined") {
    localStorage.setItem("wolfarena.audio", value ? "on" : "off");
  }
  if (!value) {
    stopAmbient();
    return;
  }
  ensureContext();
  startAmbient();
}

export function initAudio(): void {
  if (!enabled) {
    return;
  }
  ensureContext();
  startAmbient();
}

export function playSfx(kind: SfxKind): void {
  if (!enabled) {
    return;
  }
  const current = ensureContext();
  const now = current.currentTime;
  switch (kind) {
    case "night":
      tone(196, 0.7, "sine", now, 0.12);
      tone(146.83, 0.9, "sine", now + 0.16, 0.1);
      break;
    case "day":
      tone(523.25, 0.28, "triangle", now, 0.1);
      tone(659.25, 0.32, "triangle", now + 0.14, 0.08);
      break;
    case "vote":
      tone(392, 0.16, "square", now, 0.05);
      tone(523.25, 0.2, "square", now + 0.1, 0.045);
      break;
    case "death":
      tone(110, 0.9, "sawtooth", now, 0.07);
      tone(82.41, 1.0, "sine", now + 0.12, 0.09);
      break;
    case "turn":
      tone(880, 0.12, "sine", now, 0.07);
      tone(1046.5, 0.16, "sine", now + 0.08, 0.05);
      break;
    case "join":
      tone(659.25, 0.16, "triangle", now, 0.06);
      break;
  }
}

export function startAmbient(): void {
  if (!enabled || ambient !== null) {
    return;
  }
  const current = ensureContext();
  if (master === null) {
    return;
  }
  const gain = current.createGain();
  gain.gain.setValueAtTime(0.0001, current.currentTime);
  gain.gain.exponentialRampToValueAtTime(
    0.028,
    current.currentTime + 3,
  );
  gain.connect(master);

  const filter = current.createBiquadFilter();
  filter.type = "lowpass";
  filter.frequency.value = 420;
  filter.connect(gain);

  const low = current.createOscillator();
  low.type = "sine";
  low.frequency.value = 55;
  low.connect(filter);

  const fifth = current.createOscillator();
  fifth.type = "sine";
  fifth.frequency.value = 82.5;
  fifth.connect(filter);

  const lfo = current.createOscillator();
  lfo.type = "sine";
  lfo.frequency.value = 0.07;
  const lfoGain = current.createGain();
  lfoGain.gain.value = 0.01;
  lfo.connect(lfoGain);
  lfoGain.connect(gain.gain);

  low.start();
  fifth.start();
  lfo.start();
  ambient = { oscillators: [low, fifth, lfo], gain };
}

export function stopAmbient(): void {
  if (ambient === null || context === null) {
    return;
  }
  const { oscillators, gain } = ambient;
  ambient = null;
  const now = context.currentTime;
  gain.gain.cancelScheduledValues(now);
  gain.gain.setValueAtTime(Math.max(gain.gain.value, 0.0001), now);
  gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.8);
  for (const oscillator of oscillators) {
    oscillator.stop(now + 0.9);
  }
  window.setTimeout(() => {
    for (const oscillator of oscillators) {
      oscillator.disconnect();
    }
    gain.disconnect();
  }, 1000);
}
