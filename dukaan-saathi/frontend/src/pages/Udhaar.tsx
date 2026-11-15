import { useT } from "../i18n";
import { FormEvent, Fragment, useState } from "react";
import { api, ApiError, inr } from "../api";
import { useApi } from "../hooks";
import ActionCard from "../components/ActionCard";
import { Badge, Card, Empty, Gate, Stat, TileIcon, Title } from "../components/ui";
import { Icon } from "../components/icons";

type Kind = "credit" | "payment";
const tail = (phone: string) => { const d = (phone || "").replace(/\D/g, ""); return d ? `…${d.slice(-4)}` : ""; };

/** Amount box that opens inside a customer's row: give udhaar or record a payment for exactly this person. */
function RowEntry({ c, kind, onDone, onCancel }: { c: any; kind: Kind; onDone: (msg: string) => void; onCancel: () => void }) {
  const [amount, setAmount] = useState(kind === "payment" ? String(c.outstanding) : "");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const save = async (e: FormEvent) => {
    e.preventDefault();
    const n = Number(amount);
    if (!(n > 0)) { setErr("Enter an amount."); return; }
    if (kind === "payment" && n > c.outstanding + 0.5) { setErr(`${c.name} only owes ${inr(c.outstanding)}.`); return; }
    setBusy(true); setErr("");
    try {
      const r = await api(kind === "credit" ? "/udhaar/credit" : "/udhaar/payment", { method: "POST", body: { customer_id: c.customer_id, amount: n, ...(kind === "credit" ? { note } : {}) } });
      onDone(kind === "credit" ? `Noted ${inr(r.added)} for ${r.customer}. Total due ${inr(r.balance)}.` : `Received ${inr(r.received)} from ${r.customer}. Remaining ${inr(r.balance)}.`);
    } catch (x) {
      const d = (x as ApiError).detail || {};
      setErr(d.error === "exceeds_balance" ? `${d.customer} only owes ${inr(d.balance)}.` : d.error === "nothing_due" ? "Nothing is pending." : "Couldn’t save. Try again.");
    } finally { setBusy(false); }
  };
  return (
    <form onSubmit={save} className="flex flex-wrap items-center gap-2 bg-surface rounded-xl p-3">
      <span className="text-sm font-medium">{kind === "credit" ? `Give udhaar to ${c.name}` : `Payment from ${c.name}`}</span>
      <input autoFocus className="input text-sm w-32" type="number" min="1" max="10000000" step="any" placeholder="Amount ₹" value={amount} onChange={(e) => setAmount(e.target.value)} aria-label="Amount" />
      {kind === "credit" && <input className="input text-sm flex-1 min-w-[140px]" placeholder="What for? (optional)" value={note} maxLength={200} onChange={(e) => setNote(e.target.value)} aria-label="Note" />}
      {kind === "payment" && <button type="button" className="text-xs underline text-muted" onClick={() => setAmount(String(c.outstanding))}>Full {inr(c.outstanding)}</button>}
      <button className="btn btn-primary !py-1.5" disabled={busy}>{busy ? "…" : "Save"}</button>
      <button type="button" className="btn btn-ghost !py-1.5" onClick={onCancel}>Cancel</button>
      {err && <span className="text-xs text-red-600 w-full">{err}</span>}
    </form>);
}

