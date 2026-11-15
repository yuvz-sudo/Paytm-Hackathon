import { useT } from "../i18n";
import { Icon } from "../components/icons";
import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "../api";
import { canRecord, canRetry, onSpeakingChange, postAudio, record, Recording, speak, stopSpeaking, unlockAudio, voiceErrorText } from "../voice";
import ActionCard from "../components/ActionCard";

type Msg = { role: "user" | "assistant"; text: string; lang?: string; actions?: any[]; engine?: string };

// Other languages use the English list; the page translator shows them in the merchant's language,
// and Saathi understands the English text in any language mode.
const SUGGEST: Record<string, string[]> = {
  en: ["Daily briefing", "Yesterday's sales", "What's low in stock?", "Who owes me money?", "What should I stock for the festival?", "Do I need a loan?"],
  hinglish: ["Aaj ka briefing", "Kal ki sales kitni thi?", "Stock mein kya kam hai?", "Kiska udhaar baaki hai?", "GST kitna banega?", "Slow time kaunsa hai?"],
  hi: ["आज की ब्रीफिंग", "कल की बिक्री कितनी हुई?", "स्टॉक में क्या कम है?", "किसका उधार बाकी है?", "GST कितना बनेगा?", "कौन सा समय धीमा रहता है?"],
};
const HELLO: Record<string, string> = { hinglish: "Namaste! Main aapka Dukaan Saathi hoon.", hi: "नमस्ते! मैं आपका दुकान साथी हूँ।" };

