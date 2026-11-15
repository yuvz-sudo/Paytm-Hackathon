import { useT } from "../i18n";
import { FormEvent, Fragment, useState } from "react";
import { api, ApiError, inr } from "../api";
import { useApi } from "../hooks";
import ActionCard from "../components/ActionCard";
import { ItemForm, RemoveItem } from "../components/ItemEditor";
import { Badge, Card, Empty, Gate, Title } from "../components/ui";
import { Icon } from "../components/icons";

const TONE: Record<string, string> = { out: "high", critical: "high", low: "medium", unknown: "neutral", ok: "ok", no_sales: "neutral" };
const LABEL: Record<string, string> = { out: "Out", critical: "Runs out before restock", low: "Low", unknown: "Stock not reported", ok: "OK", no_sales: "No recent sales" };

export default function Stock({ go }: { go: (t: string) => void }) {
  const t = useT();
  const st = useApi<any>("/stock");
  const fest = useApi<any>("/briefing");
  const items = useApi<any[]>("/items");
  const sups = useApi<any[]>("/suppliers");
  const [editing, setEditing] = useState<number | null>(null);
  const [adding, setAdding] = useState(false);
  const changed = (m: string) => { setMsg({ ok: true, t: m }); setEditing(null); setAdding(false); st.reload(); items.reload(); };
  const [item, setItem] = useState("");
  const [qty, setQty] = useState("");
  const [mode, setMode] = useState<"set" | "add">("set");
  const [msg, setMsg] = useState<{ ok: boolean; t: string } | null>(null);
  const [proposals, setProposals] = useState<any[]>([]);
  const [busy, setBusy] = useState(false);

  const update = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true); setMsg(null);
    try {
      const r = await api("/stock/update", { method: "POST", body: { item, quantity: Number(qty), mode } });
      setMsg({ ok: true, t: `Updated: ${r.text}` }); setItem(""); setQty(""); st.reload();
    } catch (er) {
      const x = er as ApiError, d = x.detail || {};
      setMsg({ ok: false, t: d.error === "ambiguous_item" ? `Which one? ${d.candidates.join(", ")}` : d.error === "item_not_found" ? "Item not found." : d.error === "item_not_stock_tracked" ? "This item isn’t stock-tracked." : "Couldn’t update." });
    } finally { setBusy(false); }
  };
  const draft = async (items?: string[]) => {
    setBusy(true); setMsg(null);
    try { const r = await api("/stock/order", { method: "POST", body: { items } }); setProposals(r.proposals); }
    catch (er) { const d = (er as ApiError).detail || {}; setMsg({ ok: false, t: d.error === "nothing_to_order" ? "Nothing needs ordering right now." : d.error === "no_supplier_contact" ? "No supplier contact saved for these items." : "Couldn’t draft the order." }); }
    finally { setBusy(false); }
  };

  return (
    <Gate state={st} goPrivacy={() => go("privacy")}>
      {(d) => {
        const byId: Record<number, any> = Object.fromEntries((items.data || []).map((i: any) => [i.id, i]));
        const untracked = (items.data || []).filter((i: any) => !i.track_stock);
        const suppliers = sups.data || [];
        const addCard = (
          <Card>
            <Title sub="New product on your shelf? Add it with its price, opening stock and supplier." right={!adding ? <button className="btn btn-primary" onClick={() => setAdding(true)}>+ Add item</button> : undefined}>Your items</Title>
            {adding && <ItemForm suppliers={suppliers} onDone={changed} onCancel={() => setAdding(false)} />}
            {untracked.length > 0 && (
              <div className="mt-3">
                <p className="text-xs text-muted mb-1">Not stock-tracked (made to order or services)</p>
                <ul className="divide-y divide-line">{untracked.map((i: any) => (
                  <li key={i.id} className="py-2">
                    {editing === i.id ? <ItemForm item={i} suppliers={suppliers} onDone={changed} onCancel={() => setEditing(null)} /> : (
                      <div className="flex items-center justify-between gap-2 text-sm"><span>{i.name} <span className="text-muted">· {inr(i.price)}/{i.unit}</span></span>
                        <span className="flex gap-1.5"><button className="btn btn-ghost !py-1 !px-2.5 text-xs" onClick={() => setEditing(i.id)}>Edit</button><RemoveItem item={i} onDone={changed} /></span></div>)}
                  </li>))}</ul>
              </div>)}
          </Card>);
        if (!d.tracks_stock) return <div className="space-y-5"><Card><Empty icon="💇" text="No items are stock-tracked. Service businesses usually don’t need stock." /></Card>{addCard}</div>;
        const risky = d.items.filter((r: any) => ["out", "critical", "low"].includes(r.status));
        const festival = fest.data?.cards?.find((c: any) => c.id === "festival");
        return (
          <div className="space-y-5">
            {festival && <Card className="!bg-gradient-to-r !from-sky-50 !to-indigo-50 !border-sky-200"><p className="text-sm flex items-start gap-3"><span className="icon-tile !h-9 !w-9 !rounded-xl bg-white text-primary"><Icon name="gift" size={18} /></span><span><b>{festival.title}</b> — {festival.detail}</span></p></Card>}
            <div className="flex flex-wrap items-center justify-between gap-3">
              <p className="text-sm text-muted">Estimates use your last reported stock and sales since. {d.coverage_pct}% of payments have item details.</p>
              <button className="btn btn-primary" disabled={busy || risky.length === 0} onClick={() => draft()}>Draft supplier orders ({risky.length})</button>
            </div>
            {msg && <p className={`text-sm font-medium ${msg.ok ? "text-emerald-600" : "text-red-600"}`}>{msg.t}</p>}
            {proposals.length > 0 && <div className="grid md:grid-cols-2 gap-3">{proposals.map((a) => <ActionCard key={a.id} action={a} onDone={() => setProposals((p) => p.filter((x) => x.id !== a.id))} />)}</div>}

            <Card className="!p-0 overflow-hidden">
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="bg-surface text-xs text-muted"><tr><th className="text-left p-3">{t("Item")}</th><th className="text-right p-3">{t("Est. stock")}</th><th className="text-right p-3">{t("Sells / day")}</th><th className="text-right p-3">{t("Days left")}</th><th className="text-left p-3">{t("Status")}</th><th className="text-left p-3">{t("Supplier")}</th><th className="p-3" /></tr></thead>
                  <tbody>
                    {d.items.map((r: any) => (<Fragment key={r.item_id}>
                      <tr className="border-t border-line">
                        <td className="p-3 font-medium">{r.item}</td>
                        <td className="p-3 text-right">{r.current_stock ?? "—"} {r.current_stock != null && <span className="text-muted">{r.unit}</span>}</td>
                        <td className="p-3 text-right">{r.daily_pace || "—"}</td>
                        <td className="p-3 text-right font-semibold">{r.days_left ?? "—"}</td>
                        <td className="p-3"><Badge tone={TONE[r.status]}>{t(LABEL[r.status])}</Badge>{r.stale && <span className="ml-1 text-[11px] text-amber-700">· old count</span>}{r.suggested_qty && <span className="ml-1 text-[11px] text-muted">· order {r.suggested_qty} {r.unit}</span>}</td>
                        <td className="p-3 text-muted">{r.supplier?.name ?? "—"}</td>
                        <td className="p-3 text-right whitespace-nowrap">
                          {byId[r.item_id] && <span className="inline-flex gap-1.5"><button className="btn btn-ghost !py-1 !px-2.5 text-xs" onClick={() => setEditing(editing === r.item_id ? null : r.item_id)}>Edit</button><RemoveItem item={byId[r.item_id]} onDone={changed} /></span>}
                        </td>
                      </tr>
                      {editing === r.item_id && byId[r.item_id] && (
                        <tr><td colSpan={7} className="px-3 pb-3"><div className="bg-surface rounded-xl p-3">
                          <p className="text-xs text-muted mb-2">Editing {r.item}{byId[r.item_id] ? ` · now ${inr(byId[r.item_id].price)}/${byId[r.item_id].unit}` : ""}. A stock count here replaces the estimate from now on.</p>
                          <ItemForm item={byId[r.item_id]} suppliers={suppliers} onDone={changed} onCancel={() => setEditing(null)} />
                        </div></td></tr>)}
                    </Fragment>))}
                  </tbody>
                </table>
              </div>
            </Card>

            <Card>
              <Title sub={t("Counted what’s left, or new stock arrived? Tell Saathi.")}>{t("Update stock")}</Title>
              <form className="flex flex-wrap gap-2" onSubmit={update}>
                <input className="input text-sm flex-1 min-w-[160px]" placeholder="Item (e.g. atta, chini, दूध)" value={item} onChange={(e) => setItem(e.target.value)} required maxLength={80} aria-label={t("Item")} />
                <input className="input text-sm w-28" type="number" min="0" step="any" placeholder="Qty" value={qty} onChange={(e) => setQty(e.target.value)} required aria-label="Quantity" />
                <select className="input text-sm" value={mode} onChange={(e) => setMode(e.target.value as any)} aria-label="Mode"><option value="set">I counted this much</option><option value="add">New stock arrived</option></select>
                <button className="btn btn-primary" disabled={busy}>{t("Save")}</button>
              </form>
            </Card>
            {addCard}
          </div>
        );
      }}
    </Gate>
  );
}
