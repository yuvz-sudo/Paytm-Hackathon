import { useEffect, useState } from "react";
import { api, ApiError, inr } from "../api";
import { useApi } from "../hooks";
import { useT } from "../i18n";
import ActionCard from "../components/ActionCard";
import { ago, PriceChip } from "../components/NewsCard";
import { Badge, Card, Empty, Gate, Title } from "../components/ui";
import { Icon } from "../components/icons";
import { onSpeakingChange, speak, stopSpeaking, unlockAudio } from "../voice";

const GO: Record<string, string> = { winback: "customers", campaign: "marketing", promotion: "customers" };
const MOVE: Record<string, [string, string]> = { increase: ["ok", "Stock up"], reduce: ["medium", "Go slow"], check: ["info", "Count first"] };
const TONE: Record<string, string> = { bad: "border-red-200 bg-red-50", warn: "border-amber-200 bg-amber-50", good: "border-emerald-200 bg-emerald-50" };
const date = (iso: string) => new Date(iso + "T00:00:00").toLocaleDateString("en-IN", { day: "numeric", month: "short" });

function Sources({ sig }: { sig: any }) {
  if (!sig?.sources?.length) return null;
  return (
    <div className="mt-2 text-xs text-muted space-y-1">
      <PriceChip s={sig} />
      {sig.sources.map((s: any) => (
        <a key={s.link} href={s.link} target="_blank" rel="noopener noreferrer" className="block hover:text-cyan hover:underline">
          <span translate="no" className="font-semibold text-ink">{s.source}</span>: {s.title} ↗
        </a>))}
    </div>);
}

function Ask({ go, q }: { go: (t: string) => void; q: string }) {
  return <button className="inline-flex items-center gap-1.5 text-xs font-bold text-primary hover:underline" onClick={() => go("chat:" + q)}><Icon name="sparkles" size={14} />Ask Saathi about this</button>;
}

function SlowSeller({ x, go }: { x: any; go: (t: string) => void }) {
  const [busy, setBusy] = useState(false);
  const [action, setAction] = useState<any>(null);
  const [err, setErr] = useState("");
  const draft = async () => {
    setBusy(true); setErr("");
    try {
      const r = await api("/marketing/campaigns", { method: "POST", body: { occasion: `${x.item} offer`, discount_pct: x.discount_pct, audience: "regulars", valid_days: 7, use_llm: false } });
      setAction(r.action);
    } catch (e) {
      const c = (e as ApiError).code;
      setErr(c === "no_audience" ? "No regular customers to send it to yet." : c === "consent_off" ? "Turn on Customers access in Privacy to draft offers." : "Couldn’t draft the offer. Try again.");
    } finally { setBusy(false); }
  };
  return (
    <Card>
      <div className="flex items-center gap-2 flex-wrap"><span className="font-semibold text-sm">{x.item}</span>
        <Badge tone={x.why === "declining" ? "high" : "medium"}>{x.why === "declining" ? `sales −${x.drop_pct}%` : x.why === "overstocked" ? `${x.days_cover} days of stock` : "weak seller"}</Badge></div>
      <p className="text-sm text-muted mt-1">{x.advice}</p>
      {action ? <div className="mt-3"><ActionCard action={action} onDone={() => setAction(null)} /></div> : (
        <div className="flex items-center gap-4 mt-3 flex-wrap">
          {x.discount_pct > 0 && <button className="btn btn-primary !py-1.5" disabled={busy} onClick={draft}>{busy ? "Drafting…" : `Draft ${x.discount_pct}% offer for regulars`}</button>}
          <Ask go={go} q={`Your growth advice says: "${x.advice}" How should I sell more ${x.item}? Discount or bundle?`} />
        </div>)}
      {err && <p className="text-xs text-red-600 mt-2">{err}</p>}
    </Card>);
}

