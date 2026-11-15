import { useT } from "../i18n";
import { useState } from "react";
import { api, ApiError, inr } from "../api";
import ActionCard from "../components/ActionCard";
import { useApi } from "../hooks";
import HourBars from "../components/HourBars";
import { Badge, Card, Empty, ErrorBox, Spinner, Stat, TileIcon, Title } from "../components/ui";
import { Icon } from "../components/icons";

function Section({ state, go, children }: { state: any; go: (t: string) => void; children: (d: any) => any }) {
  if (state.loading && !state.data) return <Spinner />;
  if (state.error) return <ErrorBox error={state.error} onRetry={state.reload} goPrivacy={() => go("privacy")} />;
  return state.data ? children(state.data) : null;
}

function Explain({ id, onClose }: { id: number; onClose: () => void }) {
  const d = useApi<any>(`/settlements/${id}/explain`);
  return (
    <Card className="border-accent bg-sky-50">
      <div className="flex justify-between items-start gap-3"><p className="font-semibold">Why this amount?</p><button className="text-xs text-muted underline" onClick={onClose}>Close</button></div>
      {d.loading && !d.data ? <Spinner /> : d.error ? <p className="text-sm text-red-700 mt-2">Couldn’t load the breakdown.</p> : d.data && (
        <div className="mt-2 text-sm">
          <p>{d.data.summary}</p>
          {d.data.has_breakdown && (
            <table className="mt-3 w-full text-sm"><tbody>
              <tr><td className="py-1">Payments received</td><td className="py-1 text-right font-medium">{inr(d.data.gross)}</td></tr>
              {d.data.deductions.map((x: any, i: number) => <tr key={i} className="text-red-700"><td className="py-1">− {x.label}</td><td className="py-1 text-right">{inr(x.amount)}</td></tr>)}
              <tr className="border-t border-line font-semibold"><td className="py-1.5">You get</td><td className="py-1.5 text-right">{inr(d.data.net)}</td></tr>
            </tbody></table>)}
          <p className="text-[11px] text-muted mt-2">{d.data.note}</p>
        </div>)}
    </Card>
  );
}

function Chargebacks({ state, go }: { state: any; go: (t: string) => void }) {
  const [proposal, setProposal] = useState<any | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const draft = async (id: number) => {
    setBusy(true); setMsg(null);
    try { setProposal((await api("/chargebacks/proof", { method: "POST", body: { chargeback_id: id } })).action); }
    catch (e) { const c = (e as ApiError).detail?.error; setMsg(c === "deadline_passed" ? "The deadline has passed. Please contact Paytm support." : "Couldn’t draft the proof message."); }
    finally { setBusy(false); }
  };
  return (
    <Section state={state} go={go}>{(c) => c.no_data ? <Card><Empty text="No chargebacks. If a customer disputes a payment, it will show here with a deadline." /></Card> : (
      <div className="space-y-3">
        {msg && <p className="text-sm text-amber-700">{msg}</p>}
        {proposal && <ActionCard action={proposal} onDone={() => { setProposal(null); state.reload(); }} />}
        {c.chargebacks.map((x: any) => {
          const open = x.status === "open";
          return (
            <Card key={x.id} className={open && x.urgent ? "border-red-200 bg-red-50" : ""}>
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <p className="font-semibold">{inr(x.amount)} chargeback <Badge tone={open ? (x.urgent ? "high" : "medium") : x.status === "won" || x.status === "proof_sent" ? "ok" : "neutral"}>{x.status.replace("_", " ")}</Badge></p>
                  <p className="text-sm text-muted mt-1">{x.reason}. Raised {x.raised_date}.</p>
                  {open && <p className={`text-sm mt-1 font-medium ${x.urgent ? "text-red-700" : "text-amber-800"}`}>{x.overdue ? `Deadline passed ${-x.days_left} day(s) ago` : x.days_left === 0 ? "Proof due today" : `${x.days_left} day(s) left to send proof (by ${x.proof_due_date})`}. If you miss it, the amount is debited from your settlement.</p>}
                </div>
                {open && !x.overdue && <button className="btn btn-primary" disabled={busy} onClick={() => draft(x.id)}>Draft proof message</button>}
              </div>
            </Card>);
        })}
      </div>)}</Section>
  );
}

