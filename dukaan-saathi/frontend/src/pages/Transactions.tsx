import { useState } from "react";
import { useT } from "../i18n";
import { inr } from "../api";
import { useApi } from "../hooks";
import { Badge, Card, Empty, Gate, Stat, TileIcon, Title } from "../components/ui";
import { Icon } from "../components/icons";

const FILTERS: [string, string][] = [["all", "All"], ["success", "Successful"], ["failed", "Failed"], ["refunded", "Refunded"]];
const STATUS: Record<string, [string, string]> = { success: ["ok", "Success"], failed: ["high", "Failed"], refunded: ["medium", "Refunded"] };

const clock = (iso: string) => new Date(iso).toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit", hour12: true });

function Row({ x }: { x: any }) {
  const [tone, label] = STATUS[x.status] || ["neutral", x.status];
  return (
    <li className="flex items-center justify-between gap-3 py-3">
      <div className="min-w-0">
        <p className="text-sm font-semibold truncate">{x.customer || "Paytm payment"}</p>
        <p className="text-xs text-muted mt-0.5">{clock(x.ts)} · {x.mode} · #{x.id}</p>
      </div>
      <div className="text-right shrink-0">
        <p className={`text-base font-bold ${x.status === "success" ? "text-emerald-600" : "text-muted line-through"}`}>{x.status === "success" ? "+" : ""}{inr(x.amount)}</p>
        <Badge tone={tone}>{label}</Badge>
      </div>
    </li>);
}

/** Compact "Today's transactions" block for the Home dashboard. */
export function TodayTransactions({ go }: { go: (t: string) => void }) {
  const t = useT();
  const d = useApi<any>("/transactions/today");
  const r = d.data;
  if (d.error || (!r && !d.loading)) return null; // consent off or offline: the Business Overview already explains it
  return (
    <section aria-label="Today's transactions">
      <Card>
        <Title sub={r ? `${r.count} ${r.count === 1 ? "payment" : "payments"} · ${inr(r.total)} collected today` : undefined}
          right={<button className="btn btn-ghost !py-1" onClick={() => go("transactions")}>{t("View all")}<Icon name="arrow" size={15} /></button>}>{t("Today's transactions")}</Title>
        {!r ? <p className="text-sm text-muted">Loading…</p>
          : r.no_data ? <Empty icon="🧾" text="No payments yet today. They will show up here as soon as customers pay." />
            : <ul className="divide-y divide-line">{r.transactions.slice(0, 5).map((x: any) => <Row key={x.id} x={x} />)}</ul>}
      </Card>
    </section>
  );
}

const DAYS: [string, string][] = [["today", "Today"], ["yesterday", "Yesterday"]];

/** arg: "yesterday", "yesterday:refunded", "today:failed" ... (from Home tiles / voice). */
export default function Transactions({ go, arg = "" }: { go: (t: string) => void; arg?: string }) {
  const t = useT();
  const [a0, a1] = arg.split(":");
  const [day, setDay] = useState(DAYS.some(([d]) => d === a0) ? a0 : "today");
  const [filter, setFilter] = useState(FILTERS.some(([f]) => f === a1) ? a1 : "all");
  const d = useApi<any>(`/transactions?day=${day}`);
  const isToday = day === "today";

  return (
    <div className="space-y-5">
      <div className="inline-flex rounded-full border border-line p-1 bg-white" role="tablist" aria-label="Choose day">
        {DAYS.map(([id, label]) => (
          <button key={id} role="tab" aria-selected={day === id} onClick={() => setDay(id)}
            className={`rounded-full px-5 py-1.5 text-sm font-semibold ${day === id ? "bg-brand text-white" : "text-brand hover:bg-surface"}`}>{t(label)}</button>))}
      </div>
      <Gate state={d} goPrivacy={() => go("privacy")}>
        {(r) => {
          const rows = r.transactions.filter((x: any) => filter === "all" || x.status === filter);
          const dateLabel = new Date(r.date + "T00:00:00").toLocaleDateString("en-IN", { weekday: "long", day: "numeric", month: "short", year: "numeric" });
          return (
            <div className="space-y-5">
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                <Stat tint="blue" icon={<TileIcon kind="rupee" />} label={isToday ? t("Collected today") : t("Collected yesterday")} value={inr(r.total)} sub={`${r.count} ${r.count === 1 ? "payment" : "payments"}`} />
                <Stat tint="pink" icon={<TileIcon kind="alert" />} label={t("Failed")} value={r.failed_count} tone={r.failed_count ? "down" : undefined} sub="Not counted in total" onClick={r.failed_count ? () => setFilter("failed") : undefined} />
                <Stat tint="amber" icon={<TileIcon kind="money" />} label={t("Refunds")} value={r.refund_count} sub={r.refund_count ? inr(r.refund_amount) : isToday ? "None today" : "None yesterday"} onClick={r.refund_count ? () => setFilter("refunded") : undefined} />
              </div>
              <Card>
                <Title sub={isToday ? `${dateLabel} · updated ${clock(r.as_of)}` : `${dateLabel} · full day`} right={isToday ?
                  <button className="btn btn-ghost !py-1" onClick={d.reload} disabled={d.loading}>{d.loading ? "…" : "Refresh"}</button> : undefined}>{isToday ? t("Today's transactions") : t("Yesterday's transactions")}</Title>
                {Object.keys(r.by_mode).length > 0 && (
                  <div className="flex flex-wrap gap-2 mb-3">{Object.entries(r.by_mode).map(([k, v]) => <Badge key={k} tone="info">{k} {inr(v as number)}</Badge>)}</div>)}
                <div className="flex flex-wrap gap-2 mb-3" role="tablist" aria-label="Filter transactions">
                  {FILTERS.map(([id, label]) => (
                    <button key={id} role="tab" aria-selected={filter === id} onClick={() => setFilter(id)}
                      className={`rounded-full border px-3.5 py-1.5 text-sm font-medium ${filter === id ? "border-cyan bg-cyan/10 text-cyan" : "border-line text-brand hover:bg-surface"}`}>{t(label)}</button>))}
                </div>
                {r.no_data ? <Empty icon="🧾" text={isToday ? "No payments yet today. They will show up here as soon as customers pay." : "No payments were received yesterday."} />
                  : rows.length === 0 ? <Empty icon="🔍" text="Nothing matches this filter." /> : (
                    <ul className="divide-y divide-line">{rows.map((x: any) => <Row key={x.id} x={x} />)}</ul>)}
              </Card>
            </div>);
        }}
      </Gate>
    </div>
  );
}
