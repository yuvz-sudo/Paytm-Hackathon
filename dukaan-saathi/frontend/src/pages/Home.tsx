import { useT } from "../i18n";
import { Bar, CartesianGrid, ComposedChart, Legend, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useEffect, useState } from "react";
import { api, inr } from "../api";
import { useApi } from "../hooks";
import { onSpeakingChange, speak, stopSpeaking, unlockAudio } from "../voice";
import { TodayTransactions } from "./Transactions";
import NewsCard from "../components/NewsCard";
import HourBars from "../components/HourBars";
import { Badge, Card, Empty, Gate, Spinner, Stat, TileIcon, Title } from "../components/ui";
import { Icon } from "../components/icons";

const SEV_TILE: Record<string, string> = { high: "bg-red-50 text-red-600", medium: "bg-amber-50 text-amber-600", info: "bg-sky-50 text-sky-600", ok: "bg-emerald-50 text-emerald-600" };
const TAB_FOR: Record<string, string> = { setup_items: "shop", setup_suppliers: "shop", setup_sample: "shop", settle_fail: "money", settle_delay: "money", stock: "stock", sales_drop: "home", cash_gap: "money", udhaar: "udhaar", lapsed: "customers", chargeback: "money", gst: "money", gst_threshold: "money", festival: "stock", pay_fail: "home", refund: "home" };

