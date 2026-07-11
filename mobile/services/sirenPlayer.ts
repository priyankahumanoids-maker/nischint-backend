// Siren Player — foreground fallback for `louder_push` FCM alerts.
//
// When the app is FOREGROUND on Android, the system suppresses the
// heads-up presentation of an incoming FCM notification (it routes to
// `setNotificationHandler`). That means even with `bypassDnd` and the
// `critical_safety` channel, the user may not get a "siren" experience
// while staring at the app.
//
// This helper plays the bundled `siren_loop.wav` on a loop until
// ACK'd. Used by `pushService` when a foreground push arrives carrying
// `data.louder_push === "true"`.
//
// Migrated from `expo-av` (SDK 54) → `expo-audio` (SDK 55). The class-
// based `createAudioPlayer` factory is used because this is imperative
// service code, not a React component. `setAudioModeAsync` uses the
// new single `interruptionMode: 'doNotMix'` contract.
import {
  createAudioPlayer,
  setAudioModeAsync,
  type AudioPlayer,
} from 'expo-audio';

let _player: AudioPlayer | null = null;
let _playing = false;

export async function playSirenLoop(maxDurationMs: number = 30000): Promise<void> {
  if (_playing) return;
  _playing = true;
  try {
    await setAudioModeAsync({
      playsInSilentMode: true,
      shouldPlayInBackground: true,
      interruptionMode: 'doNotMix',
      allowsRecording: false,
      shouldRouteThroughEarpiece: false,
    });
    const player = createAudioPlayer(require('../assets/sounds/siren_loop.wav'));
    player.loop = true;
    player.volume = 1.0;
    player.play();
    _player = player;
    // Auto-stop after maxDurationMs as a guard against infinite siren if
    // ACK signal never arrives.
    setTimeout(() => { stopSirenLoop().catch(() => {}); }, maxDurationMs);
  } catch (e: any) {
    console.warn('[SIREN] playback failed:', e?.message || e);
    _playing = false;
  }
}

export async function stopSirenLoop(): Promise<void> {
  _playing = false;
  const p = _player;
  _player = null;
  if (!p) return;
  try {
    p.pause();
    p.remove();
  } catch {}
}

export function isSirenPlaying(): boolean {
  return _playing;
}
