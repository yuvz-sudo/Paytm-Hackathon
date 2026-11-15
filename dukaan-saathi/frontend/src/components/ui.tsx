import { useT } from "../i18n";
import { ReactNode } from "react";
import { ApiError } from "../api";
import { Icon } from "./icons";

export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <div className={`card p-5 sm:p-6 ${className}`}>{children}</div>;
}

export function Title({ children, sub, right }: { children: ReactNode; sub?: string; right?: ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-3 mb-4">
      <div className="min-w-0">
        <h2 className="text-[17px] font-bold text-ink leading-snug">{children}</h2>
        {sub && <p className="text-[13px] text-muted mt-0.5">{sub}</p>}
      </div>
      {right}
    </div>
  );
}

const TONES: Record<string, [string, string]> = {
  high: ["bg-red-50 text-red-700 ring-red-200", "bg-red-500"],
  medium: ["bg-amber-50 text-amber-800 ring-amber-200", "bg-amber-500"],
  info: ["bg-sky-50 text-sky-800 ring-sky-200", "bg-sky-500"],
  ok: ["bg-emerald-50 text-emerald-700 ring-emerald-200", "bg-emerald-500"],
  neutral: ["bg-slate-50 text-slate-600 ring-slate-200", "bg-slate-400"],
};
export function Badge({ tone = "neutral", children }: { tone?: string; children: ReactNode }) {
  const [cls, dot] = TONES[tone] || TONES.neutral;
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full ring-1 ring-inset px-2 py-0.5 text-[11px] font-bold ${cls}`}>
      <span className={`h-1.5 w-1.5 rounded-full ${dot}`} aria-hidden />{children}
    </span>
  );
}

export function Spinner({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="space-y-3 p-2" role="status" aria-live="polite">
      <span className="sr-only">{label}</span>
      <div className="skeleton h-28 w-full" aria-hidden />
      <div className="grid sm:grid-cols-3 gap-3" aria-hidden><div className="skeleton h-24" /><div className="skeleton h-24" /><div className="skeleton h-24" /></div>
    </div>
  );
}

export function ErrorBox({ error, onRetry, goPrivacy }: { error: ApiError; onRetry?: () => void; goPrivacy?: () => void }) {
  const t = useT();
  if (error.consentScope) {
    return (
      <Card className="text-center">
        <div className="bubble mx-auto mb-3"><Icon name="lock" size={28} /></div>
        <p className="font-bold">Access to “{error.consentScope}” is switched off</p>
        <p className="text-sm text-muted mt-1">Dukaan Saathi can’t read this data until you allow it.</p>
        {goPrivacy && <button className="btn btn-primary mt-4" onClick={goPrivacy}>{t("Open Privacy settings")}</button>}
      </Card>
    );
  }
  return (
    <Card className="!border-red-200 flex items-start gap-4">
      <span className="icon-tile bg-red-50 text-red-600"><Icon name="alert" /></span>
      <div>
        <p className="font-bold text-red-700">{t("Something went wrong")}</p>
        <p className="text-sm text-muted mt-1">{error.status === 0 ? error.message : "We couldn’t load this. Please try again."}</p>
        {onRetry && <button className="btn btn-ghost mt-3" onClick={onRetry}><Icon name="refresh" size={16} />{t("Retry")}</button>}
      </div>
    </Card>
  );
}

// Older call sites pass an emoji; map them onto the icon set so the UI stays one visual language.
const EMOJI_ICON: Record<string, string> = { "📤": "send", "✉️": "inbox", "🧾": "file", "🔍": "search", "💇": "scissors", "📦": "box", "🚚": "truck", "✨": "sparkles", "🔒": "lock" };

export function Empty({ icon = "sparkles", text }: { icon?: string; text: string }) {
  const name = EMOJI_ICON[icon] || (/^[a-z-]+$/.test(icon) ? icon : "sparkles");
  return (
    <div className="flex flex-col items-center text-center text-sm text-muted py-10 gap-3">
      <div className="bubble"><Icon name={name} size={28} /></div>
      <p className="max-w-xs">{text}</p>
    </div>
  );
}

const TINT_ICON: Record<string, string> = {
  blue: "text-sky-600 bg-white ring-sky-100", green: "text-emerald-600 bg-white ring-emerald-100",
  pink: "text-rose-500 bg-white ring-rose-100", amber: "text-amber-600 bg-white ring-amber-100",
};

/** Icon for a summary tile; `kind` is any name from icons.tsx (rupee is a glyph). */
export function TileIcon({ kind }: { kind: string }) {
  if (kind === "rupee") return <span className="text-[22px] font-bold leading-none">₹</span>;
  return <Icon name={kind} />;
}

function Delta({ sub, tone }: { sub: ReactNode; tone?: "up" | "down" }) {
  if (!tone) return <p className="text-[13px] font-medium text-muted">{sub}</p>;
  const up = tone === "up";
  return (
    <p className={`inline-flex items-center gap-1.5 text-[13px] font-semibold ${up ? "text-emerald-700" : "text-red-600"}`}>
      <span className={`grid place-items-center h-5 w-5 rounded-full ${up ? "bg-emerald-100" : "bg-red-100"}`}><Icon name={up ? "trend-up" : "trend-down"} size={13} strokeWidth={2.4} /></span>
      {typeof sub === "string" ? sub.replace(/^[▲▼]\s*/, "") : sub}
    </p>
  );
}

export function Stat({ label, value, sub, tone, tint, icon, onClick }: { label: string; value: ReactNode; sub?: ReactNode; tone?: "up" | "down"; tint?: "blue" | "green" | "pink" | "amber"; icon?: ReactNode; onClick?: () => void }) {
  if (tint) {
    const Tag: any = onClick ? "button" : "div";
    return (
      <Tag onClick={onClick} className={`group tint tint-${tint} p-5 text-left relative w-full`}>
        <div className="flex items-start justify-between gap-3">
          <p className="text-[13.5px] font-semibold text-ink/80">{label}</p>
          {icon && <span className={`h-11 w-11 shrink-0 rounded-2xl grid place-items-center ring-1 shadow-sm ${TINT_ICON[tint]}`}>{icon}</span>}
        </div>
        <p className="text-[30px] font-extrabold mt-1 tracking-tight tabular-nums flex items-center gap-2 text-ink">
          {value}
          {onClick && <span aria-hidden className="text-muted transition-transform group-hover:translate-x-1"><Icon name="arrow" size={18} /></span>}
        </p>
        <div className="border-t border-black/[.06] mt-4 pt-3 min-h-[40px]">{sub != null && <Delta sub={sub} tone={tone} />}</div>
      </Tag>
    );
  }
  return (
    <Card>
      <p className="text-[13px] text-muted font-semibold">{label}</p>
      <p className="text-2xl font-extrabold mt-1 tracking-tight tabular-nums">{value}</p>
      {sub != null && <div className="mt-1.5"><Delta sub={sub} tone={tone} /></div>}
    </Card>
  );
}

export function Gate({ state, children, goPrivacy }: { state: { data: any; error: ApiError | null; loading: boolean; reload: () => void }; children: (d: any) => ReactNode; goPrivacy?: () => void }) {
  if (state.loading && !state.data) return <Spinner />;
  if (state.error) return <ErrorBox error={state.error} onRetry={state.reload} goPrivacy={goPrivacy} />;
  if (!state.data) return null;
  return <>{children(state.data)}</>;
}
