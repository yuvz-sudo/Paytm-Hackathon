import { useT } from "../i18n";
import { useState } from "react";
import { api, ApiError, inr } from "../api";
import { useApi } from "../hooks";
import ActionCard from "../components/ActionCard";
import CustomerBook from "../components/CustomerBook";
import { Badge, Card, Empty, Gate, Stat, Title, TileIcon } from "../components/ui";

const SEG_TONE: Record<string, string> = { high_value: "ok", repeat: "info", new: "info", at_risk: "medium", lapsed: "high" };

function Segments({ go }: { go: (t: string) => void }) {
  const d = useApi<any>("/retention/segments");
  const [proposal, setProposal] = useState<any | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const offer = async (seg: string) => {
    setBusy(seg); setMsg(null);
    try { const r = await api("/retention/offers", { method: "POST", body: { segment: seg } }); setProposal(r.action); if (r.discount_capped) setMsg(`Discount capped at your ${r.cap_pct}% limit.`); }
    catch (e) { setMsg((e as ApiError).detail?.error === "no_audience" ? "No reachable customers in this group yet." : "Couldn’t draft the offer."); }
    finally { setBusy(null); }
  };
  return (
    <Gate state={d} goPrivacy={() => go("privacy")}>
      {(r) => r.no_data ? <Card><Empty text="No identified customers yet. Segments appear once customers pay through Paytm more than once." /></Card> : (
        <div className="space-y-3">
          <Title sub={r.summary}>Customer segments</Title>
          {msg && <p className="text-sm text-amber-700">{msg}</p>}
          {proposal && <ActionCard action={proposal} onDone={() => setProposal(null)} />}
          <div className="grid md:grid-cols-2 xl:grid-cols-3 gap-3">
            {r.segments.map((x: any) => (
              <Card key={x.id}>
                <div className="flex items-center justify-between gap-2"><p className="font-semibold">{x.label}</p><Badge tone={SEG_TONE[x.id]}>{x.count}</Badge></div>
                <p className="text-xs text-muted mt-0.5">{x.help}</p>
                {x.count === 0 ? <p className="text-sm text-muted mt-3">No one here right now.</p> : (<>
                  <p className="text-sm mt-2">{inr(x.spend)} spent in 6 months</p>
                  <ul className="mt-2 space-y-1 text-sm">{x.members.slice(0, 3).map((m: any) => <li key={m.customer_id} className="flex justify-between gap-2"><span>{m.name}{m.usual_item && <span className="text-muted"> · {m.usual_item}</span>}</span><span className="text-muted">{inr(m.spend)}</span></li>)}</ul>
                  <button className="btn btn-ghost mt-3" disabled={busy !== null || x.reachable === 0} onClick={() => offer(x.id)}>{busy === x.id ? "Drafting…" : x.default_offer.pct ? `Send ${x.default_offer.pct}% offer (${x.reachable})` : `Send thank-you (${x.reachable})`}</button>
                </>)}
              </Card>))}
          </div>
          <p className="text-[11px] text-muted">{r.unsegmented} other customers (one-time or long gone) are not in any group. Offers need your approval and respect your discount cap.</p>
        </div>)}
    </Gate>
  );
}

