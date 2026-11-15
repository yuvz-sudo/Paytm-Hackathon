"""Voice navigation: "open stock", "udhaar dikhao", "स्टॉक खोलो". Works on the English translation too, so it covers
every supported language. Returns a dashboard tab id, or None when the merchant is asking a question instead."""
from __future__ import annotations

import re

# tab -> words that name it (English, Hinglish, Hindi)
PAGES: dict[str, tuple[str, ...]] = {
    "transactions": ("transaction", "transactions", "payments list", "today's payments", "lenden", "len den", "लेनदेन", "ट्रांजैक्शन"),
    "stock": ("stock", "inventory", "maal", "स्टॉक", "माल"),
    "udhaar": ("udhaar", "udhar", "khata", "credit book", "dues", "उधार", "खाता"),
    "customers": ("customer", "customers", "grahak", "ग्राहक"),
    "approvals": ("approval", "approvals", "pending", "manzoori", "मंज़ूरी", "मंजूरी"),
    "money": ("money", "gst", "settlement", "settlements", "paisa", "पैसा", "सेटलमेंट"),
    "marketing": ("marketing", "poster", "offer", "offers", "campaign", "ऑफर", "पोस्टर"),
    "growth": ("growth", "advisor", "badhao", "ग्रोथ"),
    "chat": ("chat", "ask saathi"),
    "shop": ("my shop", "profile", "settings", "dukaan details", "मेरी दुकान"),
    "privacy": ("privacy", "consent", "प्राइवेसी"),
    "home": ("home", "dashboard", "briefing", "होम", "डैशबोर्ड"),
}
OPEN = re.compile(r"\b(open|go to|goto|take me to|show me the|switch to|navigate to|kholo|khol do|kholiye|dikhao|le chalo|jao)\b|खोलो|खोलिए|खोल दो|दिखाओ|दिखाइए|ले चलो|पर जाओ")
PAGE_WORD = re.compile(r"\b(page|screen|section|tab|panna)\b|पेज|स्क्रीन")


def nav_target(*texts: str) -> str | None:
    """Only an explicit 'open X' (or 'X page') navigates; 'how much stock is left?' is a question for Saathi."""
    for raw in texts:
        t = (raw or "").lower().strip()
        if not t or not (OPEN.search(t) or PAGE_WORD.search(t)):
            continue
        if len(t.split()) > 8:  # a long sentence is a question that happens to contain "show"
            continue
        for tab, words in PAGES.items():
            if any(re.search(r"(?<!\w)" + re.escape(w) + r"(?!\w)", t) for w in words):
                return tab
    return None


# What a voice answer is about -> the page that shows the detail
INTENT_TAB = {"sales": "transactions", "best": "home", "hours": "home", "stock": "stock", "item_info": "stock", "dues": "udhaar",
              "customer_balance": "udhaar", "customers": "customers", "settlements": "money", "gst": "money",
              "credit": "money", "briefing": "home", "close_day": "home"}