export default function Growth({ go, lang = "en" }: { go: (t: string) => void; lang?: string }) {
  const t = useT();
  const plan = useApi<any>("/growth/plan");
  const d = useApi<any>("/growth/advisor");
  const [speaking, setSpeaking] = useState(false);
  useEffect(() => onSpeakingChange(setSpeaking), []);
  useEffect(() => () => stopSpeaking(), []);
  const p = plan.data;
  const note = p?.note;

  return (
    <div className="space-y-6">
      {/* the advisor's note */}
      {plan.loading && !p ? <Card><p className="text-sm text-muted">Saathi is going through your numbers…</p></Card> : note && (
        <Card className="hero !p-6 sm:!p-8">
          <div className="flex items-start justify-between gap-4 flex-wrap">
            <div className="max-w-3xl">
              <span className="chip-ai"><Icon name="sparkles" size={14} />{t("Your advisor’s note")}</span>
              <p className="mt-4 text-[16px] sm:text-[17px] leading-relaxed whitespace-pre-wrap text-white/95">{note.text}</p>
              <p className="text-[11px] text-sky-200 mt-3">{note.source === "llm" ? "Written by Saathi’s AI from your own numbers and real market news." : "Prepared from your own numbers and real market news."} Estimates, not promises.</p>
            </div>
            <div className="flex gap-2 flex-wrap">
              <button className="btn btn-glass" onClick={() => { unlockAudio(); speaking ? stopSpeaking() : speak(note.text, note.language || lang); }}><Icon name={speaking ? "stop" : "volume"} size={18} />{speaking ? t("Stop") : t("Listen")}</button>
              <button className="btn bg-white text-brand hover:bg-sky-50 shadow-lg" onClick={() => go("chat:Let's talk about your advice for my shop. What should I do first this week?")}>Talk it through with Saathi</button>
            </div>
          </div>
        </Card>)}

      {p && !p.blocked && !p.no_data && (<>
        {/* season */}
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm font-semibold mr-1">{t("Season")}:</span>
          <Badge tone="info">{p.season.weather}</Badge>
          {p.season.wedding_season && <Badge tone="info">wedding season</Badge>}
          {p.season.festivals.map((f: any) => <Badge key={f.name} tone="medium">{f.name} · {f.days === 0 ? "today" : `in ${f.days} days`}</Badge>)}
          {!p.season.festivals.length && <span className="text-xs text-muted">No major festival for your business in the next 30 days.</span>}
        </div>

        {/* stock moves */}
        <div>
          <Title sub="Next 14 days: festivals, wedding season and weather, sized to your own sales and supplier lead time.">{t("What to stock up on, and what to slow down")}</Title>
          {p.stock_moves.length === 0 && p.service_moves.length === 0 ? <Card><Empty text="Your stock is in line with the season. No changes needed." /></Card> : (
            <div className="grid md:grid-cols-2 gap-3">
              {p.stock_moves.map((x: any) => {
                const [tone, label] = MOVE[x.move];
                return (
                  <Card key={x.item + x.move}>
                    <div className="flex items-center gap-2 flex-wrap">
                      <Badge tone={tone}>{label}</Badge><span className="font-semibold text-sm">{x.item}</span>
                      {x.uplift_pct ? <span className={`text-xs font-semibold ${x.uplift_pct > 0 ? "text-emerald-700" : "text-amber-700"}`}>demand {x.uplift_pct > 0 ? "+" : ""}{x.uplift_pct}%{x.reason ? ` · ${x.reason}` : ""}</span> : null}
                    </div>
                    <p className="text-sm mt-1.5">{x.advice}</p>
                    {x.move === "increase" && <p className="text-xs text-muted mt-1">Have {x.current_stock ?? "?"} {x.unit} · expect to sell ~{x.expected_14d} in 14 days{x.est_cost ? ` · ~${inr(x.est_cost)} to buy` : ""} · order by {date(x.by)}</p>}
                    <Sources sig={x.price_signal} />
                    <div className="mt-2"><Ask go={go} q={`Your growth advice says: "${x.advice}" ${x.move === "increase" ? `Should I really buy this much ${x.item}? What if it does not sell?` : `Why should I go slow on ${x.item}?`}`} /></div>
                  </Card>);
              })}
              {p.service_moves.map((x: any) => (
                <Card key={x.item}>
                  <div className="flex items-center gap-2"><Badge tone="ok">Plan capacity</Badge><span className="font-semibold text-sm">{x.item}</span><span className="text-xs font-semibold text-emerald-700">+{x.uplift_pct}%{x.reason ? ` · ${x.reason}` : ""}</span></div>
                  <p className="text-sm mt-1.5">{x.advice}</p>
                  <div className="mt-2"><Ask go={go} q={`Your growth advice says: "${x.advice}" How do I make the most of it?`} /></div>
                </Card>))}
            </div>)}
        </div>

        {/* slow sellers */}
        {p.slow_sellers.length > 0 && (
          <div>
            <Title sub={`Discounts stay within your ${p.max_discount_pct}% limit and are only sent after you approve.`}>{t("Slow sellers")}</Title>
            <div className="grid md:grid-cols-2 gap-3">{p.slow_sellers.map((x: any) => <SlowSeller key={x.item} x={x} go={go} />)}</div>
          </div>)}

        {/* money */}
        {p.money.length > 0 && (
          <div>
            <Title sub="Like a financial advisor would read your books: cash, credit, fees and stock budget.">{t("Money advice")}</Title>
            <div className="grid md:grid-cols-2 gap-3">
              {p.money.map((x: any) => (
                <div key={x.id} className={`rounded-2xl border p-4 ${TONE[x.tone]}`}>
                  <p className="font-semibold text-sm">{x.title}</p>
                  <p className="text-sm mt-1 text-ink/80">{x.detail}</p>
                  <div className="mt-2"><Ask go={go} q={`Your money advice says: "${x.title}: ${x.detail}" What exactly should I do?`} /></div>
                </div>))}
            </div>
          </div>)}

        {/* price news */}
        {p.price_signals.length > 0 && (
          <Card>
            <Title sub="From real news headlines about what you buy and sell. Check the source before big purchases.">{t("Price watch")}</Title>
            <ul className="divide-y divide-line">{p.price_signals.map((s: any) => (
              <li key={s.commodity} className="py-2.5">
                <div className="flex items-center gap-2"><PriceChip s={s} /><span className="text-xs text-muted">{s.headlines} headline{s.headlines === 1 ? "" : "s"}</span></div>
                {s.sources.map((x: any) => (
                  <a key={x.link} href={x.link} target="_blank" rel="noopener noreferrer" className="block text-sm mt-1 hover:text-cyan hover:underline">
                    {x.title} <span className="text-xs text-muted">· <span translate="no">{x.source}</span>{x.published ? ` · ${ago(Math.round((Date.now() - Date.parse(x.published)) / 3.6e6))}` : ""} ↗</span>
                  </a>))}
              </li>))}</ul>
          </Card>)}
      </>)}
      {p?.no_data && <Card><Empty text="Saathi needs a couple of weeks of item-level sales to give stock advice." /></Card>}

      {/* existing opportunities and problems */}
      <Gate state={d} goPrivacy={() => go("privacy")}>
        {(g) => g.no_data ? <Card><Empty text={g.reason || "Not enough data yet."} /></Card> : (
          <div className="space-y-5">
            {g.biggest_problem && (
              <Card className="border-red-200 bg-red-50">
                <p className="text-xs uppercase tracking-wider text-red-700 font-semibold">Biggest problem right now</p>
                <p className="font-semibold mt-1">{g.biggest_problem.title}</p>
                <p className="text-sm text-muted mt-0.5">{g.biggest_problem.detail}{g.biggest_problem.at_stake ? ` About ${inr(g.biggest_problem.at_stake)} at stake.` : ""}</p>
                <button className="btn btn-primary mt-3" onClick={() => go(g.biggest_problem.go)}>Open</button>
              </Card>)}
            <div>
              <Title sub="Ranked by estimated monthly rupees. Estimates, not promises.">Growth opportunities</Title>
              {g.opportunities.length === 0 ? <Card><Empty text="No clear growth gaps right now. Keep going." /></Card> : (
                <div className="grid md:grid-cols-2 gap-3">
                  {g.opportunities.map((o: any, i: number) => (
                    <Card key={o.id}>
                      <div className="flex items-center gap-2 flex-wrap"><span className="text-muted text-sm">{i + 1}.</span><span className="font-semibold text-sm">{o.title}</span><Badge tone="info">≈ {inr(o.est_monthly_impact)}/month</Badge></div>
                      <p className="text-sm text-muted mt-1">{o.detail}</p>
                      <div className="flex items-center gap-4 mt-3 flex-wrap">
                        <button className="btn btn-ghost" onClick={() => go(GO[o.action] || "chat")}>{o.action === "winback" ? "Draft an offer" : "Plan a campaign"}</button>
                        <Ask go={go} q={`${o.title}. How exactly should I do this?`} />
                      </div>
                    </Card>))}
                </div>)}
            </div>
            {g.problems.length > 1 && (
              <Card><Title sub="Everything else costing you money">Other problems</Title>
                <ul className="space-y-2 text-sm">{g.problems.slice(1).map((p: any) => <li key={p.id} className="flex justify-between gap-3"><span><b>{p.title}</b> <span className="text-muted">· {p.detail}</span></span><button className="text-accent underline text-xs" onClick={() => go(p.go)}>Open</button></li>)}</ul></Card>)}
            <p className="text-[11px] text-muted">{g.note} Seasonal demand figures are planning rules of thumb for Indian retail.</p>
          </div>)}
      </Gate>
    </div>
  );
}