export default function Customers({ go }: { go: (t: string) => void }) {
  const t = useT();
  const d = useApi<any>("/customers");
  const [pct, setPct] = useState(10);
  const [hour, setHour] = useState<number | "auto">("auto");
  const [proposal, setProposal] = useState<any | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const draft = async () => {
    setBusy(true); setMsg(null);
    try {
      const r = await api("/customers/winback", { method: "POST", body: { discount_pct: pct, valid_days: 7, ...(hour === "auto" ? {} : { send_hour: hour }) } });
      setProposal(r.action);
      if (r.discount_capped) setMsg(`Discount capped at your ${r.cap_pct}% limit.`);
    } catch (e) { setMsg((e as ApiError).detail?.error === "no_lapsed_customers" ? "No lapsed regulars right now." : "Couldn’t draft the offer."); }
    finally { setBusy(false); }
  };

  return (
    <Gate state={d} goPrivacy={() => go("privacy")}>
      {(c) => (
        <div className="space-y-5">
          <CustomerBook />
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            <Stat tint="blue" icon={<TileIcon kind="customers" />} label={t("Known customers")} value={c.identified_customers} sub="who paid via Paytm" />
            <Stat tint="green" icon={<TileIcon kind="check" />} label={t("Active (30 days)")} value={c.active_30d} />
            <Stat tint="amber" icon={<TileIcon kind="refund" />} label={t("Came back 2+ times")} value={c.repeat_30d} tone="up" />
            <Stat tint="pink" icon={<TileIcon kind="clock" />} label={t("Lapsed regulars")} value={c.lapsed.length} tone={c.lapsed.length ? "down" : undefined} sub={c.lapsed.length ? `${inr(c.at_risk_revenue)} past spend` : undefined} />
          </div>
          <Card>
            <Title sub="Regulars who’ve stopped coming (3+ visits, gap much longer than usual)" right={
              <div className="flex items-center gap-2">
                <label className="text-xs text-muted">Discount
                  <select className="ml-2 rounded-lg border border-line px-2 py-1.5 text-sm" value={pct} onChange={(e) => setPct(Number(e.target.value))}>{[5, 10, 15, 20].map((v) => <option key={v} value={v}>{v}%</option>)}</select>
                </label>
                <label className="text-xs text-muted">Time slot
                  <select className="ml-2 rounded-lg border border-line px-2 py-1.5 text-sm" value={hour} onChange={(e) => setHour(e.target.value === "auto" ? "auto" : Number(e.target.value))} aria-label="Offer time slot">
                    <option value="auto">{c.suggested_window ? `Quiet hours (${c.suggested_window.label}, ${c.suggested_window.when})` : "Any time"}</option>
                    {Array.from({ length: 24 }, (_, h) => <option key={h} value={h}>{`${h % 12 || 12} ${h < 12 ? "am" : "pm"}`}</option>)}
                  </select>
                </label>
                <button className="btn btn-primary" disabled={busy || !c.lapsed.length} onClick={draft}>{t("Draft win-back offer")}</button>
              </div>}>{t("Win back lapsed regulars")}</Title>
            {c.suggested_window
              ? <p className="text-xs text-muted mb-2">Your shop is quietest around <b>{c.suggested_window.label}</b>. Offers are timed to fill that slot.</p>
              : <p className="text-xs text-muted mb-2">Not enough sales history to find your quiet hours yet, so offers will not mention a time slot.</p>}
            {msg && <p className="text-sm text-amber-700 mb-2">{msg}</p>}
            {proposal && <div className="mb-4"><ActionCard action={proposal} onDone={() => setProposal(null)} /></div>}
            {c.lapsed.length === 0 ? <Empty text="No regulars have gone missing." /> : (
              <div className="overflow-x-auto"><table className="w-full text-sm">
                <thead className="text-xs text-muted"><tr><th className="text-left py-2">{t("Customer")}</th><th className="text-right">Visits</th><th className="text-right">Spent</th><th className="text-right">Usually comes every</th><th className="text-right">Last seen</th></tr></thead>
                <tbody>{c.lapsed.map((r: any) => (
                  <tr key={r.customer_id} className="border-t border-line"><td className="py-2.5 font-medium">{r.name}</td><td className="text-right">{r.visits}</td><td className="text-right font-semibold">{inr(r.total_spend)}</td><td className="text-right text-muted">{r.typical_gap_days} days</td><td className="text-right text-red-600">{r.days_since} days ago</td></tr>))}</tbody></table></div>)}
          </Card>
          <Segments go={go} />
          <Card>
            <Title sub={t("Your top customers by spend")}>{t("Top regulars")}</Title>
            {c.top_regulars.length === 0 ? <Empty text="Not enough repeat visits yet." /> : (
              <ol className="space-y-2">{c.top_regulars.map((r: any, i: number) => <li key={r.customer_id} className="flex justify-between text-sm"><span><span className="text-muted mr-2">{i + 1}.</span>{r.name} <span className="text-muted">· {r.visits} visits</span></span><span className="font-semibold">{inr(r.total_spend)}</span></li>)}</ol>)}
          </Card>
        </div>
      )}
    </Gate>
  );
}
