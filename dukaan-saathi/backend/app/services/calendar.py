"""Upcoming festivals / seasonal demand. Dates are approximate planning hints for the near term
(lunar-calendar festivals shift yearly) and are meant to be replaced by a maintained data feed."""
from __future__ import annotations

from datetime import date

from .. import clock

# (month, day, year or None for annual, name, categories that usually see demand)
FESTIVALS = [
    (11, 8, 2026, "Diwali", ["sweets", "kirana", "salon"]),
    (11, 24, 2026, "Dev Diwali", ["sweets", "kirana"]),
    (12, 25, None, "Christmas", ["sweets", "kirana"]),
    (12, 31, None, "New Year's Eve", ["sweets", "salon", "kirana"]),
    (1, 13, None, "Lohri", ["sweets", "kirana"]),
    (1, 14, None, "Makar Sankranti", ["sweets", "kirana"]),
    (1, 26, None, "Republic Day", ["kirana", "sweets"]),
    (2, 14, None, "Valentine's Day", ["sweets", "salon"]),
]
HINTS = {
    "sweets": "Stock gift boxes, dry fruits and ghee; pre-book bulk orders.",
    "kirana": "Expect higher demand for sugar, oil, flour, snacks and cold drinks.",
    "salon": "Open booking slots early; promote facial and styling packages.",
}


HINTS_HI = {
    "sweets": "गिफ्ट बॉक्स, मेवा और घी का स्टॉक रखें; थोक ऑर्डर पहले से बुक करें।",
    "kirana": "चीनी, तेल, आटा, स्नैक्स और कोल्ड ड्रिंक की माँग बढ़ने की उम्मीद है।",
    "salon": "बुकिंग स्लॉट जल्दी खोलें; फेशियल और स्टाइलिंग पैकेज का प्रचार करें।",
}


def upcoming(segment: str, within_days: int = 21) -> list[dict]:
    today = clock.today()
    out = []
    for mth, day, yr, name, segs in FESTIVALS:
        for y in ([yr] if yr else [today.year, today.year + 1]):
            d = date(y, mth, day)
            gap = (d - today).days
            if 0 <= gap <= within_days and segment in segs:
                out.append({"name": name, "date": d.isoformat(), "days": gap, "hint": HINTS.get(segment, ""), "hint_hi": HINTS_HI.get(segment, "")})
    return sorted(out, key=lambda x: x["days"])


def recent(segment: str, within_days: int = 7) -> list[dict]:
    """Festivals that just ended; used to explain post-festival sales dips."""
    today = clock.today()
    out = []
    for mth, day, yr, name, segs in FESTIVALS:
        for y in ([yr] if yr else [today.year, today.year - 1]):
            d = date(y, mth, day)
            ago = (today - d).days
            if 1 <= ago <= within_days and segment in segs:
                out.append({"name": name, "date": d.isoformat(), "days_ago": ago})
    return sorted(out, key=lambda x: x["days_ago"])
