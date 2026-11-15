import { useEffect, useState } from "react";
import { api, ApiError } from "../api";
import { LANGUAGES } from "../languages";
import { setUiLanguage } from "../translator";
import { Icon, Logo } from "../components/icons";

const SEGMENTS: [string, string, string][] = [["kirana", "Kirana / grocery", "cart"], ["sweets", "Sweets & bakery", "cake"], ["salon", "Salon / services", "scissors"], ["pharmacy", "Pharmacy", "pill"], ["restaurant", "Restaurant / café", "utensils"], ["other", "Other", "store"]];
const LANGS: [string, string, string][] = LANGUAGES.map(([code, native, , example]) => [code, native, example]);
const CONSENTS: [string, string, string][] = [
  ["transactions", "Payments & settlements", "Sales insights, best sellers, stock estimates, GST, settlement alerts. This is the core of Dukaan Saathi."],
  ["ledger", "Udhaar book", "Track who owes you and draft polite reminders."],
  ["customers", "Customer visits", "Spot regulars who stopped coming and draft win-back offers."],
  ["credit", "Cash-flow analysis", "Warn about cash gaps and suggest credit only when needed."],
  ["messaging", "Sending messages for me", "WhatsApp/SMS to suppliers and customers. Nothing is ever sent without your approval."],
];
const GSTIN = /^\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]$/;

