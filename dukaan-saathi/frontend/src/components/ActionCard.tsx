import { useT } from "../i18n";
import { useState } from "react";
import { api, ApiError } from "../api";
import { Badge } from "./ui";
import { DeliveryRow, DELIVERY_NOTE } from "./Delivery";

const KIND: Record<string, string> = {
  supplier_order: "Supplier order", udhaar_reminder: "Udhaar reminder", winback_offer: "Win-back offer", chargeback_proof: "Chargeback proof", campaign_send: "Campaign",
};

export default function ActionCard({ action, onDone }: { action: any; onDone: () => void }) {
  const t = useT();
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState<string>(action.payload.message || "");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [deliveries, setDeliveries] = useState<any[]>([]);

  const decide = async (kind: "approve" | "reject") => {
    setBusy(true);
    try {
      const body = kind === "approve" && editing && text.trim() !== (action.payload.message || "") ? { edited_message: text } : undefined;
      const r = await api(`/actions/${action.id}/${kind}`, { method: "POST", body });
      setMsg({ ok: r.status !== "failed", text: kind === "reject" ? "Rejected" : r.status === "failed" ? `Couldn’t complete: ${String(r.summary || r.error || "").replace(/_/g, " ")}` : r.summary || "Done" });
      const toSend = kind === "approve" && r.status !== "failed" ? (r.deliveries || []).filter((x: any) => x.status === "ready" || x.channel === "email") : [];
      if (toSend.length) setDeliveries(toSend); // stay open: the merchant now sends them from WhatsApp
      else setTimeout(onDone, 1200);
    } catch (e) {
      const err = e as ApiError;
      setMsg({ ok: false, text: err.status === 409 ? "Already handled." : "Failed. Please retry." });
      if (err.status === 409) setTimeout(onDone, 800);
    } finally {
      setBusy(false);
    }
  };

  const p = action.payload;
  const recips = p.recipients as { name: string }[] | undefined;
  return (
    <div className="rounded-xl border border-line bg-white p-4">
      <div className="flex items-center justify-between gap-2 mb-2">
        <Badge tone="info">{t(KIND[action.kind] || action.kind)}</Badge>
        <span className="text-[11px] text-muted">expires {new Date(action.expires_at).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" })}</span>
      </div>
      <p className="font-semibold text-sm">{action.title}</p>
      {recips && <p className="text-xs text-muted mt-1">To: {recips.slice(0, 4).map((r) => r.name).join(", ")}{recips.length > 4 ? ` +${recips.length - 4} more` : ""}</p>}
      {editing ? (
        <textarea className="mt-2 w-full rounded-lg border border-line p-2 text-sm" rows={4} maxLength={1000} value={text} onChange={(e) => setText(e.target.value)} aria-label="Edit message" />
      ) : (
        <pre className="mt-2 whitespace-pre-wrap rounded-lg bg-surface p-3 text-[13px] font-sans text-ink">{p.message}</pre>
      )}
      {p.window && <p className="text-xs text-muted mt-1">Timed for your quiet hours: {p.window.label}</p>}
      {action.kind === "chargeback_proof" && <p className="text-xs text-amber-700 mt-1">Attach your bill or delivery proof when Paytm replies; they decide on what you send.</p>}
      {(action.kind === "winback_offer" || action.kind === "campaign_send") && editing && <p className="text-[11px] text-muted mt-1">Use {"{name}"} to personalise.</p>}
      {msg ? (
        <div className="mt-3">
          <p className={`text-sm font-medium ${msg.ok ? "text-emerald-600" : "text-red-600"}`}>{deliveries.length ? "Approved. Now send it:" : msg.text}</p>
          {deliveries.length > 0 && (
            <div className="mt-2 space-y-2">
              <p className="text-xs text-muted">{DELIVERY_NOTE}</p>
              {deliveries.slice(0, 5).map((d) => <DeliveryRow key={d.id} d={d} />)}
              {deliveries.length > 5 && <p className="text-xs text-muted">+{deliveries.length - 5} more in Approvals → Ready to send.</p>}
              <button className="btn btn-ghost !py-1.5 text-xs" onClick={onDone}>Done</button>
            </div>)}
        </div>
      ) : (
        <div className="mt-3 flex flex-wrap gap-2">
          <button className="btn btn-primary" disabled={busy || (editing && !text.trim())} onClick={() => decide("approve")}>{busy ? t("Working…") : action.kind === "chargeback_proof" ? t("Approve proof") : t("Approve")}</button>
          <button className="btn btn-ghost" disabled={busy} onClick={() => setEditing((v) => !v)}>{editing ? t("Cancel edit") : t("Edit")}</button>
          <button className="btn btn-danger" disabled={busy} onClick={() => decide("reject")}>{t("Reject")}</button>
        </div>
      )}
    </div>
  );
}
