// Voice for the whole app, powered by Sarvam AI through our backend.
// - Recording: microphone -> 16 kHz mono WAV (works in Safari, Chrome, Firefox), stops by itself after you finish talking.
// - Speaking: text -> Sarvam speech, one sentence at a time so the first words play within a couple of seconds.
// - Fallback: if Sarvam is unreachable, the browser's own speech engine is used so "Listen" never silently fails.
import { api, ApiError, authHeaders } from "./api";
import { BROWSER_SPEECH } from "./languages";

// ------------------------------------------------------------------ playback

let audioEl: HTMLAudioElement | null = null;
let playToken = 0;
const listeners = new Set<(on: boolean) => void>();
let speakingNow = false;
const setSpeaking = (on: boolean) => { speakingNow = on; listeners.forEach((f) => f(on)); };
export const onSpeakingChange = (f: (on: boolean) => void) => { listeners.add(f); return () => { listeners.delete(f); }; };
export const isSpeaking = () => speakingNow;

// A tiny silent clip. Safari only lets a page play sound that was started from a tap, so every mic / Listen button
// calls unlockAudio() first; later (after the network round trip) the same element is allowed to play.
const SILENCE = (() => { // 0.1 s of silent 8 kHz WAV, generated so it is always a valid file
  const n = 800, v = new DataView(new ArrayBuffer(44 + n * 2));
  const w = (o: number, x: string) => { for (let i = 0; i < x.length; i++) v.setUint8(o + i, x.charCodeAt(i)); };
  w(0, "RIFF"); v.setUint32(4, 36 + n * 2, true); w(8, "WAVE"); w(12, "fmt "); v.setUint32(16, 16, true); v.setUint16(20, 1, true);
  v.setUint16(22, 1, true); v.setUint32(24, 8000, true); v.setUint32(28, 16000, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true);
  w(36, "data"); v.setUint32(40, n * 2, true);
  let bin = ""; const u8 = new Uint8Array(v.buffer); for (let i = 0; i < u8.length; i++) bin += String.fromCharCode(u8[i]);
  return "data:audio/wav;base64," + btoa(bin);
})();
export function unlockAudio() {
  if (!audioEl) { audioEl = new Audio(); audioEl.preload = "auto"; }
  try {
    audioEl.src = SILENCE;
    const p = audioEl.play();
    if (p) p.catch(() => { /* not allowed yet: fine */ });
  } catch { /* ignore */ }
  try { window.speechSynthesis?.resume(); } catch { /* ignore */ }
}

export function stopSpeaking() {
  playToken++;
  if (audioEl) { try { audioEl.pause(); audioEl.removeAttribute("src"); audioEl.load(); } catch { /* ignore */ } }
  try { window.speechSynthesis?.cancel(); } catch { /* ignore */ }
  setSpeaking(false);
}

function playClip(b64: string, mime: string, token: number): Promise<void> {
  return new Promise((resolve, reject) => {
    if (token !== playToken) return resolve();
    if (!audioEl) audioEl = new Audio();
    const el = audioEl;
    const done = () => { el.onended = el.onerror = null; resolve(); };
    el.onended = done;
    el.onerror = () => { el.onended = el.onerror = null; reject(new Error("playback")); };
    el.src = `data:${mime};base64,${b64}`;
    el.play().catch(reject);
  });
}

// Split into sentence-sized pieces (Devanagari danda and Latin punctuation), keeping pieces reasonably long.
export function sentences(text: string, max = 280): string[] {
  const raw = text.replace(/\s+/g, " ").trim().split(/(?<=[.!?।|])\s+/);
  const out: string[] = [];
  let cur = "";
  for (const s of raw) {
    if (!s) continue;
    if (cur && (cur + " " + s).length > max) { out.push(cur); cur = s; } else cur = cur ? cur + " " + s : s;
  }
  if (cur) out.push(cur);
  return out.length ? out : [text];
}

const clipCache = new Map<string, Promise<{ audios: string[]; mime: string }>>();
function fetchClip(text: string, lang: string) {
  const key = lang + "|" + text;
  let p = clipCache.get(key);
  if (!p) {
    p = api<{ audios: string[]; mime: string }>("/voice/tts", { method: "POST", body: { text, language: lang } });
    p.catch(() => clipCache.delete(key));
    clipCache.set(key, p);
    if (clipCache.size > 80) clipCache.delete(clipCache.keys().next().value as string);
  }
  return p;
}