export default function Onboarding({ onDone, onLogout }: { onDone: () => void; onLogout: () => void }) {
  const [step, setStep] = useState(0);
  const [f, setF] = useState({ business_name: "", owner_name: "", segment: "kirana", city: "", gst_registered: false, gst_number: "", soundbox_id: "", language: "hinglish", sample_data: false });
  const [consents, setConsents] = useState<Record<string, boolean>>(Object.fromEntries(CONSENTS.map(([k]) => [k, true])));
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const set = (k: string, v: any) => setF((p) => ({ ...p, [k]: v }));
  useEffect(() => { setUiLanguage(f.language); }, [f.language]); // the wizard switches language as soon as one is picked

  const gst = f.gst_number.trim().toUpperCase();
  const problems: string[] = [];
  if (f.business_name.trim().length < 2) problems.push("Enter your shop name.");
  if (f.owner_name.trim().length < 2) problems.push("Enter the owner’s name.");
  if (f.city.trim().length < 2) problems.push("Enter your city.");
  if (f.gst_registered && gst && !GSTIN.test(gst)) problems.push("That GSTIN doesn’t look right (15 characters, e.g. 27ABCDE1234F1Z5).");
  if (/[<>]/.test(f.business_name + f.owner_name + f.city)) problems.push("Names can’t contain < or >.");

  const submit = async () => {
    setBusy(true); setErr(null);
    try {
      await api("/onboarding", { method: "POST", body: { ...f, business_name: f.business_name.trim(), owner_name: f.owner_name.trim(), city: f.city.trim(), gst_number: f.gst_registered && gst ? gst : null, soundbox_id: f.soundbox_id.trim() || null, consents } });
      onDone();
    } catch (e) {
      const x = e as ApiError;
      setErr(x.code === "already_onboarded" ? "Your account is already set up." : x.status === 422 ? "Please check the details you entered." : x.status === 0 ? x.message : "Couldn’t finish setup. Please try again.");
      if (x.code === "already_onboarded") onDone();
    } finally { setBusy(false); }
  };

  const inp = "input mt-1.5 w-full text-[15px] font-normal";
  return (
    <div className="min-h-full py-8 px-4">
      <div className="mx-auto max-w-2xl">
        <div className="flex items-center justify-between mb-5">
          <p className="flex items-center gap-3 font-extrabold text-lg text-brand" translate="no"><Logo size={36} />Dukaan <span className="text-primary -ml-2">Saathi</span></p>
          <button className="btn btn-ghost !min-h-9" onClick={onLogout}><Icon name="logout" size={16} />Sign out</button>
        </div>
        <div className="flex gap-2 mb-2" aria-label={`Step ${step + 1} of 3`}>{[0, 1, 2].map((i) => <div key={i} className="h-1.5 flex-1 rounded-full bg-line overflow-hidden"><div className={`h-full rounded-full bg-gradient-to-r from-accent to-primary transition-all duration-500 ${i <= step ? "w-full" : "w-0"}`} /></div>)}</div>
        <p className="text-xs font-bold text-muted mb-5">Step {step + 1} of 3</p>

        <div className="card p-6 sm:p-8 space-y-6 shadow-[var(--shadow-lift)]">
          {step === 0 && (<>
            <div><h1 className="text-2xl font-extrabold tracking-tight">Tell us about your shop</h1><p className="text-sm text-muted mt-1">So Saathi can give advice that fits your business.</p></div>
            <label className="block text-sm font-medium">Shop name<input className={inp} value={f.business_name} maxLength={120} onChange={(e) => set("business_name", e.target.value)} placeholder="e.g. Verma General Store" autoFocus /></label>
            <label className="block text-sm font-medium">Owner’s name<input className={inp} value={f.owner_name} maxLength={80} onChange={(e) => set("owner_name", e.target.value)} placeholder="e.g. Sunil Verma" /></label>
            <div><p className="text-sm font-medium mb-1">What kind of business?</p>
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">{SEGMENTS.map(([v, l, i]) => (
                <button type="button" key={v} aria-pressed={f.segment === v} onClick={() => set("segment", v)} className={`rounded-2xl border p-3.5 text-left text-sm font-semibold transition-all ${f.segment === v ? "border-primary bg-sky-50 ring-2 ring-primary/20" : "border-line bg-white hover:border-sky-200"}`}><span className={`icon-tile !h-9 !w-9 !rounded-xl mb-2 ${f.segment === v ? "bg-primary text-white" : "bg-surface text-brand"}`}><Icon name={i} size={18} /></span>{l}</button>))}</div></div>
            <label className="block text-sm font-medium">City<input className={inp} value={f.city} maxLength={60} onChange={(e) => set("city", e.target.value)} placeholder="e.g. Nagpur" /></label>
            <div className="rounded-xl border border-line p-3.5">
              <label className="flex items-center gap-3 text-sm font-medium cursor-pointer"><input type="checkbox" className="h-4 w-4" checked={f.gst_registered} onChange={(e) => set("gst_registered", e.target.checked)} />My business is GST registered</label>
              {f.gst_registered && <label className="block text-sm font-medium mt-3">GSTIN <span className="text-muted font-normal">(optional)</span><input className={inp + " uppercase tracking-wide"} value={f.gst_number} maxLength={15} onChange={(e) => set("gst_number", e.target.value)} placeholder="27ABCDE1234F1Z5" /></label>}
            </div>
            <label className="block text-sm font-medium">Soundbox ID <span className="text-muted font-normal">(optional)</span><input className={inp} value={f.soundbox_id} maxLength={30} onChange={(e) => set("soundbox_id", e.target.value)} placeholder="Printed on the back of the device" /></label>
            {problems.length > 0 && (f.business_name || f.owner_name || f.city || gst) && <ul className="text-sm text-red-600 list-disc pl-5">{problems.map((p) => <li key={p}>{p}</li>)}</ul>}
          </>)}

          {step === 1 && (<>
            <div><h1 className="text-2xl font-extrabold tracking-tight">Language & your privacy</h1><p className="text-sm text-muted mt-1">You choose what Saathi can read. You can change any of this later in Privacy.</p></div>
            <div><p className="text-sm font-medium mb-1">Preferred language</p>
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-2" translate="no">{LANGS.map(([v, l, ex]) => <button type="button" key={v} aria-pressed={f.language === v} onClick={() => set("language", v)} className={`rounded-2xl border p-3.5 text-left transition-all ${f.language === v ? "border-primary bg-sky-50 ring-2 ring-primary/20" : "border-line hover:border-sky-200"}`}><b className="text-sm">{l}</b><p className="text-xs text-muted mt-1">{ex}</p></button>)}</div></div>
            <div className="divide-y divide-line rounded-xl border border-line">{CONSENTS.map(([k, l, d]) => (
              <div key={k} className="flex items-start justify-between gap-4 p-3.5"><div><p className="text-sm font-medium">{l}{k === "transactions" && <span className="ml-2 text-[11px] rounded-full bg-emerald-50 text-emerald-700 border border-emerald-200 px-1.5 py-0.5">Recommended</span>}</p><p className="text-xs text-muted mt-0.5">{d}</p></div>
                <button type="button" role="switch" aria-checked={consents[k]} aria-label={l} onClick={() => setConsents((c) => ({ ...c, [k]: !c[k] }))} className={`relative mt-0.5 h-6 w-11 shrink-0 rounded-full transition-colors ${consents[k] ? "bg-emerald-500" : "bg-slate-300"}`}><span className={`absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition-all ${consents[k] ? "left-[22px]" : "left-0.5"}`} /></button></div>))}</div>
            <p className="text-xs text-muted">Money never moves and no message is sent without your approval. Everything Saathi does is recorded in your activity log.</p>
          </>)}

          {step === 2 && (<>
            <div><h1 className="text-2xl font-extrabold tracking-tight">How would you like to start?</h1><p className="text-sm text-muted mt-1">Real payments appear as customers pay through Paytm.</p></div>
            <div className="grid sm:grid-cols-2 gap-3">
              <button type="button" aria-pressed={f.sample_data} onClick={() => set("sample_data", true)} className={`rounded-2xl border p-5 text-left transition-all ${f.sample_data ? "border-primary bg-sky-50 ring-2 ring-primary/20" : "border-line hover:border-sky-200"}`}><span className="icon-tile bg-gradient-to-br from-accent to-primary text-white"><Icon name="sparkles" /></span><p className="font-bold mt-3">Explore with sample data</p><p className="text-xs text-muted mt-1">A month of simulated payments, stock and udhaar so you can try every feature. Remove it any time.</p></button>
              <button type="button" aria-pressed={!f.sample_data} onClick={() => set("sample_data", false)} className={`rounded-2xl border p-5 text-left transition-all ${!f.sample_data ? "border-primary bg-sky-50 ring-2 ring-primary/20" : "border-line hover:border-sky-200"}`}><span className="icon-tile bg-emerald-50 text-emerald-600"><Icon name="leaf" /></span><p className="font-bold mt-3">Start fresh</p><p className="text-xs text-muted mt-1">Begin empty. You’ll add your items and suppliers, and insights build up from your real payments.</p></button>
            </div>
            <div className="rounded-xl bg-surface p-3.5 text-sm"><b>Summary</b><p className="text-muted mt-1">{f.business_name} · {f.owner_name} · {SEGMENTS.find((s) => s[0] === f.segment)?.[1]} · {f.city}<br />Language: {LANGS.find((l) => l[0] === f.language)?.[1]} · {Object.values(consents).filter(Boolean).length} of {CONSENTS.length} permissions on</p></div>
            {err && <p className="text-sm text-red-600" role="alert">{err}</p>}
          </>)}

          <div className="flex justify-between pt-1">
            <button className="btn btn-ghost" disabled={step === 0 || busy} onClick={() => setStep(step - 1)}>Back</button>
            {step < 2 ? <button className="btn btn-primary" disabled={(step === 0 && problems.length > 0) || (step === 0 && (!f.business_name || !f.owner_name || !f.city))} onClick={() => setStep(step + 1)}>Continue</button>
              : <button className="btn btn-primary" disabled={busy} onClick={submit}>{busy ? "Setting up…" : "Finish setup"}</button>}
          </div>
        </div>
      </div>
    </div>
  );
}
