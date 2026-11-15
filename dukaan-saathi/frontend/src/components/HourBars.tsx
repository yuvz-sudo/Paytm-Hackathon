import { inr } from "../api";

const label = (h: number) => `${h % 12 || 12}${h < 12 ? "am" : "pm"}`;

/** Average sales per hour. Bar heights are in pixels: Safari resolves % heights inside flex columns inconsistently
 *  and drew every bar at full height. */
export default function HourBars({ h, height = 112 }: { h: any; height?: number }) {
  const max = Math.max(...h.hours.map((x: any) => x.avg_revenue), 1);
  const room = height - 20; // leave space for the hour labels
  return (
    <div className="flex items-end gap-1" style={{ height }} role="img" aria-label="Average sales by hour">
      {h.hours.map((x: any) => {
        const px = Math.max(3, Math.round((x.avg_revenue / max) * room));
        const tone = h.peak_hours.includes(x.hour) ? "bg-brand" : h.quietest_hours.includes(x.hour) ? "bg-amber-400" : "bg-accent/60";
        return (
          <div key={x.hour} className="group relative flex-1 flex flex-col items-center justify-end gap-1" title={`${label(x.hour)} · ${inr(x.avg_revenue)} per day`}>
            <span className="pointer-events-none absolute -top-5 hidden group-hover:block rounded bg-ink px-1.5 py-0.5 text-[10px] text-white whitespace-nowrap z-10">{inr(x.avg_revenue)}</span>
            <div className={`w-full rounded-t ${tone}`} style={{ height: px }} />
            <span className="text-[10px] text-muted leading-none">{x.hour}</span>
          </div>);
      })}
    </div>);
}

export const hourLabel = label;