export default function Udhaar({ go }: { go: (t: string) => void }) {
  const t = useT();
  const d = useApi<any>("/udhaar");
  const [proposals, setProposals] = useState<any[]>([]);
  const [msg, setMsg] = useState<{ ok: boolean; t: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState<{ id: number; kind: Kind } | null>(null);
  const [f, setF] = useState({ customer: "", amount: "", kind: "credit" as Kind });
  const [choices, setChoices] = useState<any[]>([]);      // same-name customers to pick from
  const [canCreate, setCanCreate] = useState(false);       // name not found: offer to add them

  const errText = (e: ApiError) => {
    const x = e.detail || {};
    switch (x.error) {
      case "ambiguous_customer": return "More than one customer has that name. Pick the right one:";
      case "customer_not_found": return `No customer named “${f.customer}”.`;
      case "exceeds_balance": return `${x.customer} only owes ${inr(x.balance)}.`;
      case "nothing_due": return "Nothing is pending for this customer.";
      default: return "Couldn’t save that. Check the amount and try again.";
    }
  };
  const save = async (extra: Record<string, unknown> = {}) => {
    setBusy(true); setMsg(null); setChoices([]); setCanCreate(false);
    try {
      const r = await api(f.kind === "credit" ? "/udhaar/credit" : "/udhaar/payment", { method: "POST", body: { customer: f.customer, amount: Number(f.amount), ...extra } });
      setMsg({ ok: true, t: f.kind === "credit" ? `Noted ${inr(r.added)} for ${r.customer}. Total due ${inr(r.balance)}.` : `Received ${inr(r.received)} from ${r.customer}. Remaining ${inr(r.balance)}.` });
      setF({ ...f, customer: "", amount: "" }); d.reload();
    } catch (er) {
      const x = (er as ApiError).detail || {};
      setMsg({ ok: false, t: errText(er as ApiError) });
      if (x.error === "ambiguous_customer") setChoices(x.candidates || []);
      if (x.error === "customer_not_found" && f.kind === "credit") setCanCreate(true);
    } finally { setBusy(false); }
  };
  const submit = (e: FormEvent) => { e.preventDefault(); save(); };
  const remind = async (customer_id?: number) => {
    setBusy(true); setMsg(null);
    try { const r = await api("/udhaar/remind", { method: "POST", body: customer_id ? { customer_id } : {} }); setProposals(r.proposals); if (!r.proposals.length) setMsg({ ok: false, t: "No reminders to send right now." }); }
    catch (er) { setMsg({ ok: false, t: errText(er as ApiError) }); } finally { setBusy(false); }
  };

  return (
    <Gate state={d} goPrivacy={() => go("privacy")}>
      {(u) => {
        const names: Record<string, number> = {};
        u.customers.forEach((c: any) => { names[c.name.toLowerCase()] = (names[c.name.toLowerCase()] || 0) + 1; });
        return (
          <div className="space-y-5">
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
              <Stat tint="blue" icon={<TileIcon kind="udhaar" />} label={t("Total udhaar")} value={inr(u.total_outstanding)} sub={`${u.count} customers`} />
              <Stat tint="pink" icon={<TileIcon kind="alert" />} label={t("Overdue")} value={inr(u.total_overdue)} tone={u.total_overdue ? "down" : undefined} sub={t("past due date")} />
              <Stat tint="green" icon={<TileIcon kind="calendar" />} label={t("0–30 days")} value={inr(u.aging["0-30"])} />
              <Stat tint="amber" icon={<TileIcon kind="clock" />} label={t("31+ days")} value={inr(u.aging["31-60"] + u.aging["60+"])} tone={u.aging["31-60"] + u.aging["60+"] ? "down" : undefined} sub={t("older dues")} />
            </div>
            {msg && <p className={`text-sm font-medium ${msg.ok ? "text-emerald-600" : "text-red-600"}`} role="status">{msg.t}</p>}
            {proposals.length > 0 && <div className="grid md:grid-cols-2 gap-3">{proposals.map((a) => <ActionCard key={a.id} action={a} onDone={() => setProposals((p) => p.filter((x) => x.id !== a.id))} />)}</div>}

            <Card className="!p-0 overflow-hidden">
              <div className="flex items-center justify-between gap-3 flex-wrap p-4"><Title sub={t("Payments are applied to the oldest udhaar first")}>{t("Who owes you")}</Title><button className="btn btn-primary" disabled={busy || !u.count} onClick={() => remind()}>{t("Draft reminders for overdue")}</button></div>
              {u.customers.length === 0 ? <Empty icon="check-circle" text="No udhaar pending." /> : (
                <div className="overflow-x-auto"><table className="w-full text-sm">
                  <thead className="bg-surface text-xs text-muted"><tr><th className="text-left p-3">{t("Customer")}</th><th className="text-right p-3">{t("Owes")}</th><th className="text-right p-3">{t("Overdue")}</th><th className="text-right p-3">{t("Oldest")}</th><th className="p-3 text-right">Update</th></tr></thead>
                  <tbody>{u.customers.map((c: any) => (<Fragment key={c.customer_id}>
                    <tr className="border-t border-line">
                      <td className="p-3 font-medium"><span translate="no">{c.name}</span>
                        {(names[c.name.toLowerCase()] > 1 || c.phone) && <span className="ml-1.5 text-xs text-muted font-normal" translate="no">{tail(c.phone) || `#${c.customer_id}`}</span>}
                        {c.do_not_contact && <span className="ml-1.5"><Badge>no contact</Badge></span>}</td>
                      <td className="p-3 text-right font-semibold">{inr(c.outstanding)}</td>
                      <td className="p-3 text-right">{c.overdue ? <span className="text-red-600 font-medium">{inr(c.overdue)}</span> : "—"}</td>
                      <td className="p-3 text-right text-muted">{c.oldest_days}d</td>
                      <td className="p-3">
                        <div className="flex justify-end gap-1.5 flex-wrap">
                          <button className="btn btn-ghost !py-1 !px-2.5 text-xs" onClick={() => setOpen({ id: c.customer_id, kind: "credit" })}>+ Udhaar</button>
                          <button className="btn btn-ghost !py-1 !px-2.5 text-xs text-emerald-700" onClick={() => setOpen({ id: c.customer_id, kind: "payment" })}>Received</button>
                          <button className="btn btn-ghost !py-1 !px-2.5 text-xs" disabled={busy || c.do_not_contact} onClick={() => remind(c.customer_id)}>{t("Remind")}</button>
                        </div>
                      </td>
                    </tr>
                    {open?.id === c.customer_id && (
                      <tr><td colSpan={5} className="px-3 pb-3">
                        <RowEntry c={c} kind={open!.kind} onCancel={() => setOpen(null)} onDone={(m) => { setOpen(null); setMsg({ ok: true, t: m }); d.reload(); }} />
                      </td></tr>)}
                  </Fragment>))}</tbody></table></div>)}
            </Card>

            <Card>
              <Title sub={t("Quick entry — or just tell Saathi by voice")}>{t("Update the book")}</Title>
              <form className="flex flex-wrap gap-2" onSubmit={submit}>
                <select className="input text-sm" value={f.kind} onChange={(e) => { setF({ ...f, kind: e.target.value as Kind }); setChoices([]); setCanCreate(false); }} aria-label="Type"><option value="credit">Gave udhaar</option><option value="payment">Received payment</option></select>
                <input className="input text-sm flex-1 min-w-[160px]" placeholder="Customer name" value={f.customer} onChange={(e) => { setF({ ...f, customer: e.target.value }); setChoices([]); setCanCreate(false); }} required maxLength={80} aria-label={t("Customer")} />
                <input className="input text-sm w-32" type="number" min="1" max="10000000" step="any" placeholder="Amount ₹" value={f.amount} onChange={(e) => setF({ ...f, amount: e.target.value })} required aria-label="Amount" />
                <button className="btn btn-primary" disabled={busy}>{t("Save")}</button>
              </form>
              {choices.length > 0 && (
                <div className="flex flex-wrap gap-2 mt-3">{choices.map((c) => (
                  <button key={c.id} className="btn btn-ghost !py-1.5 text-sm" disabled={busy} onClick={() => save({ customer_id: c.id })} translate="no">
                    {c.label} · owes {inr(c.balance)}
                  </button>))}</div>)}
              {canCreate && (
                <button className="btn btn-ghost mt-3 text-sm" disabled={busy} onClick={() => save({ create_if_missing: true })}>Add “{f.customer}” as a new customer and save</button>)}
              <p className="text-xs text-muted mt-2">Tip: use the buttons in each row above to update one customer directly. Add phone numbers in <button className="underline" onClick={() => go("customers")}>Customers</button> so reminders can reach them.</p>
            </Card>
          </div>);
      }}
    </Gate>
  );
}
