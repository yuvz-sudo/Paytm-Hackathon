import { useApi } from "../hooks";
import { useT } from "../i18n";
import { Card, Title } from "./ui";

const SEG: Record<string, string> = { kirana: "kirana", sweets: "sweet shop", salon: "salon", pharmacy: "pharmacy", restaurant: "restaurant" };

export function ago(hours: number | null | undefined) {
  if (hours == null) return "";
  if (hours < 1) return "just now";
  if (hours < 24) return `${hours}h ago`;
  const d = Math.round(hours / 24);
  return d === 1 ? "yesterday" : `${d} days ago`;
}

export function PriceChip({ s }: { s: { commodity: string; direction: string } }) {
  const up = s.direction === "up";
  return (
    <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-semibold ${up ? "bg-red-50 text-red-700 border-red-200" : "bg-emerald-50 text-emerald-700 border-emerald-200"}`}>
      {s.commodity} {up ? "price ▲" : "price ▼"}
    </span>);
}

/** Real headlines for this kind of business, each linked to its publisher. */
export default function NewsCard() {
  const t = useT();
  const d = useApi<any>("/news");
  const n = d.data;
  if (d.error || (n && !n.items?.length && !d.loading)) return null; // offline: the rest of Home still works
  return (
    <section aria-label="Market news">
      <Card>
        <Title sub={`What’s happening in the market for your ${SEG[n?.segment] || "business"} · from trusted publishers`}
          right={<button className="btn btn-ghost !py-1" onClick={d.reload} disabled={d.loading}>{d.loading ? "…" : t("Refresh")}</button>}>
          {t("Market news")}
        </Title>
        {!n ? <p className="text-sm text-muted">Loading…</p> : (
          <ul className="divide-y divide-line">
            {n.items.map((x: any) => (
              <li key={x.link} className="py-3">
                <a href={x.link} target="_blank" rel="noopener noreferrer" className="group block">
                  <p className="text-[15px] font-medium leading-snug group-hover:text-cyan group-hover:underline">{x.title}</p>
                  <p className="text-xs text-muted mt-1 flex flex-wrap items-center gap-2">
                    <span className="font-semibold text-ink" translate="no">{x.source}</span>
                    <span>· {ago(x.age_hours)}</span>
                    {x.price_signal && <PriceChip s={x.price_signal} />}
                    <span className="text-cyan">Read ↗</span>
                  </p>
                </a>
              </li>))}
          </ul>)}
        <p className="text-[11px] text-muted mt-2">{n?.source_note}</p>
      </Card>
    </section>
  );
}