function browserSpeak(text: string, lang: string, token: number): Promise<void> {
  return new Promise((resolve) => {
    if (!("speechSynthesis" in window) || token !== playToken) return resolve();
    const u = new SpeechSynthesisUtterance(text);
    u.lang = BROWSER_SPEECH[lang] || "en-IN";
    u.rate = 0.95;
    u.onend = () => resolve();
    u.onerror = () => resolve();
    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(u);
  });
}

/** Read text aloud in the merchant's language. Resolves when finished (or stopped). Never throws. */
export async function speak(text: string, lang: string): Promise<void> {
  stopSpeaking();
  const token = ++playToken;
  const parts = sentences(text || "");
  if (!parts.join("").trim()) return;
  setSpeaking(true);
  try {
    // Prefetch two pieces ahead while the current one plays.
    const jobs = parts.map(() => null as null | ReturnType<typeof fetchClip>);
    const get = (i: number) => (jobs[i] ??= fetchClip(parts[i], lang));
    for (let i = 0; i < parts.length; i++) {
      if (token !== playToken) return;
      get(i); if (i + 1 < parts.length) get(i + 1); if (i + 2 < parts.length) get(i + 2);
      let clip: { audios: string[]; mime: string };
      try { clip = await get(i); } catch (e) {
        // Sarvam unavailable: read the rest with the browser voice instead of stopping mid-way.
        await browserSpeak(parts.slice(i).join(" "), lang, token);
        return;
      }
      for (const a of clip.audios) {
        if (token !== playToken) return;
        try { await playClip(a, clip.mime || "audio/mpeg", token); } catch { await browserSpeak(parts.slice(i).join(" "), lang, token); return; }
      }
    }
  } finally {
    if (token === playToken) setSpeaking(false);
  }
}

// ------------------------------------------------------------------ recording

export type Recording = { stop: () => void; cancel: () => void; done: Promise<Blob | null>; level: () => number };
export const canRecord = () => !!(navigator.mediaDevices?.getUserMedia) && typeof MediaRecorder !== "undefined";

export class MicError extends Error {}

/** Start listening. Stops automatically ~1.4 s after the merchant stops talking, after 8 s of silence, or at 28 s. */
export async function record(opts: { maxMs?: number; silenceMs?: number } = {}): Promise<Recording> {
  if (!canRecord()) throw new MicError("This browser can’t record audio. Please type instead.");
  let stream: MediaStream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, channelCount: 1 } });
  } catch (e: any) {
    throw new MicError(e?.name === "NotAllowedError" || e?.name === "SecurityError"
      ? "Microphone permission is blocked. Allow it in your browser’s site settings."
      : e?.name === "NotFoundError" ? "No microphone found." : "Couldn’t start the microphone.");
  }
  const types = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus"];
  const mimeType = types.find((t) => (MediaRecorder as any).isTypeSupported?.(t));
  const rec = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
  const chunks: BlobPart[] = [];
  let cancelled = false;
  rec.ondataavailable = (e) => { if (e.data.size) chunks.push(e.data); };

  // Voice activity: watch the input level to stop when the merchant goes quiet.
  const AC: typeof AudioContext = (window as any).AudioContext || (window as any).webkitAudioContext;
  const ctx = new AC();
  const src = ctx.createMediaStreamSource(stream);
  const an = ctx.createAnalyser();
  an.fftSize = 1024;
  src.connect(an);
  const buf = new Float32Array(an.fftSize);
  let lvl = 0, heard = false, lastLoud = performance.now();
  const started = performance.now();
  const maxMs = opts.maxMs ?? 28000, silenceMs = opts.silenceMs ?? 1400;
  const tick = setInterval(() => {
    an.getFloatTimeDomainData(buf);
    let sum = 0; for (let i = 0; i < buf.length; i++) sum += buf[i] * buf[i];
    lvl = Math.sqrt(sum / buf.length);
    const now = performance.now();
    if (lvl > 0.02) { heard = true; lastLoud = now; }
    if ((heard && now - lastLoud > silenceMs) || (!heard && now - started > 8000) || now - started > maxMs) stop();
  }, 100);

  const cleanup = () => {
    clearInterval(tick);
    stream.getTracks().forEach((t) => t.stop());
    ctx.close().catch(() => { /* ignore */ });
  };
  const done = new Promise<Blob | null>((resolve) => {
    rec.onstop = () => { cleanup(); resolve(cancelled || !heard ? null : new Blob(chunks, { type: rec.mimeType || mimeType || "audio/webm" })); };
  });
  function stop() { if (rec.state !== "inactive") rec.stop(); }
  rec.start(250);
  return { stop, cancel: () => { cancelled = true; stop(); }, done, level: () => lvl };
}

