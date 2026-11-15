import { useCallback, useEffect, useRef, useState } from "react";
import ActionCard from "./ActionCard";
import { Icon } from "./icons";
import { canRecord, canRetry, onSpeakingChange, postAudio, record, Recording, speak, stopSpeaking, unlockAudio, voiceErrorText } from "../voice";

type Phase = "idle" | "listening" | "thinking" | "done" | "error";
const TAB_NAME: Record<string, string> = {
  home: "Today", transactions: "Transactions", stock: "Stock", udhaar: "Udhaar", customers: "Customers",
  approvals: "Approvals", money: "Money & GST", marketing: "Marketing", growth: "Growth Advisor", chat: "Ask Saathi", shop: "My Shop", privacy: "Privacy",
};

/** Floating "talk to Saathi" button available on every page. Speak in any supported language; Saathi answers in text
 *  and voice, can open pages ("open stock"), and shows anything that needs approval right here. */
export default function VoiceAssistant({ lang, go, tab }: { lang: string; go: (t: string) => void; tab: string }) {
  const [open, setOpen] = useState(false);
  const [phase, setPhase] = useState<Phase>("idle");
  const [heard, setHeard] = useState("");
  const [reply, setReply] = useState<{ text: string; lang: string } | null>(null);
  const [actions, setActions] = useState<any[]>([]);
  const [suggest, setSuggest] = useState<string | null>(null);
  const [err, setErr] = useState("");
  const [speaking, setSpeaking] = useState(false);
  const [level, setLevel] = useState(0);
  const recRef = useRef<Recording | null>(null);
  const lastBlob = useRef<Blob | null>(null); // kept so "Try again" does not make the merchant speak again
  const [retry, setRetry] = useState(false);
  const sid = useRef<string | undefined>(undefined);
  const busy = phase === "listening" || phase === "thinking";

  useEffect(() => onSpeakingChange(setSpeaking), []);
  useEffect(() => () => { recRef.current?.cancel(); }, []);
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") close(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }); // eslint-disable-line

  const close = () => { recRef.current?.cancel(); stopSpeaking(); setOpen(false); setPhase("idle"); };

  const ask = useCallback(async (blob: Blob) => {
    setPhase("thinking"); setErr(""); setRetry(false);
    try {
      const q = new URLSearchParams({ language: lang, speak: "false" });
      if (sid.current) q.set("session_id", sid.current);
      const r = await postAudio(`/voice/ask?${q}`, blob);
      if (r.heard_nothing || !r.transcript) { setErr("I didn’t catch that. Please say it again."); setPhase("error"); return; }
      lastBlob.current = null;
      sid.current = r.session_id || sid.current;
      setHeard(r.transcript);
      setReply({ text: r.reply, lang: r.language || lang });
      setActions(r.pending_actions || []);
      setSuggest(r.navigate ? null : r.suggest_tab && r.suggest_tab !== tab ? r.suggest_tab : null);
      setPhase("done");
      if (r.navigate) go(r.navigate);
      if (r.reply) speak(r.reply, r.language || lang);
    } catch (e) {
      setErr(voiceErrorText(e)); setRetry(canRetry(e) && !!lastBlob.current); setPhase("error");
    }
  }, [lang, go, tab]);

  const listen = useCallback(async () => {
    unlockAudio(); // must happen inside the tap so the answer can be played later (Safari)
    if (phase === "listening") { recRef.current?.stop(); return; }
    if (phase === "thinking") return;
    stopSpeaking();
    setOpen(true); setErr(""); setRetry(false); setHeard(""); setReply(null); setActions([]); setSuggest(null);
    let rec: Recording;
    try { rec = await record(); } catch (e) { setErr(voiceErrorText(e)); setPhase("error"); return; }
    recRef.current = rec;
    setPhase("listening");
    let raf = 0;
    const meter = () => { setLevel(rec.level()); raf = requestAnimationFrame(meter); };
    raf = requestAnimationFrame(meter);
    const blob = await rec.done;
    cancelAnimationFrame(raf); setLevel(0);
    recRef.current = null;
    if (!blob) { setErr("I didn’t hear anything. Tap the mic and speak."); setPhase("error"); return; }
    lastBlob.current = blob;
    await ask(blob);
  }, [phase, ask]);

  const status = phase === "listening" ? "Listening… speak now" : phase === "thinking" ? "Saathi is thinking…" : phase === "error" ? "Couldn’t hear you" : "Saathi";

  if (!canRecord()) return null;
  return (
    <>
      {open && (
        <div role="dialog" aria-label="Voice assistant" className="pop fixed z-40 bottom-[168px] lg:bottom-[104px] right-4 sm:right-6 w-[min(400px,calc(100vw-32px))] max-h-[min(64vh,600px)] overflow-y-auto rounded-3xl bg-white/95 backdrop-blur-xl border border-line shadow-[0_30px_80px_-20px_rgba(11,42,91,.45)]">
          <div className="flex items-center justify-between gap-2 px-4 py-3 sticky top-0 hero !rounded-none">
            <p className="font-bold text-sm flex items-center gap-2.5" aria-live="polite">
              {phase === "listening" ? <span className="inline-block h-2.5 w-2.5 rounded-full bg-red-400 animate-pulse" aria-hidden /> : <span className="grid place-items-center h-7 w-7 rounded-lg bg-white/15"><Icon name="sparkles" size={15} /></span>}{status}
            </p>
            <div className="flex items-center gap-1">
              {speaking && <button className="btn btn-glass !min-h-8 !py-1 text-xs" onClick={stopSpeaking}><Icon name="stop" size={14} />Stop voice</button>}
              <button onClick={close} aria-label="Close voice assistant" className="h-8 w-8 grid place-items-center rounded-lg text-white/80 hover:bg-white/15"><Icon name="x" size={18} /></button>
            </div>
          </div>
          <div className="p-4 space-y-3 text-[15px]">
            {phase === "listening" && (
              <div className="flex items-end gap-1 h-8" aria-hidden>
                {[0.5, 0.8, 1, 0.8, 0.5].map((k, i) => <span key={i} className="w-1.5 rounded-full bg-gradient-to-t from-primary to-accent transition-all" style={{ height: `${Math.max(12, Math.min(100, level * 900 * k))}%` }} />)}
                <span className="ml-3 text-xs text-muted self-center">Stops by itself when you finish</span>
              </div>)}
            {heard && <p className="rounded-2xl rounded-br-md bg-gradient-to-br from-primary to-brand-2 text-white px-4 py-2.5 ml-10 shadow-md" translate="no">{heard}</p>}
            {phase === "thinking" && <div className="flex gap-1.5 px-2" aria-hidden>{[0, 1, 2].map((i) => <span key={i} className="h-2 w-2 rounded-full bg-primary/60 animate-bounce" style={{ animationDelay: `${i * 120}ms` }} />)}</div>}
            {reply && (
              <div className="rounded-2xl rounded-bl-md bg-surface ring-1 ring-line px-4 py-3 mr-6">
                <p className="whitespace-pre-wrap leading-relaxed">{reply.text}</p>
                <button className="inline-flex items-center gap-1.5 text-xs font-semibold text-primary mt-2 hover:underline" onClick={() => { unlockAudio(); speaking ? stopSpeaking() : speak(reply.text, reply.lang); }}><Icon name={speaking ? "stop" : "volume"} size={14} />{speaking ? "Stop" : "Listen"}</button>
              </div>)}
            {actions.map((a) => <ActionCard key={a.id} action={a} onDone={() => setActions((x) => x.filter((y) => y.id !== a.id))} />)}
            {suggest && <button className="btn btn-ghost w-full" onClick={() => { go(suggest); }}>Open {TAB_NAME[suggest] || suggest}<Icon name="arrow" size={16} /></button>}
            {err && <p className="text-sm text-red-600">{err}</p>}
            {retry && phase === "error" && <button className="btn btn-primary w-full" onClick={() => { unlockAudio(); if (lastBlob.current) ask(lastBlob.current); }}>Try again</button>}
            {phase === "idle" && !reply && <p className="text-sm text-muted">Ask anything in your language, or say “open stock”.</p>}
          </div>
        </div>)}
      <button data-voice-button onClick={listen} disabled={phase === "thinking"} aria-label={phase === "listening" ? "Stop listening" : "Talk to Saathi"}
        className={`fixed z-40 bottom-[88px] lg:bottom-6 right-4 sm:right-6 h-16 w-16 rounded-full grid place-items-center text-white ring-4 ring-white/70 transition-transform hover:scale-105 active:scale-95 disabled:opacity-70 ${phase === "listening" ? "bg-red-500 listening" : "bg-gradient-to-br from-accent via-primary to-brand-2 fab"}`}>
        {phase === "thinking" ? <span className="h-6 w-6 rounded-full border-2 border-white/40 border-t-white animate-spin" aria-hidden /> : <Icon name="mic" size={28} />}
      </button>
      {busy && <span className="sr-only" aria-live="assertive">{status}</span>}
    </>
  );
}