function Mdr({ state, go }: { state: any; go: (t: string) => void }) {
  return (
    <Section state={state} go={go}>{(f) => f.no_data ? <Card><Empty text="No UPI payments this month yet." /></Card> : (
      <div className="space-y-3">
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          <Stat tint="blue" icon={<TileIcon kind="rupee" />} label="UPI received" value={inr(f.upi_receipts)} sub={`${f.upi_count} payments`} />
          <Stat tint="green" icon={<TileIcon kind="check" />} label="Fee-free" value={inr(f.exempt_amount)} />
          <Stat tint={f.estimated_mdr ? "pink" : "green"} icon={<TileIcon kind="tag" />} label="Estimated UPI fee" value={inr(f.estimated_mdr)} tone={f.estimated_mdr ? "down" : "up"} sub={f.chargeable_count ? `${f.chargeable_count} payments above ₹2,000` : "nothing charged"} />
          <Stat tint="amber" icon={<TileIcon kind="doc" />} label="Share touched" value={`${f.share_charged_pct}%`} sub="of UPI receipts" />
        </div>
        {f.months.map((mo: any) => <p key={mo.month} className="text-xs text-muted">{mo.month}: {inr(mo.upi_receipts)} by UPI. {mo.over_exempt_limit ? "Above the ₹1,00,000 monthly limit, so payments over ₹2,000 are charged." : `${inr(mo.headroom)} more before the ₹1,00,000 monthly limit.`}</p>)}
        <Card className="border-amber-200 bg-amber-50"><p className="text-sm font-semibold">This is an estimate</p>
          <ul className="text-xs text-muted mt-1 list-disc pl-5 space-y-0.5">{f.assumptions.map((a: string) => <li key={a}>{a}</li>)}</ul></Card>
      </div>)}</Section>
  );
}

function FinanceReport({ state, go }: { state: any; go: (t: string) => void }) {
  return (
    <Section state={state} go={go}>{(r) => r.no_data ? <Card><Empty text="No payments in this period yet." /></Card> : (
      <div className="space-y-3">
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          <Stat tint="blue" icon={<TileIcon kind="rupee" />} label={r.partial ? "Collected so far" : "Collected"} value={inr(r.collections)} sub={r.collections_change_pct == null ? undefined : `${r.collections_change_pct >= 0 ? "▲" : "▼"} ${Math.abs(r.collections_change_pct)}% vs previous period`} tone={r.collections_change_pct == null ? undefined : r.collections_change_pct >= 0 ? "up" : "down"} />
          <Stat tint="pink" icon={<TileIcon kind="refund" />} label="Refunds" value={inr(r.refunds.amount)} sub={`${r.refunds.count} payments · ${r.refunds.pct_of_collections}%`} />
          <Stat tint="amber" icon={<TileIcon kind="alert" />} label="Failed payments" value={r.failed.count} sub={`${r.failed.rate_pct}% · about ${inr(r.failed.amount)}`} tone={r.failed.count ? "down" : undefined} />
          <Stat tint="green" icon={<TileIcon kind="bank" />} label="Paytm deductions" value={inr(r.settlements.total_deductions)} sub="on settlements in this period" />
        </div>
        <Card>
          <ul className="text-sm space-y-1 list-disc pl-5">{r.highlights.map((h: string) => <li key={h}>{h}</li>)}</ul>
          <p className="text-xs text-muted mt-2">By payment type: {Object.entries(r.by_mode).map(([k, v]) => `${k} ${inr(v as number)}`).join(" · ")}. Settlements: {inr(r.settlements.settled)} paid, {inr(r.settlements.pending)} pending, {inr(r.settlements.failed)} failed.{r.partial ? " The month is not over yet." : ""}</p>
        </Card>
      </div>)}</Section>
  );
}

