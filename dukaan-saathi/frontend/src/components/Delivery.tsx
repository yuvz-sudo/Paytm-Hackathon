import { useState } from "react";
import { api } from "../api";

/** One approved message and how it actually reaches the person: the merchant's own WhatsApp (one tap), SMS, or copy. */
export function DeliveryRow({ d, onChange, go }: { d: any; onChange?: (d: any) => void; go?: (t: string) => void }) {
  const [state, setState] = useState(d.status);
  const [copied, setCopied] = useState(false);
  const mark = async (status: string) => {
    setState(status);
    try { const r = await api(`/outbox/${d.id}/mark`, { method: "POST", body: { status } }); onChange?.(r); } catch { /* the link still opened */ }
  };
  const copy = async () => {
    try { await navigator.clipboard.writeText(d.body); setCopied(true); setTimeout(() => setCopied(false), 1500); } catch { /* ignore */ }
  };
  return (
    <div className="rounded-xl border border-line p-3 bg-white">
      <div className="flex items-center justify-between gap-2 text-xs">
        <span>To <b className="text-ink" translate="no">{d.to}</b>{d.phone && <span className="text-muted" translate="no"> · {d.phone}</span>}</span>
        <span className={`rounded-full px-2 py-0.5 font-semibold ${state === "sent" ? "bg-emerald-50 text-emerald-700" : state === "skipped" ? "bg-slate-100 text-slate-500" : "bg-amber-50 text-amber-800"}`}>
          {state === "sent" ? "Sent" : state === "skipped" ? "Skipped" : "Ready to send"}
        </span>
      </div>
      <pre className="whitespace-pre-wrap font-sans text-[13px] mt-1.5 text-ink">{d.body}</pre>
      <div className="flex flex-wrap items-center gap-2 mt-2">
        {d.whatsapp_url && (
          <a href={d.whatsapp_url} target="_blank" rel="noopener noreferrer" onClick={() => mark("sent")}
            className="btn !py-1.5 text-xs text-white bg-[#25D366] hover:bg-[#1ebe5b]">{state === "sent" ? "Open WhatsApp again" : "Open in WhatsApp"}</a>)}
        {d.sms_url && <a href={d.sms_url} onClick={() => mark("sent")} className="btn btn-ghost !py-1.5 text-xs">SMS</a>}
        {d.needs_number && (
          <span className="text-xs text-amber-800">No mobile number saved.{go && <> <button className="underline font-semibold" onClick={() => go("customers")}>Add it in Customers</button></>}</span>)}
        <button className="btn btn-ghost !py-1.5 text-xs" onClick={copy}>{copied ? "Copied" : "Copy text"}</button>
        {state !== "sent" && <button className="text-xs text-muted underline" onClick={() => mark("sent")}>Mark as sent</button>}
        {state === "ready" && <button className="text-xs text-muted underline" onClick={() => mark("skipped")}>Skip</button>}
      </div>
    </div>);
}

export const DELIVERY_NOTE = "Approved messages are sent from your own WhatsApp: tap “Open in WhatsApp”, check the text, press send.";
