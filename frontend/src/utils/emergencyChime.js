/**
 * Escalating Alert Chimes — Web Audio API synthesizer
 * Severity-aware: single / double / triple chime + pulse.
 */

let audioCtx = null;

function ctx() {
  if (!audioCtx || audioCtx.state === 'closed') {
    audioCtx = new (window.AudioContext || window.webkitAudioContext)();
  }
  if (audioCtx.state === 'suspended') audioCtx.resume();
  return audioCtx;
}

function createReverb(ac, duration) {
  const rate = ac.sampleRate;
  const len = rate * duration;
  const buf = ac.createBuffer(2, len, rate);
  for (let ch = 0; ch < 2; ch++) {
    const data = buf.getChannelData(ch);
    for (let i = 0; i < len; i++) {
      data[i] = (Math.random() * 2 - 1) * Math.pow(1 - i / len, 2.4);
    }
  }
  const conv = ac.createConvolver();
  conv.buffer = buf;
  return conv;
}

function playTone(ac, dest, freq, startTime, dur, vol) {
  const osc = ac.createOscillator();
  const gain = ac.createGain();
  osc.type = 'sine';
  osc.frequency.setValueAtTime(freq, startTime);
  gain.gain.setValueAtTime(0, startTime);
  gain.gain.linearRampToValueAtTime(vol, startTime + 0.02);
  gain.gain.exponentialRampToValueAtTime(0.001, startTime + dur);
  osc.connect(gain);
  gain.connect(dest);
  osc.start(startTime);
  osc.stop(startTime + dur);
}

const SEVERITY = {
  low:      { notes: [{ freq: 523.25, time: 0, dur: 0.5, vol: 0.4 }], reverb: 1.0, volume: 0.2, sub: false },
  medium:   { notes: [{ freq: 523.25, time: 0, dur: 0.45, vol: 0.5 }, { freq: 659.25, time: 0.2, dur: 0.45, vol: 0.4 }], reverb: 1.4, volume: 0.3, sub: false },
  critical: { notes: [{ freq: 523.25, time: 0, dur: 0.6, vol: 0.6 }, { freq: 659.25, time: 0.18, dur: 0.5, vol: 0.5 }, { freq: 783.99, time: 0.36, dur: 0.8, vol: 0.4 }], reverb: 1.8, volume: 0.35, sub: true },
};

/**
 * Play escalation-aware alert chime.
 * @param {'low'|'medium'|'critical'} severity
 * @param {number} [volumeOverride] 0-1
 */
export function playAlertChime(severity = 'critical', volumeOverride) {
  try {
    const ac = ctx();
    const now = ac.currentTime;
    const cfg = SEVERITY[severity] || SEVERITY.critical;
    const vol = volumeOverride ?? cfg.volume;

    const master = ac.createGain();
    master.gain.setValueAtTime(vol, now);

    const reverb = createReverb(ac, cfg.reverb);
    const dry = ac.createGain();
    const wet = ac.createGain();
    dry.gain.setValueAtTime(0.7, now);
    wet.gain.setValueAtTime(0.3, now);

    master.connect(dry);
    master.connect(reverb);
    reverb.connect(wet);
    dry.connect(ac.destination);
    wet.connect(ac.destination);

    cfg.notes.forEach(n => playTone(ac, master, n.freq, now + n.time, n.dur, n.vol));

    if (cfg.sub) {
      const sub = ac.createOscillator();
      const subGain = ac.createGain();
      sub.type = 'sine';
      sub.frequency.setValueAtTime(65, now);
      subGain.gain.setValueAtTime(0, now);
      subGain.gain.linearRampToValueAtTime(vol * 0.25, now + 0.05);
      subGain.gain.exponentialRampToValueAtTime(0.001, now + 0.5);
      sub.connect(subGain);
      subGain.connect(ac.destination);
      sub.start(now);
      sub.stop(now + 0.5);
    }

    return true;
  } catch {
    return false;
  }
}

/** Backwards-compat alias */
export const playEmergencyChime = (vol) => playAlertChime('critical', vol);