/** Convert any recorded blob to 16 kHz mono 16-bit WAV (small, and accepted everywhere). Falls back to the original. */
export async function toWav(blob: Blob): Promise<Blob> {
  try {
    const AC: typeof AudioContext = (window as any).AudioContext || (window as any).webkitAudioContext;
    const ctx = new AC();
    const ab = await blob.arrayBuffer();
    const decoded = await new Promise<AudioBuffer>((res, rej) => ctx.decodeAudioData(ab, res, rej));
    ctx.close().catch(() => { /* ignore */ });
    const rate = 16000;
    const off = new OfflineAudioContext(1, Math.max(1, Math.ceil(decoded.duration * rate)), rate);
    const s = off.createBufferSource();
    s.buffer = decoded; s.connect(off.destination); s.start();
    const pcm = (await off.startRendering()).getChannelData(0);
    const out = new DataView(new ArrayBuffer(44 + pcm.length * 2));
    const w = (o: number, str: string) => { for (let i = 0; i < str.length; i++) out.setUint8(o + i, str.charCodeAt(i)); };
    w(0, "RIFF"); out.setUint32(4, 36 + pcm.length * 2, true); w(8, "WAVE"); w(12, "fmt ");
    out.setUint32(16, 16, true); out.setUint16(20, 1, true); out.setUint16(22, 1, true); out.setUint32(24, rate, true);
    out.setUint32(28, rate * 2, true); out.setUint16(32, 2, true); out.setUint16(34, 16, true); w(36, "data"); out.setUint32(40, pcm.length * 2, true);
    for (let i = 0; i < pcm.length; i++) { const v = Math.max(-1, Math.min(1, pcm[i])); out.setInt16(44 + i * 2, v < 0 ? v * 0x8000 : v * 0x7fff, true); }
    return new Blob([out], { type: "audio/wav" });
  } catch {
    return blob;
  }
}

/** POST raw audio to a voice endpoint. */
export async function postAudio<T = any>(path: string, blob: Blob): Promise<T> {
  const wav = await toWav(blob);
  let res: Response;
  try {
    res = await fetch(`/api${path}`, { method: "POST", headers: { ...authHeaders(), "Content-Type": wav.type || "application/octet-stream" }, body: wav });
  } catch {
    throw new ApiError(0, "Cannot reach the server. Check your connection.");
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError(res.status, data.detail ?? data);
  return data as T;
}

/** Worth re-sending the same recording? (network / busy, not "too short" or "not set up") */
export function canRetry(e: unknown): boolean {
  const err = e as ApiError;
  if (err?.status === 0) return true;
  const why = err?.detail?.reason;
  return err?.code === "voice_unavailable" && !["not_configured", "daily_budget"].includes(why);
}

export function voiceErrorText(e: unknown): string {
  if (e instanceof MicError) return e.message;
  const err = e as ApiError;
  if (err?.status === 0) return err.message;
  if (err?.code === "voice_unavailable") {
    const why = err.detail?.reason;
    if (why === "unreachable" || why === "ConnectTimeout" || why === "ConnectError") return "Couldn’t reach the voice service. Check your internet and tap Try again.";
    if (why === "rate_limited" || why === "http_429") return "Voice service is busy right now. Tap Try again in a few seconds.";
    if (why === "not_configured") return "Voice isn’t set up on this server. Please type instead.";
    if (why === "daily_budget") return "Today’s voice limit is used up. Please type instead; voice is back tomorrow.";
    return "Voice service didn’t respond. Tap Try again, or type instead.";
  }
  if (err?.code === "audio_too_long") return "That was too long. Please keep it under 30 seconds.";
  if (err?.code === "audio_too_short") return "I didn’t hear anything. Tap the mic and speak.";
  return "Couldn’t process that. Please try again.";
}
