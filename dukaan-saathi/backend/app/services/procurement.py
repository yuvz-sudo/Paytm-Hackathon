from __future__ import annotations

from sqlalchemy.orm import Session

from .. import messages
from ..models import Merchant, Supplier
from ..util import qty_fmt
from . import actions, inventory


def propose_supplier_orders(db: Session, m: Merchant, item_names: list[str] | None = None) -> dict:
    """Draft one order message per supplier covering at-risk items (or the named ones)."""
    status = inventory.stock_status(db, m)
    rows = status["items"]
    if item_names:
        wanted = []
        for nm in item_names:
            it, amb = inventory.find_item(db, m, nm)
            if amb:
                return {"ok": False, "error": "ambiguous_item", "candidates": [i.name for i in amb]}
            if not it:
                return {"ok": False, "error": "item_not_found", "item": nm}
            wanted.append(it.id)
        rows = [r for r in rows if r["item_id"] in wanted]
        # an explicitly requested item may not be 'low'; still order a sensible quantity
        for r in rows:
            if "suggested_qty" not in r:
                it = inventory.find_item(db, m, r["item"])[0]
                pace = r.get("daily_pace", 0) or 0
                lead = (r["supplier"] or {}).get("lead_time_days", 2)
                r["suggested_qty"] = max(it.pack_qty or 1, round(pace * (lead + (it.cover_days or inventory.COVER_DAYS))) or (it.pack_qty or 1))
    else:
        rows = [r for r in rows if r["status"] in ("out", "critical", "low")]
    if not rows:
        return {"ok": False, "error": "nothing_to_order"}

    by_sup: dict[int | None, list[dict]] = {}
    for r in rows:
        by_sup.setdefault((r["supplier"] or {}).get("id"), []).append(r)
    proposals, no_supplier = [], []
    for sid, lines in by_sup.items():
        if sid is None:
            no_supplier += [l["item"] for l in lines]
            continue
        sup = db.get(Supplier, sid)
        if not sup.phone:
            no_supplier += [l["item"] for l in lines]
            continue
        order_lines = [{"item": l["item"], "qty": l["suggested_qty"], "unit": l["unit"]} for l in lines]
        msg = messages.supplier_order(sup.language or m.language, m.name, m.owner_name, order_lines)
        key = "order:" + str(sid) + ":" + ",".join(sorted(l["item"] for l in lines))
        title = f"Order from {sup.name}: " + ", ".join(f"{l['item']} {qty_fmt(l['qty'])}" for l in order_lines[:3])
        proposals.append(actions.propose(db, m, "supplier_order", title, {
            "supplier_id": sup.id, "supplier_name": sup.name, "phone": sup.phone, "lines": order_lines, "message": msg}, dedupe_key=key))
    if not proposals:
        return {"ok": False, "error": "no_supplier_contact", "items": no_supplier}
    return {"ok": True, "proposals": proposals, "items_without_supplier": no_supplier}
