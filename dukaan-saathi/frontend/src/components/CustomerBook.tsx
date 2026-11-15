import { FormEvent, useState } from "react";
import { api, ApiError, inr } from "../api";
import { useApi } from "../hooks";
import { Badge, Card, Empty, Title } from "./ui";

const PHONE = /^(?:\+?91[\s-]?|0)?[6-9]\d{9}$/;
const clean = (p: string) => p.replace(/[\s-]/g, "");

function errText(e: ApiError): string {
  const d = e.detail || {};
  switch (d.error) {
    case "invalid_phone": return "Enter a 10-digit Indian mobile number.";
    case "phone_exists": return `That number already belongs to ${d.customer}.`;
    case "has_udhaar": return `They still owe ${inr(d.balance)}. Settle the udhaar first.`;
    case "has_history": return "They have past payments or udhaar, so they stay in your books. Mark them “do not contact” instead.";
    case "invalid_name": return "Names can’t contain < or >.";
    case "consent_off": return "Turn on Customers access in Privacy to manage customers.";
    default: return e.status === 0 ? e.message : "Couldn’t save. Please try again.";
  }
}

function Row({ c, onChanged }: { c: any; onChanged: (msg: string) => void }) {
  const [edit, setEdit] = useState(false);
  const [f, setF] = useState({ name: c.name, phone: c.phone || "", do_not_contact: c.do_not_contact });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const save = async (e: FormEvent) => {
    e.preventDefault();
    if (f.phone && !PHONE.test(clean(f.phone))) { setErr("Enter a 10-digit Indian mobile number."); return; }
    setBusy(true); setErr("");
    try { await api(`/customers/${c.id}`, { method: "PUT", body: f }); setEdit(false); onChanged(`Saved ${f.name}.`); }
    catch (x) { setErr(errText(x as ApiError)); } finally { setBusy(false); }
  };
  const remove = async () => {
    setBusy(true); setErr("");
    try { await api(`/customers/${c.id}`, { method: "DELETE" }); onChanged(`Removed ${c.name}.`); }
    catch (x) { setErr(errText(x as ApiError)); } finally { setBusy(false); }
  };
  if (edit) return (
    <li className="py-3">
      <form onSubmit={save} className="flex flex-wrap items-center gap-2">
        <input className="input text-sm flex-1 min-w-[140px]" value={f.name} maxLength={80} required onChange={(e) => setF({ ...f, name: e.target.value })} aria-label="Name" />
        <input className="input text-sm w-44" value={f.phone} maxLength={20} inputMode="tel" placeholder="Mobile number" onChange={(e) => setF({ ...f, phone: e.target.value })} aria-label="Mobile number" />
        <label className="text-xs flex items-center gap-1.5"><input type="checkbox" checked={f.do_not_contact} onChange={(e) => setF({ ...f, do_not_contact: e.target.checked })} /> Do not contact</label>
        <button className="btn btn-primary !py-1.5" disabled={busy}>Save</button>
        <button type="button" className="btn btn-ghost !py-1.5" onClick={() => { setEdit(false); setErr(""); }}>Cancel</button>
      </form>
      {err && <p className="text-xs text-red-600 mt-1">{err}</p>}
    </li>);
  return (
    <li className="py-3">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="min-w-0">
          <p className="text-sm font-semibold" translate="no">{c.name} {c.do_not_contact && <Badge>no contact</Badge>}</p>
          <p className="text-xs text-muted mt-0.5" translate="no">{c.phone || <span className="text-amber-700">No number yet: add one so reminders and offers can reach them</span>}</p>
        </div>
        <div className="flex items-center gap-3 text-xs">
          {c.balance > 0 && <span className="font-semibold text-red-600">owes {inr(c.balance)}</span>}
          <span className="text-muted">{c.visits_90d} visits · 90 days</span>
          <button className="btn btn-ghost !py-1 !px-2.5" onClick={() => setEdit(true)}>Edit</button>
          <button className="btn btn-danger !py-1 !px-2.5" disabled={busy} onClick={remove}>Remove</button>
        </div>
      </div>
      {err && <p className="text-xs text-red-600 mt-1">{err}</p>}
    </li>);
}

/** Add customers with their mobile numbers, find, edit and remove them. */
export default function CustomerBook() {
  const [q, setQ] = useState("");
  const d = useApi<any>(`/customers/all?q=${encodeURIComponent(q)}`, [q]);
  const [f, setF] = useState({ name: "", phone: "" });
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; t: string } | null>(null);
  const [showAll, setShowAll] = useState(false);

  const add = async (e: FormEvent) => {
    e.preventDefault();
    if (f.phone && !PHONE.test(clean(f.phone))) { setMsg({ ok: false, t: "Enter a 10-digit Indian mobile number." }); return; }
    setBusy(true); setMsg(null);
    try {
      const r = await api("/customers", { method: "POST", body: { name: f.name.trim(), phone: f.phone.trim() } });
      setMsg({ ok: true, t: `Added ${r.name}${r.phone ? ` (${r.phone})` : ""}.${r.same_name_count ? ` Note: you have ${r.same_name_count} other customer(s) with this name; the number tells them apart.` : ""}` });
      setF({ name: "", phone: "" }); d.reload();
    } catch (x) { setMsg({ ok: false, t: errText(x as ApiError) }); } finally { setBusy(false); }
  };
  const list: any[] = d.data?.customers || [];
  const shown = showAll ? list : list.slice(0, 8);

  return (
    <Card>
      <Title sub="Save customers with their mobile number so udhaar reminders and offers reach the right person.">Your customers</Title>
      <form onSubmit={add} className="flex flex-wrap gap-2">
        <input className="input text-sm flex-1 min-w-[160px]" placeholder="Customer name" value={f.name} maxLength={80} required onChange={(e) => setF({ ...f, name: e.target.value })} aria-label="Customer name" />
        <input className="input text-sm w-48" placeholder="Mobile number (optional)" inputMode="tel" value={f.phone} maxLength={20} onChange={(e) => setF({ ...f, phone: e.target.value })} aria-label="Mobile number" />
        <button className="btn btn-primary" disabled={busy}>{busy ? "Adding…" : "+ Add customer"}</button>
      </form>
      {msg && <p className={`text-sm mt-2 ${msg.ok ? "text-emerald-700" : "text-red-600"}`} role="status">{msg.t}</p>}
      <div className="mt-4 flex items-center gap-2">
        <input className="input text-sm flex-1" placeholder="Search by name or number" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search customers" />
        <span className="text-xs text-muted whitespace-nowrap">{d.data ? `${d.data.count} customers` : ""}</span>
      </div>
      {d.error ? <p className="text-sm text-red-600 mt-3">{errText(d.error)}</p> : !d.data ? <p className="text-sm text-muted mt-3">Loading…</p> : list.length === 0 ? <Empty text={q ? "No customer matches that." : "No customers yet. Add your regulars above."} /> : (
        <>
          <ul className="divide-y divide-line mt-2">{shown.map((c) => <Row key={c.id} c={c} onChanged={(m) => { setMsg({ ok: true, t: m }); d.reload(); }} />)}</ul>
          {list.length > 8 && <button className="text-xs text-cyan font-semibold mt-2" onClick={() => setShowAll((v) => !v)}>{showAll ? "Show fewer" : `Show all ${list.length}`}</button>}
        </>)}
    </Card>);
}