function Forecast({ state, go }: { state: any; go: (t: string) => void }) {
  return (
    <Section state={state} go={go}>{(f) => f.no_data ? <Card><Empty text="I need about four weeks of payments before I can forecast." /></Card> : (
      <div className="space-y-3">
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          <Stat tint="blue" icon={<TileIcon kind="rupee" />} label="Expected collections" value={inr(f.collections.likely)} sub={`range ${inr(f.collections.low)} to ${inr(f.collections.high)}`} />
          <Stat tint="amber" icon={<TileIcon kind="doc" />} label="Bills due (30 days)" value={inr(f.bills_total)} sub={`${f.bills.length} bill(s) recorded`} />
          <Stat tint={f.net_low < 0 ? "pink" : "green"} icon={<TileIcon kind="check" />} label="Left after bills" value={inr(f.net_likely)} sub="likely case, after 15% running costs" tone={f.net_likely < 0 ? "down" : "up"} />
          <Stat tint="green" icon={<TileIcon kind="clock" />} label="Trend" value={f.trend_pct == null ? "—" : `${f.trend_pct >= 0 ? "+" : ""}${f.trend_pct}%`} sub="last 4 weeks vs the 4 before" tone={f.trend_pct == null ? undefined : f.trend_pct >= 0 ? "up" : "down"} />
        </div>
        {(f.crunch || f.crunch_if_low) ? (
          <Card className="border-amber-200 bg-amber-50">
            <p className="font-semibold">Cash may get tight around {(f.crunch || f.crunch_if_low).date}</p>
            <p className="text-sm mt-1">Bills due could exceed sales by about <b>{inr((f.crunch || f.crunch_if_low).shortfall)}</b>{f.crunch ? "" : " if sales come in at the low end"}. An indicative working-capital need is <b>{inr(f.working_capital_needed || (f.crunch || f.crunch_if_low).shortfall)}</b>. See the credit suggestion above.</p>
          </Card>) : <Card><p className="text-sm flex items-center gap-3"><span className="text-emerald-600 shrink-0"><Icon name="check-circle" size={20} /></span>No cash crunch expected from your recorded bills in the next 30 days.</p></Card>}
        {f.bills.length > 0 && <Card><ul className="text-sm space-y-1">{f.bills.map((b: any, i: number) => <li key={i} className="flex justify-between"><span>{b.label} <span className="text-muted">· due in {b.days}d</span></span><b>{inr(b.amount)}</b></li>)}</ul></Card>}
        <ul className="text-[11px] text-muted list-disc pl-5">{f.notes.map((n: string) => <li key={n}>{n}</li>)}</ul>
      </div>)}</Section>
  );
}

