import { useT } from "../i18n";
import { useState } from "react";
import { api } from "../api";
import { useApi } from "../hooks";
import { Card, Gate, Title } from "../components/ui";

export default function Privacy({ onChange }: { onChange: () => void }) {
  const t = useT();
  const consent = useApi<any[]>("/consent");
  const audit = useApi<any[]>("/audit?limit=40");
  const [busy, setBusy] = useState<string | null>(null);

  const toggle = async (scope: string, granted: boolean) => {
    setBusy(scope);
    try { await api(`/consent/${scope}`, { method: "PUT", body: { granted } }); await consent.reload(); await audit.reload(); onChange(); } finally { setBusy(null); }
  };
  return (
    <div className="grid lg:grid-cols-2 gap-5">
      <div>
        <Title sub={t("You decide what Dukaan Saathi can read. Switch anything off at any time.")}>{t("Your data, your control")}</Title>
        <Gate state={consent}>{(list: any[]) => (
          <Card className="divide-y divide-line !p-0">{list.map((c) => (
            <div key={c.scope} className="flex items-center justify-between gap-4 p-4">
              <div><p className="font-medium text-sm capitalize">{c.scope}</p><p className="text-xs text-muted">{c.label}</p></div>
              <button role="switch" aria-checked={c.granted} aria-label={`${c.scope} access`} disabled={busy === c.scope} onClick={() => toggle(c.scope, !c.granted)}
                className={`relative h-6 w-11 rounded-full transition-colors ${c.granted ? "bg-emerald-500" : "bg-slate-300"}`}><span className={`absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition-all ${c.granted ? "left-[22px]" : "left-0.5"}`} /></button>
            </div>))}</Card>)}</Gate>
        <p className="text-xs text-muted mt-3">{t("Money never moves and no message is sent without your approval. Every action is recorded in the log.")}</p>
      </div>
      <div>
        <Title sub={t("Everything Saathi did or you changed")}>{t("Activity log")}</Title>
        <Gate state={audit}>{(list: any[]) => (
          <Card className="!p-0 max-h-[520px] overflow-y-auto divide-y divide-line">{list.length === 0 ? <p className="p-4 text-sm text-muted">{t("No activity yet.")}</p> : list.map((a) => (
            <div key={a.id} className="p-3 text-sm"><div className="flex justify-between"><b>{a.event.replace(/_/g, " ")}</b><span className="text-xs text-muted">{new Date(a.ts).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" })}</span></div>
              <p className="text-xs text-muted">{a.actor}{Object.keys(a.detail || {}).length ? " · " + Object.entries(a.detail).map(([k, v]) => `${k}: ${typeof v === "object" ? JSON.stringify(v) : v}`).join(", ") : ""}</p></div>))}</Card>)}</Gate>
      </div>
    </div>
  );
}
