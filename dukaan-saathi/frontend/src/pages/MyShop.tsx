import { FormEvent, useState } from "react";
import { api, ApiError, inr } from "../api";
import { useApi } from "../hooks";
import { Badge, Card, Empty, Gate, Title } from "../components/ui";

const ERR: Record<string, string> = {
  item_exists: "You already have an item with that name.", supplier_exists: "That supplier is already added.", invalid_phone: "Enter a valid 10-digit mobile number.",
  unknown_supplier: "Pick a valid supplier.", merchant_already_has_data: "This shop already has data.",
};
const unitOptions = ["pc", "kg", "bag", "packet", "litre", "tray", "box", "dozen", "service"];

export default function MyShop({ profile, refreshProfile }: { profile: any; refreshProfile: () => void }) {
  const items = useApi<any[]>("/items");
  const sups = useApi<any[]>("/suppliers");
  const [msg, setMsg] = useState<{ ok: boolean; t: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [it, setIt] = useState({ name: "", price: "", unit: "pc", gst_rate: "0", track_stock: true, stock_qty: "", pack_qty: "1", supplier_id: "", aliases: "" });
  const [sp, setSp] = useState({ name: "", phone: "", lead_time_days: "2" });

  const fail = (e: unknown) => { const x = e as ApiError; setMsg({ ok: false, t: ERR[x.code || ""] || (x.status === 422 ? "Please check the details." : "Couldn’t save. Try again.") }); };
  const addItem = async (e: FormEvent) => {
    e.preventDefault(); setBusy(true); setMsg(null);
    try {
      await api("/items", { method: "POST", body: { name: it.name, price: Number(it.price), unit: it.unit, gst_rate: Number(it.gst_rate), track_stock: it.track_stock, stock_qty: it.track_stock && it.stock_qty !== "" ? Number(it.stock_qty) : null, pack_qty: Number(it.pack_qty) || 1, supplier_id: it.supplier_id ? Number(it.supplier_id) : null, aliases: it.aliases.split(",").map((s) => s.trim()).filter(Boolean) } });
      setIt({ ...it, name: "", price: "", stock_qty: "", aliases: "" }); setMsg({ ok: true, t: "Item added." }); items.reload();
    } catch (x) { fail(x); } finally { setBusy(false); }
  };
  const addSup = async (e: FormEvent) => {
    e.preventDefault(); setBusy(true); setMsg(null);
    try { await api("/suppliers", { method: "POST", body: { name: sp.name, phone: sp.phone, lead_time_days: Number(sp.lead_time_days) || 0, language: profile.language } }); setSp({ name: "", phone: "", lead_time_days: "2" }); setMsg({ ok: true, t: "Supplier added." }); sups.reload(); }
    catch (x) { fail(x); } finally { setBusy(false); }
  };
  const removeItem = async (id: number) => { try { await api(`/items/${id}`, { method: "DELETE" }); items.reload(); } catch (x) { fail(x); } };
  const sample = async (load: boolean) => {
    if (!load && !confirm("Remove all sample data (payments, items, customers)? Your account and settings stay.")) return;
    setBusy(true); setMsg(null);
    try { await api("/onboarding/sample-data", { method: load ? "POST" : "DELETE" }); refreshProfile(); items.reload(); sups.reload(); setMsg({ ok: true, t: load ? "Sample data loaded. Open Today to see it." : "Sample data removed." }); }
    catch (x) { fail(x); } finally { setBusy(false); }
  };
  const f = "input text-sm outline-none focus:border-accent";
  const supName = (id: number | null) => sups.data?.find((s) => s.id === id)?.name ?? "—";

  return (
    <div className="space-y-6">
      <Card>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div><p className="font-semibold">{profile.name}</p><p className="text-sm text-muted">{profile.owner} · {profile.city} · +91 {String(profile.phone || "").slice(-10)} {profile.gst_registered && <Badge tone="ok">GST {profile.gst_number || "registered"}</Badge>}</p></div>
          {profile.sample_data
            ? <button className="btn btn-danger" disabled={busy} onClick={() => sample(false)}>Remove sample data</button>
            : <button className="btn btn-ghost" disabled={busy || (items.data?.length ?? 0) > 0} title={(items.data?.length ?? 0) > 0 ? "Only available for an empty shop" : ""} onClick={() => sample(true)}>Load sample data</button>}
        </div>
      </Card>
      {msg && <p className={`text-sm font-medium ${msg.ok ? "text-emerald-600" : "text-red-600"}`} role="status">{msg.t}</p>}

      <section>
        <Title sub="Saathi uses these to track stock and best sellers">Your items</Title>
        <Gate state={items}>{(list: any[]) => (
          <Card className="!p-0 overflow-hidden">
            {list.length === 0 ? <Empty icon="📦" text="No items yet. Add your first one below." /> : (
              <div className="overflow-x-auto"><table className="w-full text-sm"><thead className="bg-surface text-xs text-muted"><tr><th className="text-left p-3">Item</th><th className="text-right p-3">Price</th><th className="text-right p-3">GST</th><th className="text-left p-3">Supplier</th><th className="p-3" /></tr></thead>
                <tbody>{list.map((i) => <tr key={i.id} className="border-t border-line"><td className="p-3 font-medium">{i.name} <span className="text-muted">/ {i.unit}</span></td><td className="p-3 text-right">{inr(i.price)}</td><td className="p-3 text-right">{i.gst_rate}%</td><td className="p-3 text-muted">{supName(i.supplier_id)}</td><td className="p-3 text-right"><button className="text-xs text-red-600 underline" onClick={() => removeItem(i.id)}>Remove</button></td></tr>)}</tbody></table></div>)}
          </Card>)}</Gate>
        <form onSubmit={addItem} className="card p-4 mt-3 grid grid-cols-2 md:grid-cols-6 gap-2 items-end">
          <input className={`${f} col-span-2`} placeholder="Item name" value={it.name} onChange={(e) => setIt({ ...it, name: e.target.value })} required maxLength={80} aria-label="Item name" />
          <input className={f} type="number" min="0.01" step="any" placeholder="Price ₹" value={it.price} onChange={(e) => setIt({ ...it, price: e.target.value })} required aria-label="Price" />
          <select className={f} value={it.unit} onChange={(e) => setIt({ ...it, unit: e.target.value })} aria-label="Unit">{unitOptions.map((u) => <option key={u}>{u}</option>)}</select>
          <select className={f} value={it.gst_rate} onChange={(e) => setIt({ ...it, gst_rate: e.target.value })} aria-label="GST rate">{[0, 3, 5, 12, 18, 28].map((r) => <option key={r} value={r}>GST {r}%</option>)}</select>
          <select className={f} value={it.supplier_id} onChange={(e) => setIt({ ...it, supplier_id: e.target.value })} aria-label="Supplier"><option value="">No supplier</option>{(sups.data || []).map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</select>
          <label className="col-span-2 md:col-span-2 flex items-center gap-2 text-sm"><input type="checkbox" checked={it.track_stock} onChange={(e) => setIt({ ...it, track_stock: e.target.checked })} />Track stock</label>
          {it.track_stock && <input className={f} type="number" min="0" step="any" placeholder="In stock now" value={it.stock_qty} onChange={(e) => setIt({ ...it, stock_qty: e.target.value })} aria-label="Current stock" />}
          {it.track_stock && <input className={f} type="number" min="0.01" step="any" placeholder="Order pack size" value={it.pack_qty} onChange={(e) => setIt({ ...it, pack_qty: e.target.value })} aria-label="Pack size" />}
          <input className={`${f} col-span-2`} placeholder="Other names (comma separated), e.g. atta, आटा" value={it.aliases} onChange={(e) => setIt({ ...it, aliases: e.target.value })} aria-label="Aliases" />
          <button className="btn btn-primary" disabled={busy}>Add item</button>
        </form>
      </section>

      <section>
        <Title sub="Saathi drafts re-orders for these suppliers. You approve before anything is sent.">Your suppliers</Title>
        <Gate state={sups}>{(list: any[]) => (
          <Card className="!p-0">{list.length === 0 ? <Empty icon="🚚" text="No suppliers yet." /> : <ul className="divide-y divide-line text-sm">{list.map((s) => <li key={s.id} className="p-3 flex justify-between"><span className="font-medium">{s.name}</span><span className="text-muted">{s.phone} · {s.lead_time_days}d delivery</span></li>)}</ul>}</Card>)}</Gate>
        <form onSubmit={addSup} className="card p-4 mt-3 flex flex-wrap gap-2">
          <input className={`${f} flex-1 min-w-[160px]`} placeholder="Supplier name" value={sp.name} onChange={(e) => setSp({ ...sp, name: e.target.value })} required minLength={2} maxLength={100} aria-label="Supplier name" />
          <input className={`${f} w-44`} inputMode="numeric" placeholder="Mobile number" value={sp.phone} onChange={(e) => setSp({ ...sp, phone: e.target.value })} required aria-label="Supplier phone" />
          <input className={`${f} w-28`} type="number" min="0" max="30" placeholder="Days" value={sp.lead_time_days} onChange={(e) => setSp({ ...sp, lead_time_days: e.target.value })} aria-label="Delivery days" />
          <button className="btn btn-primary" disabled={busy}>Add supplier</button>
        </form>
      </section>
    </div>
  );
}
