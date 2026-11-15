import { FormEvent, useEffect, useState } from "react";
import { api, ApiError, setDemo, setToken } from "../api";
import { Icon, Logo } from "../components/icons";

const MSG: Record<string, string> = {
  invalid_phone: "Enter a valid 10-digit Indian mobile number.",
  otp_incorrect: "That code isn’t right. Check and try again.",
  otp_expired: "That code has expired. Request a new one.",
  too_many_requests: "Too many requests. Please wait a while and try again.",
  sms_failed: "We couldn't send the SMS right now. Please try again in a moment.",
  too_many_attempts: "Too many wrong attempts. Request a new code.",
};

export default function Login({ onDone }: { onDone: () => void }) {
  const [phone, setPhone] = useState("");
  const [otp, setOtp] = useState("");
  const [step, setStep] = useState<"phone" | "otp">("phone");
  const [devOtp, setDevOtp] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [cool, setCool] = useState(0);
  const [demos, setDemos] = useState<any[]>([]);

  useEffect(() => { api("/merchants").then(setDemos).catch(() => setDemos([])); }, []);
  useEffect(() => { if (cool <= 0) return; const id = setTimeout(() => setCool(cool - 1), 1000); return () => clearTimeout(id); }, [cool]);

  const fail = (e: unknown) => { const x = e as ApiError; setErr(MSG[x.code || ""] || (x.status === 0 ? x.message : "Something went wrong. Please try again.")); };

  const sendOtp = async (e?: FormEvent) => {
    e?.preventDefault();
    setBusy(true); setErr(null);
    try { const r = await api("/auth/request-otp", { method: "POST", body: { phone } }); setDevOtp(r.dev_otp ?? null); setStep("otp"); setCool(30); setOtp(""); }
    catch (x) { fail(x); } finally { setBusy(false); }
  };
  const verify = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true); setErr(null);
    try { const r = await api("/auth/verify", { method: "POST", body: { phone, otp } }); setToken(r.token); onDone(); }
    catch (x) { fail(x); } finally { setBusy(false); }
  };

  const FEATURES: [string, string, string][] = [
    ["sparkles", "Daily AI briefing", "Know your sales, dues and stock before you open the shutter."],
    ["mic", "Talk in your language", "Ask by voice in Hindi, Marathi, Tamil and more."],
    ["shield", "You stay in control", "Nothing is sent and no money moves without your approval."],
  ];
  return (
    <div className="min-h-full grid lg:grid-cols-[1.1fr_1fr]">
      <section className="hero !rounded-none relative flex flex-col justify-between px-6 py-8 sm:px-12 lg:py-12 lg:min-h-full">
        <div className="flex items-center gap-3" translate="no"><Logo size={44} /><div><p className="text-xl font-extrabold tracking-tight">Dukaan <span className="text-accent">Saathi</span></p><p className="text-xs font-semibold text-sky-200/80">AI business partner · Paytm</p></div></div>
        <div className="hidden lg:block max-w-lg my-12">
          <span className="chip-ai"><Icon name="sparkles" size={14} />Built for Bharat’s merchants</span>
          <h1 className="mt-5 text-[44px] leading-[1.08] font-extrabold tracking-tight">Your shop’s smartest <span className="bg-gradient-to-r from-accent to-sky-200 bg-clip-text text-transparent">business partner.</span></h1>
          <p className="mt-4 text-lg text-sky-100/85 leading-relaxed">Sales insights, udhaar reminders, stock alerts and marketing, all from the Paytm payments you already receive.</p>
          <ul className="mt-10 space-y-5">{FEATURES.map(([ic, h, d]) => (
            <li key={h} className="flex items-start gap-4"><span className="icon-tile bg-white/10 ring-1 ring-white/15 text-accent"><Icon name={ic} /></span><div><p className="font-bold">{h}</p><p className="text-sm text-sky-100/75 mt-0.5">{d}</p></div></li>))}</ul>
        </div>
        <p className="hidden lg:block text-xs text-sky-200/60">Your data stays yours. Consent-first, approval before every action.</p>
      </section>
      <section className="flex items-start lg:items-center justify-center px-4 py-8 sm:py-12 -mt-6 lg:mt-0">
      <div className="w-full max-w-md">
        <div className="card p-6 sm:p-8 shadow-[var(--shadow-lift)]">
          {step === "phone" ? (
            <form onSubmit={sendOtp} className="space-y-4">
              <div><h2 className="font-extrabold text-2xl tracking-tight">Welcome</h2><p className="font-semibold text-ink mt-1">Sign in or create your account</p><p className="text-sm text-muted mt-1">Use the mobile number linked to your Paytm business.</p></div>
              <label className="block text-sm font-medium">Mobile number
                <div className="mt-1.5 flex rounded-2xl border border-line bg-surface/60 focus-within:border-primary focus-within:bg-white focus-within:shadow-[0_0_0_4px_rgba(10,108,223,.12)] overflow-hidden transition">
                  <span className="px-4 grid place-items-center text-sm font-bold text-ink border-r border-line">+91</span>
                  <input className="flex-1 min-w-0 bg-transparent px-4 py-3.5 outline-none focus-visible:outline-none text-[16px] tracking-wide" inputMode="numeric" autoComplete="tel-national" autoFocus maxLength={14} placeholder="98765 43210" value={phone} onChange={(e) => setPhone(e.target.value)} />
                </div>
              </label>
              {err && <p className="text-sm text-red-600" role="alert">{err}</p>}
              <button className="btn btn-primary w-full !min-h-12 text-[15px]" disabled={busy || phone.replace(/\D/g, "").length < 10}>{busy ? "Sending…" : "Send OTP"}</button>
              <p className="text-[11px] text-muted text-center">New here? We’ll set up your account in under a minute.</p>
            </form>
          ) : (
            <form onSubmit={verify} className="space-y-4">
              <div><h2 className="font-extrabold text-2xl tracking-tight">Enter the 6-digit code</h2><p className="text-sm text-muted mt-1">Sent to +91 {phone.replace(/\D/g, "").slice(-10)}. <button type="button" className="text-brand underline" onClick={() => { setStep("phone"); setErr(null); }}>Change</button></p></div>
              {devOtp && <div className="rounded-2xl bg-amber-50 border border-amber-200 p-3.5 text-sm"><b>Prototype mode:</b> no SMS is sent. Your code is <b className="tracking-widest text-base">{devOtp}</b></div>}
              <input className="input w-full !rounded-2xl !py-4 text-center text-2xl font-bold tracking-[0.5em] tabular-nums" inputMode="numeric" autoComplete="one-time-code" autoFocus maxLength={6} value={otp} onChange={(e) => setOtp(e.target.value.replace(/\D/g, ""))} aria-label="One-time code" />
              {err && <p className="text-sm text-red-600" role="alert">{err}</p>}
              <button className="btn btn-primary w-full !min-h-12 text-[15px]" disabled={busy || otp.length !== 6}>{busy ? "Checking…" : "Verify & continue"}</button>
              <button type="button" className="w-full text-sm text-muted disabled:opacity-60" disabled={cool > 0 || busy} onClick={() => sendOtp()}>{cool > 0 ? `Resend code in ${cool}s` : "Resend code"}</button>
            </form>
          )}
        </div>
        {demos.length > 0 && (
          <div className="mt-5 card p-5">
            <p className="text-xs font-bold text-muted uppercase tracking-wider mb-3 flex items-center gap-2"><Icon name="store" size={16} />Just exploring? Open a demo shop</p>
            <div className="flex flex-wrap gap-2">{demos.map((d) => <button key={d.id} className="btn btn-ghost !min-h-9 !py-1.5 hover:!border-primary/40 hover:!text-primary" onClick={() => { setDemo(d.id); onDone(); }}>{d.name}</button>)}</div>
          </div>
        )}
      </div>
      </section>
    </div>
  );
}
