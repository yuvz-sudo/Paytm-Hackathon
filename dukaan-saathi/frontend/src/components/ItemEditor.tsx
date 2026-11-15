import { FormEvent, useState } from "react";
import { api, ApiError, inr } from "../api";

export type Supplier = { id: number; name: string };
const UNITS = ["pc", "kg", "g", "litre", "ml", "bag", "box", "pack", "tray", "dozen", "cup", "plate", "service"];

function errText(e: ApiError): string {
  const d = e.detail || {};
  if (d.error === "item_exists") return "You already have an item with that name.";
  if (d.error === "unknown_supplier") return "Pick a supplier from the list.";
  if (e.status === 422) return "Check the values: price above 0, quantities not negative.";
  return e.status === 0 ? e.message : "Couldn’t save. Please try again.";
}

/** Add a new item (no `item`) or edit one. Stock count here is a fresh count: it replaces the estimate as of now. */
export function ItemForm({ item, suppliers, onDone, onCancel }: { item?: any; suppliers: Supplier[]; onDone: (msg: string) => void; onCancel?: () => void }) {
  const [f, setF] = useState({
    name: item?.name ?? "", unit: item?.unit ?? "pc", price: item ? String(item.price) : "", stock: "",
    supplier_id: item?.supplier_id ? String(item.supplier_id) : "", pack_qty: item ? String(item.pack_qty ?? 1) : "1",
    track_stock: item?.track_stock ?? true,
  });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const set = (k: string, v: any) => setF((p) => ({ ...p, [k]: v }));

  const save = async (e: FormEvent) => {
    e.preventDefault();
    const price = Number(f.price);
    if (!f.name.trim()) { setErr("Enter the item name."); return; }
    if (!(price > 0)) { setErr("Enter a price above ₹0."); return; }
    if (f.stock !== "" && !(Number(f.stock) >= 0)) { setErr("Stock can’t be negative."); return; }
    setBusy(true); setErr("");
    try {
      if (item) {
        const body: any = { name: f.name.trim(), unit: f.unit, price, pack_qty: Number(f.pack_qty) || 1, track_stock: f.track_stock };
        if (f.supplier_id) body.supplier_id = Number(f.supplier_id); else if (item.supplier_id) body.clear_supplier = true;
        if (f.stock !== "" && f.track_stock) body.stock_qty = Number(f.stock);
        await api(`/items/${item.id}`, { method: "PUT", body });
        onDone(`Saved ${f.name.trim()}.`);
      } else {
        await api("/items", { method: "POST", body: { name: f.name.trim(), unit: f.unit, price, track_stock: f.track_stock, pack_qty: Number(f.pack_qty) || 1,
          supplier_id: f.supplier_id ? Number(f.supplier_id) : null, stock_qty: f.stock !== "" && f.track_stock ? Number(f.stock) : null } });
        onDone(`Added ${f.name.trim()} at ${inr(price)}.`);
      }
    } catch (x) { setErr(errText(x as ApiError)); } finally { setBusy(false); }
  };

  return (
    <form onSubmit={save} className="space-y-2">
      <div className="flex flex-wrap gap-2">
        <input className="input text-sm flex-1 min-w-[160px]" placeholder="Item name (e.g. Toor Dal 1kg)" value={f.name} maxLength={80} onChange={(e) => set("name", e.target.value)} aria-label="Item name" />
        <select className="input text-sm" value={f.unit} onChange={(e) => set("unit", e.target.value)} aria-label="Unit">{(UNITS.includes(f.unit) ? UNITS : [f.unit, ...UNITS]).map((u) => <option key={u} value={u}>{u}</option>)}</select>
        <input className="input text-sm w-28" type="number" min="0.01" step="any" placeholder="Price ₹" value={f.price} onChange={(e) => set("price", e.target.value)} aria-label="Price" />
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <label className="text-xs flex items-center gap-1.5"><input type="checkbox" checked={f.track_stock} onChange={(e) => set("track_stock", e.target.checked)} /> Track stock</label>
        {f.track_stock && <input className="input text-sm w-36" type="number" min="0" step="any" placeholder={item ? "Counted now (optional)" : "Opening stock"} value={f.stock} onChange={(e) => set("stock", e.target.value)} aria-label="Stock count" />}
        <select className="input text-sm" value={f.supplier_id} onChange={(e) => set("supplier_id", e.target.value)} aria-label="Supplier">
          <option value="">No supplier</option>{suppliers.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
        </select>
        <input className="input text-sm w-28" type="number" min="1" step="any" placeholder="Order pack" title="Supplier sells in packs of" value={f.pack_qty} onChange={(e) => set("pack_qty", e.target.value)} aria-label="Order pack size" />
        <button className="btn btn-primary !py-1.5" disabled={busy}>{busy ? "Saving…" : item ? "Save" : "+ Add item"}</button>
        {onCancel && <button type="button" className="btn btn-ghost !py-1.5" onClick={onCancel}>Cancel</button>}
      </div>
      {err && <p className="text-xs text-red-600">{err}</p>}
    </form>);
}

/** Remove with an in-page confirmation (no browser pop-up). Items are hidden, not erased: past sales keep their history. */
export function RemoveItem({ item, onDone }: { item: any; onDone: (msg: string) => void }) {
  const [ask, setAsk] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const remove = async () => {
    setBusy(true); setErr("");
    try { await api(`/items/${item.id}`, { method: "DELETE" }); onDone(`Removed ${item.name}. Past sales keep their history.`); }
    catch (x) { setErr(errText(x as ApiError)); setBusy(false); }
  };
  if (!ask) return <button className="btn btn-danger !py-1 !px-2.5 text-xs" onClick={() => setAsk(true)}>Remove</button>;
  return (
    <span className="inline-flex items-center gap-1.5 text-xs">
      Remove {item.name}?
      <button className="btn btn-danger !py-1 !px-2 text-xs" disabled={busy} onClick={remove}>Yes</button>
      <button className="btn btn-ghost !py-1 !px-2 text-xs" onClick={() => setAsk(false)}>No</button>
      {err && <span className="text-red-600">{err}</span>}
    </span>);
}