function Compare() {
  const c = useApi<any>("/sales/compare");
  const hours = useApi<any>("/sales/hours");
  if (!c.data || c.data.no_data) return null;
  const rows = [c.data.week, c.data.month].filter(Boolean);
  const h = hours.data;
  return (
    <div className="grid lg:grid-cols-2 gap-4">
      <Card className="!rounded-3xl">
        <Title sub="Complete days only">Week and month comparison</Title>
        <ul className="space-y-3">{rows.map((r: any) => (
          <li key={r.label} className="rounded-2xl bg-surface px-4 py-3">
            <p className="text-xs font-semibold text-muted">{r.label}</p>
            <p className="flex items-baseline gap-2"><span className="text-2xl font-extrabold tracking-tight tabular-nums">{inr(r.current)}</span>
              {r.change_pct == null ? <span className="text-xs text-muted">no earlier period</span> : <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-bold ${r.change_pct >= 0 ? "bg-emerald-50 text-emerald-700" : "bg-red-50 text-red-600"}`}><Icon name={r.change_pct >= 0 ? "trend-up" : "trend-down"} size={13} strokeWidth={2.4} />{Math.abs(r.change_pct)}%</span>}
              <span className="text-xs text-muted">vs {inr(r.previous)}</span></p>
          </li>))}</ul>
      </Card>
      <Card className="!rounded-3xl">
        <Title sub="Average revenue per hour, last 4 weeks">Peak and quiet hours</Title>
        {!h || h.no_data ? <Empty text="Not enough data yet." /> : (() => { return (
          <>
            <HourBars h={h} />
            <p className="text-xs text-muted mt-2">Busiest: {h.peak_hours.map((x: number) => `${x % 12 || 12}${x < 12 ? "am" : "pm"}`).join(", ")} · Quietest: {h.quietest_hours.map((x: number) => `${x % 12 || 12}${x < 12 ? "am" : "pm"}`).join(", ")}</p>
          </>); })()}
      </Card>
    </div>
  );
}

function CheckPayment() {
  const [amount, setAmount] = useState("");
  const [minutes, setMinutes] = useState(5);
  const [res, setRes] = useState<any | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const check = async (e: React.FormEvent) => {
    e.preventDefault();
    const n = Number(amount);
    if (!(n > 0)) { setErr("Enter the amount the customer says they paid."); setRes(null); return; }
    setBusy(true); setErr(null);
    try { setRes(await api(`/payments/verify?amount=${n}&minutes=${minutes}`)); }
    catch (x: any) { setRes(null); setErr(x?.consentScope ? "Access to payments is switched off in Privacy settings." : "Couldn’t check right now. Please try again."); }
    finally { setBusy(false); }
  };
  const ok = res?.received;
  return (
    <Card className="!rounded-3xl">
      <Title sub="A customer shows a payment screenshot? Check it against your own Paytm records.">Check a payment</Title>
      <form className="flex flex-wrap items-end gap-3" onSubmit={check}>
        <label className="text-xs font-semibold text-muted">Amount (₹)
          <input className="input mt-1 block w-36 text-sm text-ink" inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="450" aria-label="Amount paid" />
        </label>
        <label className="text-xs font-semibold text-muted">Within
          <select className="input mt-1 block text-sm text-ink" value={minutes} onChange={(e) => setMinutes(Number(e.target.value))}>{[5, 10, 30].map((v) => <option key={v} value={v}>{v} min</option>)}</select>
        </label>
        <button className="btn btn-primary !min-h-[44px]" disabled={busy}><Icon name="shield" size={17} />{busy ? "Checking…" : "Check"}</button>
      </form>
      {err && <p className="text-sm text-amber-700 mt-3" role="alert">{err}</p>}
      {res && (
        <div className={`pop mt-4 rounded-2xl border p-4 text-sm ${ok ? "border-emerald-200 bg-emerald-50" : "border-red-200 bg-red-50"}`} role="status">
          <b className={`flex items-center gap-2 ${ok ? "text-emerald-700" : "text-red-700"}`}><Icon name={ok ? "check-circle" : res.verdict === "earlier_only" ? "clock" : "x-circle"} size={18} />
            {ok ? `${inr(res.amount)} received ${res.matches[0].minutes_ago} min ago`
              : res.verdict === "earlier_only" ? `Not in the last ${res.window_minutes} min`
              : res.verdict.startsWith("not_received_") ? `A ${inr(res.amount)} payment shows as ${res.verdict.split("_").pop()}` : `No ${inr(res.amount)} payment in the last ${res.window_minutes} min`}
          </b>
          {res.verdict === "earlier_only" && <p className="mt-1">The only {inr(res.amount)} credit was {res.earlier[0].minutes_ago} min ago, so it may belong to someone else.</p>}
          {!ok && <p className="mt-1">Don’t hand over the goods until it shows here or on your soundbox.</p>}
          <p className="mt-1 text-xs text-muted">Trust only your Paytm app or soundbox, never a screenshot. Suspect fraud? Call <b>1930</b>.</p>
        </div>)}
    </Card>
  );
}

export default function Home({ go, lang, onSample }: { go: (t: string) => void; lang: string; onSample?: () => void }) {
  const t = useT();
  const briefing = useApi<any>("/briefing");
  const series = useApi<any[]>("/sales/series?days=30");
  const modes = useApi<any>("/sales/summary?period=yesterday");
  const [overview, setOverview] = useState<"today" | "yesterday">("today");
  const todaySales = useApi<any>(overview === "today" ? "/sales/summary?period=today" : null);
  const [speaking, setSpeaking] = useState(false);
  const [refreshing, setRefreshing] = useState(false);

  const refresh = async () => {
    setRefreshing(true);
    try { await api("/briefing?refresh=true"); await briefing.reload(); } finally { setRefreshing(false); }
  };
  const downloadReport = () => {
    const rows = series.data;
    if (!rows?.length) return;
    const csv = "date,total_sales,payments\n" + rows.map((r: any) => `${r.date},${r.total},${r.payments}`).join("\n");
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
    const a = document.createElement("a");
    a.href = url; a.download = "sales-last-30-days.csv"; a.click();
    URL.revokeObjectURL(url);
  };
  useEffect(() => onSpeakingChange(setSpeaking), []);
  useEffect(() => () => stopSpeaking(), []);
  const play = (text: string) => {
    unlockAudio();
    if (speaking) { stopSpeaking(); return; }
    speak(text, lang);
  };

  return (
    <Gate state={briefing} goPrivacy={() => go("privacy")}>
      {(b) => {
        const s = b.sales;
        if (b.empty) {
          return (
            <div className="space-y-5">
              <Card className="hero">
                <span className="chip-ai"><Icon name="sparkles" size={14} />Welcome</span>
                <p className="mt-3 text-[17px] sm:text-lg leading-relaxed font-medium max-w-2xl">{b.script}</p>
              </Card>
              <Title sub="A few quick steps to get value from day one">Get started</Title>
              <div className="grid md:grid-cols-3 gap-3">
                {b.cards.map((c: any) => (
                  <button key={c.id} className="card p-5 text-left" onClick={() => (c.id === "setup_sample" && onSample ? onSample() : go("shop"))}>
                    <span className="icon-tile bg-sky-50 text-primary"><Icon name={c.icon} /></span><p className="font-bold text-[15px] mt-3">{c.title}</p><p className="text-sm text-muted mt-1">{c.detail}</p>
                  </button>))}
              </div>
            </div>
          );
        }
        return (
          <div className="space-y-5">
            <Card className="hero !p-6 sm:!p-8">
              <div className="flex items-start justify-between gap-5 flex-wrap">
                <div className="max-w-2xl">
                  <span className="chip-ai"><Icon name="sparkles" size={14} />{t("Today’s briefing")}</span>
                  <p className="mt-4 text-[17px] sm:text-[19px] leading-relaxed font-medium text-white/95">{b.script}</p>
                </div>
                <div className="flex gap-2">
                  <button className={`btn ${speaking ? "bg-white text-brand" : "btn-glass"}`} onClick={() => play(b.script)} aria-pressed={speaking}>
                    {speaking ? <span className="flex items-end gap-[3px] h-4" aria-hidden>{[0, 1, 2].map((i) => <span key={i} className="w-[3px] rounded-full bg-current animate-pulse" style={{ height: `${[60, 100, 70][i]}%`, animationDelay: `${i * 150}ms` }} />)}</span> : <Icon name="volume" size={18} />}
                    {speaking ? t("Stop") : t("Listen")}
                  </button>
                  <button className="btn btn-glass" disabled={refreshing} onClick={refresh} aria-label={t("Refresh")}><span className={refreshing ? "animate-spin" : ""}><Icon name="refresh" size={18} /></span><span className="hidden sm:inline">{t("Refresh")}</span></button>
                </div>
              </div>
              {b.blocked_scopes?.length > 0 && <p className="mt-4 text-xs text-amber-200 flex items-center gap-1.5"><Icon name="lock" size={14} />Some insights are hidden because access is off for: {b.blocked_scopes.join(", ")}.</p>}
            </Card>

            {s && (
              <section aria-label="Business overview">
                <div className="flex flex-wrap items-center gap-3 mb-4">
                  <h2 className="text-xl sm:text-2xl font-extrabold tracking-tight">{t("Business Overview for")}</h2>
                  <div className="seg" role="tablist" aria-label="Choose day">
                    {(["today", "yesterday"] as const).map((d) => (
                      <button key={d} role="tab" aria-selected={overview === d} onClick={() => setOverview(d)}
                        >{t(d === "today" ? "Today" : "Yesterday")}</button>))}
                  </div>
                </div>
                {(() => {
                  const isToday = overview === "today";
                  const o = isToday ? todaySales.data : s;
                  if (!o) return <div className="grid grid-cols-1 sm:grid-cols-3 gap-4" aria-busy="true"><div className="skeleton h-[150px]" /><div className="skeleton h-[150px]" /><div className="skeleton h-[150px]" /></div>;
                  const day = isToday ? "today" : "yesterday";
                  const vs = isToday ? t("vs same time yesterday") : t("vs previous day");
                  return (
                    <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                      <Stat tint="blue" icon={<TileIcon kind="rupee" />} onClick={() => go(`transactions:${day}`)} label={isToday ? t("Today’s sales so far") : t("Yesterday’s sales")} value={inr(o.total)}
                        sub={o.change_pct == null ? t("no earlier day to compare") : `${o.change_pct > 0 ? "▲" : "▼"} ${Math.abs(o.change_pct)}% ${vs}`} tone={o.change_pct == null ? undefined : o.change_pct >= 0 ? "up" : "down"} />
                      <Stat tint="green" icon={<TileIcon kind="check" />} onClick={() => go(`transactions:${day}`)} label={t("Payments")} value={o.payments} sub={o.failed_count ? `${o.failed_count} ${t("failed")}` : t("none failed")} tone={o.failed_count ? "down" : undefined} />
                      <Stat tint="pink" icon={<TileIcon kind="refund" />} onClick={o.refund_count ? () => go(`transactions:${day}:refunded`) : undefined} label={t("Refunds")} value={o.refund_count} sub={o.refund_count ? inr(o.refund_amount) : "—"} />
                    </div>);
                })()}
              </section>
            )}

            <TodayTransactions go={go} />

            <NewsCard />

            <Compare />

            <div className="panel grid lg:grid-cols-5 gap-5">
              <Card className="lg:col-span-3 !rounded-3xl">
                <Title sub={t("Successful payments per day")} right={<button className="btn btn-ghost" onClick={downloadReport} disabled={!series.data?.length}><Icon name="download" size={16} /><span className="hidden sm:inline">Download Report</span><span className="sm:hidden">CSV</span></button>}>{t("Last 30 days")}</Title>
                {series.loading && !series.data ? <Spinner /> : series.data ? (
                  <div className="h-72">
                    <ResponsiveContainer>
                      <ComposedChart data={series.data} margin={{ left: 4, right: 4, top: 8 }}>
                        <defs><linearGradient id="barG" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#00b9f5" /><stop offset="1" stopColor="#0a6cdf" stopOpacity={0.85} /></linearGradient></defs>
                        <CartesianGrid stroke="#eef2f7" strokeDasharray="3 4" vertical={false} />
                        <XAxis dataKey="date" tickFormatter={(d) => new Date(d).toLocaleDateString("en-IN", { day: "2-digit", month: "short" })} tick={{ fontSize: 11, fill: "#64748b" }} interval={2} angle={-20} textAnchor="end" height={46} axisLine={false} tickLine={false} />
                        <YAxis yAxisId="amt" tickFormatter={(v) => `₹${v >= 1000 ? `${Math.round(v / 1000)}k` : v}`} tick={{ fontSize: 11, fill: "#64748b" }} axisLine={false} tickLine={false} />
                        <YAxis yAxisId="cnt" orientation="right" allowDecimals={false} tick={{ fontSize: 11, fill: "#64748b" }} axisLine={false} tickLine={false} />
                        <Tooltip contentStyle={{ borderRadius: 14, border: "1px solid #e5eaf2", boxShadow: "0 12px 30px -12px rgba(11,42,91,.25)", fontSize: 12 }} cursor={{ fill: "rgba(0,185,245,.08)" }} formatter={(v: number, name: string) => (name === "Payment Amount" ? inr(v) : v)} labelFormatter={(d) => new Date(d).toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short" })} />
                        <Legend verticalAlign="bottom" align="left" iconType="circle" iconSize={10} wrapperStyle={{ paddingTop: 12, fontSize: 12 }} />
                        <Bar yAxisId="amt" name="Payment Amount" dataKey="total" fill="url(#barG)" radius={[6, 6, 0, 0]} maxBarSize={22} isAnimationActive={false} />
                        <Line yAxisId="cnt" name="No. Of Payments" dataKey="payments" type="monotone" stroke="#0b2a5b" strokeWidth={2.5} dot={false} isAnimationActive={false} />
                      </ComposedChart>
                    </ResponsiveContainer>
                  </div>
                ) : <Empty text="No data to show." />}
              </Card>

              <Card className="lg:col-span-2 !rounded-3xl">
                <Title sub={t("Yesterday")}>{t("Best sellers")}</Title>
                {b.best_sellers?.items?.length ? (
                  <ol className="space-y-2">
                    {b.best_sellers.items.map((it: any, i: number) => (
                      <li key={it.item} className="flex items-center justify-between gap-3 text-sm rounded-xl px-2 py-2 hover:bg-surface"><span className="flex items-center gap-3 min-w-0"><span className={`h-8 w-8 shrink-0 rounded-xl grid place-items-center text-xs font-extrabold ${i === 0 ? "bg-amber-100 text-amber-700" : i === 1 ? "bg-slate-100 text-slate-600" : i === 2 ? "bg-orange-50 text-orange-700" : "bg-surface text-muted"}`}>{i + 1}</span><span className="font-medium truncate">{it.item}</span></span><span className="font-bold tabular-nums">{inr(it.revenue)}</span></li>
                    ))}
                    <li className="text-[11px] text-muted pt-1">{t("Based on {n}% of payments that had item details.").replace("{n}", String(b.best_sellers.coverage_pct))}</li>
                  </ol>
                ) : <Empty icon="doc" text="Item details appear when you bill through Paytm." />}
              </Card>
            </div>

            <CheckPayment />

            {modes.data?.by_mode && Object.keys(modes.data.by_mode).length > 0 && (
              <div className="panel !pt-0">
                <Card className="!rounded-3xl">
                  <h2 className="text-xl font-extrabold tracking-tight mb-5">Payment Sources for <span className="inline-block align-middle rounded-full bg-surface ring-1 ring-line px-3 py-1 text-sm font-semibold ml-1">{t("Yesterday")}</span></h2>
                  <ul className="space-y-5">
                    {Object.entries(modes.data.by_mode as Record<string, number>).sort((x, y) => y[1] - x[1]).map(([mode, amt]) => {
                      const tot = Object.values(modes.data.by_mode as Record<string, number>).reduce((p, c) => p + c, 0) || 1;
                      const share = Math.round((amt / tot) * 100);
                      return (
                        <li key={mode}>
                          <div className="flex items-center justify-between text-sm mb-2">
                            <span className="flex items-center gap-3"><span className="h-9 w-9 rounded-xl bg-gradient-to-br from-sky-50 to-blue-100 grid place-items-center text-[11px] font-extrabold text-brand">{mode.slice(0, 3)}</span><span className="font-semibold text-brand">{mode}</span></span>
                            <span className="text-muted tabular-nums"><span className="text-ink font-bold mr-3">{inr(amt)}</span>{share}%</span>
                          </div>
                          <div className="h-2 rounded-full bg-sky-50" role="progressbar" aria-valuenow={share} aria-valuemin={0} aria-valuemax={100} aria-label={`${mode} share`}><div className="h-full rounded-full bg-gradient-to-r from-accent to-primary" style={{ width: `${share}%` }} /></div>
                        </li>);
                    })}
                  </ul>
                </Card>
              </div>)}

            <div>
              <Title sub={t("Most important first")}>{t("Needs your attention")}</Title>
              {b.cards.length === 0 ? <Card><Empty text="Nothing needs your attention right now." /></Card> : (
                <div className="grid md:grid-cols-2 gap-3">
                  {b.cards.map((c: any) => (
                    <button key={c.id} onClick={() => go(TAB_FOR[c.id] || "home")} className="group card p-4 sm:p-5 text-left">
                      <div className="flex items-start gap-4">
                        <span className={`icon-tile ${SEV_TILE[c.severity] || "bg-slate-50 text-slate-600"}`}><Icon name={c.icon} /></span>
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-2 flex-wrap"><span className="font-bold text-[15px]">{t(c.title)}</span><Badge tone={c.severity}>{t(c.severity === "info" ? "FYI" : c.severity)}</Badge></div>
                          <p className="text-sm text-muted mt-1 leading-relaxed">{c.detail}</p>
                        </div>
                        <span className="self-center text-muted transition-transform group-hover:translate-x-1" aria-hidden><Icon name="chevron-right" size={18} /></span>
                      </div>
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>
        );
      }}
    </Gate>
  );
}
