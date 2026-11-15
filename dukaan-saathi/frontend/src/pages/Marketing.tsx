import { useState } from "react";
import { api, ApiError, inr } from "../api";
import { useApi } from "../hooks";
import ActionCard from "../components/ActionCard";
import Poster from "../components/Poster";
import { Badge, Card, Empty, Gate, Title } from "../components/ui";

const OCCASIONS = ["Diwali", "Holi", "Eid", "Navratri", "New Year", "Weekend offer", "Special offer"];
const AUD: Record<string, string> = { lapsed: "Lapsed regulars", regulars: "Regulars", all: "All known customers" };

function CampaignCard({ c, shop, lang }: { c: any; shop: string; lang: string }) {
  const p = c.performance;
  return (
    <Card>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="font-semibold">{c.title}</p>
        <div className="flex gap-2"><Badge tone={c.status === "sent" ? "ok" : c.status === "draft" ? "info" : c.status === "failed" ? "high" : "neutral"}>{c.status}</Badge><Badge>{AUD[c.audience]} · {c.recipient_count}</Badge></div>
      </div>
      <div className="grid md:grid-cols-2 gap-4 mt-3">
        <div>
          <pre className="whitespace-pre-wrap rounded-lg bg-surface p-3 text-[13px] font-sans">{c.message}</pre>
          <p className="text-[11px] text-muted mt-1">{c.copy_source === "llm" ? "Written by AI, checked against your discount" : "Standard wording"} · {c.valid_days} days</p>
          {p && (
            <div className="mt-3 rounded-lg border border-line p-3 text-sm">
              <p className="font-semibold">Results so far</p>
              {p.too_soon ? <p>Sent just now. Results appear after the first full day.</p> : (<>
                <p>{p.recipients_returned} of {p.recipients} customers came back, spending {inr(p.recipient_revenue)}.</p>
                <p>Sales {inr(p.sales_since)} vs about {inr(p.expected_without_campaign)} usual{p.lift_pct != null && <> (<b className={p.lift >= 0 ? "text-emerald-600" : "text-red-600"}>{p.lift >= 0 ? "+" : ""}{p.lift_pct}%</b>)</>}.</p></>)}
              <p className="text-[11px] text-muted mt-1">{p.early ? "Too early to judge. " : ""}{p.note}</p>
            </div>)}
        </div>
        <Poster shop={shop} occasion={c.occasion} pct={c.discount_pct} days={c.valid_days} lang={lang} name={c.occasion.replace(/\W+/g, "-")} />
      </div>
    </Card>
  );
}

export default function Marketing({ go, shop, lang }: { go: (t: string) => void; shop: string; lang: string }) {
  const d = useApi<any>("/marketing/campaigns");
  const [occasion, setOccasion] = useState("Diwali");
  const [pct, setPct] = useState(10);
  const [aud, setAud] = useState("lapsed");
  const [draft, setDraft] = useState<any | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const create = async () => {
    setBusy(true); setErr(null);
    try {
      const r = await api("/marketing/campaigns", { method: "POST", body: { occasion, discount_pct: pct, valid_days: 7, audience: aud } });
      setDraft(r.action); if (r.discount_capped) setErr(`Discount capped at your ${r.cap_pct}% limit.`);
      d.reload();
    } catch (e) { setErr((e as ApiError).detail?.error === "no_audience" ? "No customers in that group yet." : "Couldn’t create the campaign."); }
    finally { setBusy(false); }
  };

  return (
    <Gate state={d} goPrivacy={() => go("privacy")}>
      {(data) => (
        <div className="space-y-5">
          <Card>
            <Title sub="Pick an occasion and an audience. You approve before anything is sent.">New campaign</Title>
            <div className="flex flex-wrap items-end gap-3">
              <label className="text-xs text-muted">Occasion
                <input list="occ" className="mt-1 block w-44 rounded-lg border border-line px-3 py-2 text-sm text-ink" value={occasion} maxLength={60} onChange={(e) => setOccasion(e.target.value)} />
                <datalist id="occ">{OCCASIONS.map((o) => <option key={o} value={o} />)}</datalist></label>
              <label className="text-xs text-muted">Discount
                <select className="mt-1 block rounded-lg border border-line px-2 py-2 text-sm text-ink" value={pct} onChange={(e) => setPct(Number(e.target.value))}>{[0, 5, 10, 15, 20].map((v) => <option key={v} value={v}>{v}%</option>)}</select></label>
              <label className="text-xs text-muted">Audience
                <select className="mt-1 block rounded-lg border border-line px-2 py-2 text-sm text-ink" value={aud} onChange={(e) => setAud(e.target.value)}>{Object.keys(AUD).map((k) => <option key={k} value={k}>{AUD[k]} ({data.audiences[k]})</option>)}</select></label>
              <button className="btn btn-primary" disabled={busy || !occasion.trim() || !data.audiences[aud]} onClick={create}>{busy ? "Creating…" : "Create campaign"}</button>
            </div>
            {err && <p className="text-sm text-amber-700 mt-2">{err}</p>}
            {draft && <div className="mt-4"><ActionCard action={draft} onDone={() => { setDraft(null); d.reload(); }} /></div>}
            <p className="text-[11px] text-muted mt-3">Approved messages are saved to your outbox. Real sending is not connected.</p>
          </Card>
          <div>
            <Title sub="Drafts, sent campaigns and how they did">Your campaigns</Title>
            {data.no_data ? <Card><Empty text="No campaigns yet. Create your first one above." /></Card> : <div className="space-y-3">{data.campaigns.map((c: any) => <CampaignCard key={c.id} c={c} shop={shop} lang={lang} />)}</div>}
          </div>
        </div>)}
    </Gate>
  );
}