export default function Money({ go }: { go: (t: string) => void }) {
  const t = useT();
  const settle = useApi<any>("/settlements");
  const credit = useApi<any>("/credit");
  const gst = useApi<any>("/gst?period=last_month");
  const hours = useApi<any>("/sales/hours");
  const cbs = useApi<any>("/chargebacks");
  const fin = useApi<any>("/finance/report?period=this_month");
  const fc = useApi<any>("/finance/forecast");
  const mdr = useApi<any>("/fees/mdr?period=this_month");
  const [explainId, setExplainId] = useState<number | null>(null);

  return (
    <div className="space-y-6">
      <section>
        <Title sub={t("Where your Paytm money is")}>{t("Settlements")}</Title>
        <Section state={settle} go={go}>{(s) => (
          <div className="space-y-3">
            {s.failed.map((x: any) => <Card key={x.id} className="border-red-200 bg-red-50"><b className="text-red-700">Failed · {inr(x.amount)}</b><p className="text-sm mt-1">{x.failure_reason}. Update your bank details or contact Paytm support. UTR {x.utr}</p></Card>)}
            {s.delayed.map((x: any) => <Card key={x.id} className="border-amber-200 bg-amber-50"><b className="text-amber-800">Delayed {x.days_late} day(s) · {inr(x.amount)}</b><p className="text-sm mt-1">Expected {x.expected_date}. UTR {x.utr}</p></Card>)}
            {explainId !== null && <Explain id={explainId} onClose={() => setExplainId(null)} />}
            {!s.failed.length && !s.delayed.length && <Card><p className="text-sm flex items-center gap-3"><span className="text-emerald-600 shrink-0"><Icon name="check-circle" size={20} /></span>All settlements are on track. {inr(s.pending_amount)} upcoming.</p></Card>}
            <Card className="!p-0 overflow-x-auto"><table className="w-full text-sm"><thead className="bg-surface text-xs text-muted"><tr><th className="text-left p-3">Expected</th><th className="text-right p-3">Amount</th><th className="text-left p-3">{t("Status")}</th><th className="text-left p-3">UTR</th><th className="p-3"><span className="sr-only">Details</span></th></tr></thead>
              <tbody>{[...s.failed, ...s.delayed, ...s.upcoming, ...s.recent].map((x: any) => (
                <tr key={x.id} className="border-t border-line"><td className="p-3">{x.expected_date}</td><td className="p-3 text-right font-medium">{inr(x.amount)}</td><td className="p-3"><Badge tone={x.status === "settled" ? "ok" : x.status === "failed" ? "high" : x.days_late ? "medium" : "neutral"}>{x.status === "pending" && x.days_late ? "delayed" : x.status}</Badge></td><td className="p-3 text-muted text-xs">{x.utr}</td><td className="p-3 text-right"><button className="text-accent text-xs font-semibold underline whitespace-nowrap" onClick={() => setExplainId(x.id)}>Why this amount?</button></td></tr>))}</tbody></table></Card>
          </div>)}</Section>
      </section>

      <section>
        <Title sub="This month so far, in plain words">Finance report</Title>
        <FinanceReport state={fin} go={go} />
      </section>

      <section>
        <Title sub="Next 30 days, cautious estimate">Cash flow forecast</Title>
        <Forecast state={fc} go={go} />
      </section>

      <section>
        <Title sub="Customer disputes. Send proof before the deadline or the amount is debited.">Chargebacks</Title>
        <Chargebacks state={cbs} go={go} />
      </section>

      <section>
        <Title sub="What UPI fees may cost you this month">UPI fee (MDR) estimate</Title>
        <Mdr state={mdr} go={go} />
      </section>

      <section>
        <Title sub={t("Upcoming bills vs expected sales over the next 14 days")}>{t("Cash flow & credit")}</Title>
        <Section state={credit} go={go}>{(c) => {
          const cf = c.cashflow;
          return (
            <div className="space-y-3">
              <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
                <Stat tint="amber" icon={<TileIcon kind="doc" />} label={t("Bills due (14 days)")} value={inr(cf.bills_due_total)} />
                <Stat tint="green" icon={<TileIcon kind="rupee" />} label={t("Expected sales")} value={inr(cf.expected_inflow)} sub="cautious estimate" />
                <Stat tint={cf.has_gap ? "pink" : "green"} icon={<TileIcon kind="alert" />} label={t("Cash gap")} value={inr(cf.gap)} tone={cf.has_gap ? "down" : "up"} sub={cf.has_gap ? "bills come before sales" : "covered"} />
                <Stat tint="blue" icon={<TileIcon kind="bank" />} label={t("Pending settlements")} value={inr(cf.pending_settlements)} />
              </div>
              {cf.bills_due.length > 0 && <Card><ul className="text-sm space-y-1">{cf.bills_due.map((b: any, i: number) => <li key={i} className="flex justify-between"><span>{b.label} <span className="text-muted">· due in {b.days}d</span></span><b>{inr(b.amount)}</b></li>)}</ul></Card>}
              {c.eligible && c.needs_credit ? (
                <Card className="border-accent bg-sky-50">
                  <p className="font-semibold">Suggested: {inr(c.suggested_amount)} working-capital credit</p>
                  <p className="text-sm text-muted mt-1">{c.tenor_months} months · indicative EMI about {inr(c.indicative_emi)} at ~{c.indicative_apr_pct}% p.a. · {c.covers_gap ? "covers the gap" : "covers part of the gap"}</p>
                  <ul className="text-xs text-muted mt-2 list-disc pl-5">{c.reasons.map((r: string) => <li key={r}>{r}</li>)}</ul>
                  <p className="text-[11px] text-muted mt-2">{c.disclaimer}</p>
                </Card>
              ) : c.eligible ? <Card><p className="text-sm flex items-center gap-3"><span className="text-emerald-600 shrink-0"><Icon name="check-circle" size={20} /></span>{c.note || "No credit needed right now."}</p></Card>
                : <Card><p className="text-sm">Credit suggestions need more history ({String(c.reason).replace(/_/g, " ")}).</p></Card>}
            </div>);
        }}</Section>
      </section>

      <section>
        <Title sub={t("Estimate from your Paytm payments. Confirm with your CA before filing.")}>{t("GST")}</Title>
        <Section state={gst} go={go}>{(g) => g.no_data ? <Card><Empty text="No payments in this period." /></Card> : g.registered ? (
          <div className="space-y-3">
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
              <Stat tint="blue" icon={<TileIcon kind="rupee" />} label={`Turnover (${g.start.slice(5)} → ${g.end.slice(5)})`} value={inr(g.turnover)} />
              <Stat tint="green" icon={<TileIcon kind="doc" />} label={t("Estimated GST collected")} value={inr(g.estimated_tax)} />
              <Stat tint="amber" icon={<TileIcon kind="calendar" />} label="GSTR-1" value={g.days_to_gstr1 >= 0 ? `in ${g.days_to_gstr1}d` : `${-g.days_to_gstr1}d ago`} tone={g.days_to_gstr1 < 0 ? "down" : undefined} sub={g.days_to_gstr1 < 0 ? "confirm it is filed" : g.gstr1_due} />
              <Stat tint="amber" icon={<TileIcon kind="calendar" />} label="GSTR-3B" value={g.days_to_gstr3b >= 0 ? `in ${g.days_to_gstr3b}d` : `${-g.days_to_gstr3b}d ago`} sub={g.gstr3b_due} />
            </div>
            <Card className="!p-0 overflow-x-auto"><table className="w-full text-sm"><thead className="bg-surface text-xs text-muted"><tr><th className="text-left p-3">{t("GST rate")}</th><th className="text-right p-3">{t("Sales")}</th><th className="text-right p-3">{t("Taxable value")}</th><th className="text-right p-3">{t("Tax")}</th></tr></thead>
              <tbody>{g.breakup.map((b: any) => <tr key={b.rate} className="border-t border-line"><td className="p-3">{b.rate}%</td><td className="p-3 text-right">{inr(b.sales)}</td><td className="p-3 text-right">{inr(b.taxable_value)}</td><td className="p-3 text-right font-medium">{inr(b.tax)}</td></tr>)}</tbody></table></Card>
            {g.unallocated_note && <Card className="border-amber-200 bg-amber-50"><p className="text-sm"><b>{inr(g.unallocated_sales)}</b> of sales had no item details, so no GST slab. {g.unallocated_note}</p></Card>}
            <p className="text-[11px] text-muted">{g.filing_note}</p>
          </div>
        ) : (
          <Card className={g.threshold_alert ? "border-amber-200 bg-amber-50" : ""}><p className="text-sm">You’re not GST-registered. Annualised turnover ≈ <b>{inr(g.annualised_turnover)}</b> vs the {inr(g.registration_threshold)} registration limit.{g.threshold_crossed ? " You may need to register — please check with your CA." : g.threshold_alert ? " You’re close to the limit." : ""}</p></Card>
        )}</Section>
      </section>

      <section>
        <Title sub={t("Average revenue by hour, last 4 weeks")}>{t("Busy and quiet hours")}</Title>
        <Section state={hours} go={go}>{(h) => h.no_data ? <Card><Empty text="Not enough data yet." /></Card> : (
          <Card>
            <HourBars h={h} height={140} />
            <p className="text-xs text-muted mt-3"><span className="inline-block w-2 h-2 bg-brand rounded-sm mr-1" />Busiest · <span className="inline-block w-2 h-2 bg-amber-400 rounded-sm mx-1" />Quietest — a small offer in quiet hours can fill them.</p>
          </Card>)}</Section>
      </section>
    </div>
  );
}
