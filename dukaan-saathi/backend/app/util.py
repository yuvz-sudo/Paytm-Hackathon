from __future__ import annotations

import difflib
import re
import unicodedata
from datetime import date, datetime, timedelta

from . import clock


def inr(n: float | int | None, decimals: int = 0) -> str:
    """Indian digit grouping: 1234567 -> ₹12,34,567."""
    if n is None:
        return "—"
    neg = n < 0
    n = abs(float(n))
    s = f"{n:.{decimals}f}"
    whole, _, frac = s.partition(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        whole = ",".join(parts) + "," + tail
    out = "₹" + whole + (("." + frac) if decimals else "")
    return "-" + out if neg else out


def qty_fmt(q: float) -> str:
    return str(int(q)) if abs(q - round(q)) < 1e-9 else f"{q:.1f}".rstrip("0").rstrip(".")


def resolve_period(period: str | None, ref: datetime | None = None) -> tuple[datetime, datetime, str]:
    """Return [start, end) and a canonical label. Unknown/empty -> yesterday."""
    ref = ref or clock.now()
    t0 = datetime(ref.year, ref.month, ref.day)
    p = (period or "yesterday").strip().lower().replace(" ", "_")
    if p in ("today", "aaj"):
        return t0, ref, "today"
    if p in ("yesterday", "kal"):
        return t0 - timedelta(days=1), t0, "yesterday"
    if p in ("last_7_days", "week", "this_week", "last_week", "7d"):
        return t0 - timedelta(days=7), t0, "last_7_days"
    if p in ("last_30_days", "month", "30d"):
        return t0 - timedelta(days=30), t0, "last_30_days"
    if p == "this_month":
        return t0.replace(day=1), ref, "this_month"
    if p == "last_month":
        first = t0.replace(day=1)
        prev_last = first - timedelta(days=1)
        return prev_last.replace(day=1), first, "last_month"
    # explicit date YYYY-MM-DD
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", p):
        d = datetime.fromisoformat(p)
        return d, d + timedelta(days=1), p
    return t0 - timedelta(days=1), t0, "yesterday"


_STRIP = re.compile(r"[^\wऀ-ॿ ]+", re.UNICODE)


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "").lower()
    return re.sub(r"\s+", " ", _STRIP.sub(" ", s)).strip()


def best_match(query: str, candidates: dict[str, list[str]], cutoff: float = 0.72):
    """candidates: key -> list of names/aliases. Returns (key, score, ambiguous_keys)."""
    q = norm(query)
    if not q:
        return None, 0.0, []
    scored: list[tuple[float, str]] = []
    for key, names in candidates.items():
        best = 0.0
        for n in names:
            nn = norm(n)
            if not nn:
                continue
            if q == nn:
                sc = 1.0
            elif q in nn.split() or nn in q.split():
                sc = 0.93
            elif q in nn or nn in q:
                sc = 0.85
            else:
                sc = difflib.SequenceMatcher(None, q, nn).ratio()
            best = max(best, sc)
        scored.append((best, key))
    scored.sort(reverse=True)
    if not scored or scored[0][0] < cutoff:
        return None, scored[0][0] if scored else 0.0, []
    top = scored[0][0]
    close = [k for sc, k in scored if sc >= top - 0.04 and sc >= cutoff]
    return scored[0][1], top, close if len(close) > 1 else []


def pct_change(new: float, old: float) -> float | None:
    if old == 0:
        return None
    return round((new - old) / old * 100, 1)


def short_date(d: date | datetime) -> str:
    return d.strftime("%d %b")


def hour_label(h: int) -> str:
    """15 -> '3 pm', 0 -> '12 am'."""
    return f"{h % 12 or 12} {'am' if h % 24 < 12 else 'pm'}"