export default function Chat({ lang, merchantId, initial = "" }: { lang: string; merchantId: number; initial?: string }) {
  const t = useT();
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [sid, setSid] = useState<string | undefined>();
  const [autoSpeak, setAutoSpeak] = useState(() => { try { return localStorage.getItem("autoSpeak") === "1"; } catch { return false; } });
  const [listening, setListening] = useState(false);
  const [speakingNow, setSpeakingNow] = useState(false);
  const [micErr, setMicErr] = useState("");
  const recRef = useRef<Recording | null>(null);
  const lastBlob = useRef<Blob | null>(null);
  const [canTryAgain, setCanTryAgain] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);

  const [loaded, setLoaded] = useState(false);
  const [keepDays, setKeepDays] = useState(7);
  // bring back the latest conversation (kept on the server for 7 days)
  useEffect(() => {
    let live = true;
    setMsgs([]); setSid(undefined); setLoaded(false);
    api("/chat/recent").then((r) => {
      if (!live) return;
      setKeepDays(r.retention_days || 7);
      let cleared: string | null = null;
      try { cleared = localStorage.getItem(`chatCleared:${merchantId}`); } catch { /* ignore */ }
      if (r.session_id && r.messages?.length && r.session_id !== cleared) {
        setSid(r.session_id);
        setMsgs((m) => [...r.messages.map((x: any) => ({ role: x.role, text: x.text, lang: x.lang || undefined, actions: x.actions })), ...m]);
      }
    }).catch(() => { /* start fresh */ }).finally(() => live && setLoaded(true));
    return () => { live = false; };
  }, [merchantId]);
  const newChat = () => {
    if (sid) { try { localStorage.setItem(`chatCleared:${merchantId}`, sid); } catch { /* ignore */ } } // stays cleared after a reload
    stopSpeaking(); setMsgs([]); setSid(undefined); setInput(""); setMicErr("");
  };
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth" }); }, [msgs, busy]);
  useEffect(() => onSpeakingChange(setSpeakingNow), []);
  useEffect(() => () => { recRef.current?.cancel(); stopSpeaking(); }, []);
  useEffect(() => { try { localStorage.setItem("autoSpeak", autoSpeak ? "1" : "0"); } catch { /* ignore */ } }, [autoSpeak]);

  const answered = useCallback((r: any) => {
    setSid(r.session_id);
    setMsgs((m) => [...m, { role: "assistant", text: r.reply, lang: r.language || lang, actions: r.pending_actions, engine: r.engine }]);
    if (autoSpeak && r.reply) speak(r.reply, r.language || lang);
  }, [autoSpeak, lang]);

  const failed = (e: unknown) => {
    const err = e as ApiError;
    setMsgs((m) => [...m, { role: "assistant", text: err.status === 0 ? err.message : "Sorry, I couldn’t process that. Please try again." }]);
  };

  const send = useCallback(async (text: string) => {
    text = text.trim();
    if (!text || busy) return;
    unlockAudio();
    setInput(""); setMicErr("");
    setMsgs((m) => [...m, { role: "user", text }]);
    setBusy(true);
    try {
      answered(await api("/chat", { method: "POST", body: { message: text, session_id: sid, language: lang } }));
    } catch (e) { failed(e); } finally { setBusy(false); }
  }, [busy, sid, lang, answered]);

  const mic = async () => {
    unlockAudio();
    if (listening) { recRef.current?.stop(); return; }
    if (busy) return;
    stopSpeaking(); setMicErr(""); setCanTryAgain(false);
    let rec: Recording;
    try { rec = await record(); } catch (e) { setMicErr(voiceErrorText(e)); return; }
    recRef.current = rec; setListening(true);
    const blob = await rec.done;
    recRef.current = null; setListening(false);
    if (!blob) { setMicErr("I didn’t hear anything. Tap the mic and speak."); return; }
    lastBlob.current = blob;
    await askVoice(blob);
  };

  const askVoice = async (blob: Blob) => {
    setBusy(true); setMicErr(""); setCanTryAgain(false);
    try {
      const q = new URLSearchParams({ language: lang, speak: "false" });
      if (sid) q.set("session_id", sid);
      const r = await postAudio(`/voice/ask?${q}`, blob);
      lastBlob.current = null;
      if (!r.transcript) { setMicErr("I didn’t catch that. Please say it again."); return; }
      setMsgs((m) => [...m, { role: "user", text: r.transcript }]);
      if (r.navigate) r.reply = r.reply + " (Use the menu or the mic button on other pages to open it.)";
      answered(r);
    } catch (e) {
      setMicErr(voiceErrorText(e)); setCanTryAgain(canRetry(e) && !!lastBlob.current);
    } finally { setBusy(false); }
  };

  // opened from "Ask Saathi about this": send that question once
  const sentInitial = useRef(false);
  useEffect(() => {
    if (loaded && initial.trim() && !sentInitial.current) { sentInitial.current = true; send(initial); }
  }, [initial, loaded]); // eslint-disable-line

  const suggestions = SUGGEST[lang] || SUGGEST.en;
  const dropAction = (mi: number, id: number) => setMsgs((m) => m.map((x, i) => (i === mi ? { ...x, actions: x.actions?.filter((a) => a.id !== id) } : x)));

  return (
    <div className="card flex flex-col h-[calc(100dvh-260px)] lg:h-[calc(100dvh-200px)] min-h-[480px] overflow-hidden">
      <div className="flex items-center justify-between gap-3 px-4 sm:px-5 py-3 sm:py-3.5 border-b border-line bg-gradient-to-r from-white to-sky-50/60">
        <div className="flex items-center gap-3 min-w-0">
          <span className="hidden sm:grid icon-tile !h-10 !w-10 !rounded-xl text-white bg-gradient-to-br from-accent to-primary shadow-[var(--shadow-glow)]"><Icon name="sparkles" size={20} /></span>
          <div className="min-w-0">
          <p className="font-bold text-sm flex items-center gap-2">{t("Ask Dukaan Saathi")}<span className="inline-flex items-center gap-1 text-[11px] font-semibold text-emerald-700"><span className="h-1.5 w-1.5 rounded-full bg-emerald-500" aria-hidden />online</span></p>
          <p className="hidden sm:block text-xs text-muted truncate">Type or tap the mic, in any Indian language. Chats are kept for {keepDays} days.</p>
          </div>
        </div>
        <div className="flex items-center gap-3 shrink-0">
        {msgs.length > 0 && <button className="btn btn-ghost !min-h-9 !py-1 text-xs" onClick={newChat} disabled={busy} aria-label="New chat"><Icon name="plus" size={14} /><span className="hidden sm:inline">New chat</span></button>}
        <label className="flex items-center gap-2 text-xs text-muted cursor-pointer select-none shrink-0">
          <input type="checkbox" checked={autoSpeak} onChange={(e) => { unlockAudio(); setAutoSpeak(e.target.checked); if (!e.target.checked) stopSpeaking(); }} /> {t("Speak replies")}
        </label>
        </div>
      </div>
      <div className="flex-1 overflow-y-auto p-5 space-y-4" aria-live="polite">
        {msgs.length === 0 && !loaded && <p className="text-sm text-muted text-center mt-8">{t("Loading…")}</p>}
        {msgs.length === 0 && loaded && (
          <div className="text-center mt-8">
            <div className="mx-auto h-16 w-16 rounded-3xl grid place-items-center text-white bg-gradient-to-br from-accent via-primary to-brand-2 shadow-[var(--shadow-glow)]"><Icon name="sparkles" size={30} /></div>
            <p className="font-extrabold text-lg mt-4">{HELLO[lang] || "Namaste! I’m your Dukaan Saathi."}</p>
            <p className="text-sm text-muted mt-1">{t("Try one of these:")}</p>
            <div className="flex flex-wrap justify-center gap-2 mt-4">
              {suggestions.map((s) => <button key={s} className="btn btn-ghost hover:!border-primary/40 hover:!text-primary" onClick={() => send(s)}>{s}</button>)}
            </div>
          </div>
        )}
        {msgs.map((m, i) => (
          <div key={i} className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
            <div className={`max-w-[85%] ${m.role === "user" ? "bg-gradient-to-br from-primary to-brand-2 text-white rounded-2xl rounded-br-md shadow-md" : "bg-surface ring-1 ring-line rounded-2xl rounded-bl-md"} px-4 py-2.5 text-[15px] leading-relaxed`}>
              <p className="whitespace-pre-wrap" translate={m.role === "user" ? "no" : undefined}>{m.text}</p>
              {m.role === "assistant" && (
                <button className="inline-flex items-center gap-1 text-[11.5px] font-semibold text-primary mt-1.5 hover:underline" onClick={() => { unlockAudio(); speakingNow ? stopSpeaking() : speak(m.text, m.lang || lang); }} aria-label="Read aloud"><Icon name={speakingNow ? "stop" : "volume"} size={13} />{speakingNow ? t("Stop") : t("Listen")}</button>
              )}
              {m.actions && m.actions.length > 0 && (
                <div className="mt-3 space-y-2 min-w-[min(520px,75vw)]">
                  {m.actions.map((a) => <ActionCard key={a.id} action={a} onDone={() => dropAction(i, a.id)} />)}
                </div>
              )}
            </div>
          </div>
        ))}
        {busy && <div className="flex items-center gap-2 text-sm text-muted"><span className="flex gap-1" aria-hidden>{[0, 1, 2].map((i) => <span key={i} className="h-1.5 w-1.5 rounded-full bg-primary/60 animate-bounce" style={{ animationDelay: `${i * 120}ms` }} />)}</span>{t("Saathi is thinking…")}</div>}
        <div ref={endRef} />
      </div>
      {micErr && (
        <p className="px-5 pb-1 text-xs text-red-600 flex items-center gap-3" role="alert">{micErr}
          {canTryAgain && <button className="font-semibold underline text-cyan" disabled={busy} onClick={() => { unlockAudio(); if (lastBlob.current) askVoice(lastBlob.current); }}>Try again</button>}
        </p>)}
      <form className="flex items-center gap-2 p-3 border-t border-line bg-white" onSubmit={(e: FormEvent) => { e.preventDefault(); send(input); }}>
        {canRecord() && (
          <button type="button" aria-label={listening ? "Stop listening" : "Speak"} onClick={mic} disabled={busy && !listening}
            className={`h-11 w-11 shrink-0 rounded-full grid place-items-center transition-colors ${listening ? "bg-red-500 text-white listening" : "bg-sky-50 text-primary ring-1 ring-sky-100 hover:bg-sky-100"}`}><Icon name={listening ? "stop" : "mic"} size={20} /></button>
        )}
        <input className="input flex-1 min-w-0 !rounded-full !px-5 text-[15px]" placeholder={listening ? t("Listening…") : t("Ask about sales, stock, udhaar…")}
          value={input} maxLength={1000} onChange={(e) => setInput(e.target.value)} aria-label="Message" />
        <button className="btn btn-primary h-11 !px-4 sm:!px-5" disabled={busy || !input.trim()} aria-label={t("Send")}><Icon name="send" size={17} /><span className="hidden sm:inline">{t("Send")}</span></button>
      </form>
    </div>
  );
}
