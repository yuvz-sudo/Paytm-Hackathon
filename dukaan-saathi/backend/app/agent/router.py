"""Rule-based fast path: handles routine questions in English / Hinglish / Hindi without an LLM.
This is the deck's "rules and small models handle routine questions" layer, and the offline fallback."""
from __future__ import annotations

import re

from .. import i18n
from ..util import inr, norm, qty_fmt
from . import tools
from .tools import Ctx

NUM = r"(?P<amt>\d[\d,]*(?:\.\d+)?)"
UNITS = r"(?:kg|kgs|pcs|pc|packet|packets|bag|bags|tray|trays|box|boxes|litre|liter|l|dozen|units?)"


def _cands(r: dict) -> str:
    """Candidates to choose from: customers carry a label with the last digits of their phone, items are plain names."""
    return ", ".join(c["label"] if isinstance(c, dict) else str(c) for c in r.get("candidates", []))


def L(lang: str, en: str, hi: str | None = None, hx: str | None = None) -> str:
    lang = i18n.lang_of(lang)
    return {"en": en, "hi": hi or en, "hinglish": hx or en}[lang]


def _n(x: str) -> float:
    return float(x.replace(",", ""))


def detect_language(text: str, default: str) -> str:
    if re.search(r"[ऀ-ॿ]", text):
        return "hi"
    return default


_UNITS = {"ek": 1, "do": 2, "teen": 3, "char": 4, "chaar": 4, "paanch": 5, "panch": 5, "chhe": 6, "che": 6, "saat": 7, "aath": 8, "nau": 9, "das": 10,
          "gyarah": 11, "barah": 12, "pandrah": 15, "bees": 20, "pachees": 25, "tees": 30, "chalis": 40, "pachaas": 50, "saath": 60, "sattar": 70, "assi": 80, "nabbe": 90}
_SPECIAL = {"dedh sau": 150, "dhai sau": 250, "dhai hazaar": 2500, "dedh hazaar": 1500, "saade teen sau": 350, "sawa sau": 125}


def words_to_digits(t: str) -> str:
    """Voice often yields 'paanch sau' / 'do hazaar' for amounts. Convert the common spoken forms."""
    for k, v in _SPECIAL.items():
        t = t.replace(k, str(v))
    def conv(m):
        n = _UNITS[m["u"]]
        return str(n * (100 if m["m"] == "sau" else 1000 if m["m"] in ("hazaar", "hazar") else 100000))
    pat = r"\b(?P<u>" + "|".join(_UNITS) + r")\s+(?P<m>sau|hazaar|hazar|lakh)\b"
    t = re.sub(pat, conv, t)
    t = re.sub(r"\b(\d+)\s+(sau)\b", lambda m: str(int(m[1]) * 100), t)
    t = re.sub(r"\b(\d+)\s+(hazaar|hazar)\b", lambda m: str(int(m[1]) * 1000), t)
    return re.sub(r"\b(sau)\b", "100", t) if re.search(r"\bsau\b", t) and not re.search(r"\d", t) else t


def explicit_period(t: str) -> str | None:
    """Period named in the text, or None (period_of defaults to yesterday, which hides 'no period given')."""
    if re.search(r"\b(today|aaj|kal|yesterday|week|hafte|hafta|saptah|month|mahine|mahina)\b|आज|कल|हफ्ते|हफ़्ते|सप्ताह|महीने|महीना", t):
        return period_of(t)
    return None


def period_of(t: str) -> str:
    if re.search(r"\b(today|aaj)\b|आज", t):
        return "today"
    if re.search(r"\b(week|hafte|hafta|saptah|7 din)\b|हफ्ते|हफ़्ते|सप्ताह", t):
        return "last_7_days"
    if re.search(r"\b(last month|pichle mahine|pichhle mahine)\b|पिछले महीने", t):
        return "last_month"
    if re.search(r"\b(month|mahine|mahina)\b|महीने|महीना", t):
        return "this_month"
    return "yesterday"


# ---------------------------------------------------------------- intent detection
def classify(text: str, has_pending: bool) -> tuple[str, dict]:
    raw = text.strip()
    t = words_to_digits(norm(raw))
    if not t:
        return "empty", {}
    if has_pending and tools.YES.search(raw):
        return "confirm_yes", {}
    if has_pending and tools.NO.search(raw):
        return "confirm_no", {}

    # -- payments checks, payout/fee/chargeback questions (before writes and the generic sales/settlement rules)
    if re.search(r"screenshot|\b(payment|paisa|paise|upi)\s+(aaya|aaye|aa gaya|aa gaye|mila|mil gaya|received|came|credited|hua|show)\b|"
                 r"payment\s+(aaya|mila|received)|पेमेंट\s+(आया|मिला)|पैसे\s+(आए|आया|मिले)|स्क्रीनशॉट", t):
        m_ = re.search(NUM, t)
        return "verify_payment", {"amount": _n(m_["amt"]) if m_ else None}
    if re.search(r"charge ?back|dispute|चार्जबैक|विवाद", t):
        if re.search(r"reply|respond|proof|jawab|bhej|send|submit|sabut|सबूत|जवाब|भेज", t):
            return "chargeback_proof", {}
        return "chargebacks", {}
    if re.search(r"\bmdr\b|upi (fee|charge|charges|shulk)|(fee|charge|charges) (lagega|lagegi|lagenge|kitna)|upi par (fee|charge)|एमडीआर", t):
        return "mdr", {"period": "last_month" if re.search(r"last month|pichle|पिछले", t) else "this_month"}
    if re.search(r"payout|pay out|settlement|settle|bank|khate|deduct|commission|katauti|कटौती|सेटलमेंट|बैंक", t) and \
            re.search(r"\b(why|kyu|kyun|kyon|kam|short|less|lower|kata|kat gaya|kate|cut|explain|breakup|kaise)\b|क्यों|कम|कटा|कटौती", t) and \
            not re.search(r"sales|sale|bikri|बिक्री", t):
        m_ = re.search(NUM, t)
        return "explain_payout", {"amount": _n(m_["amt"]) if m_ else None}

    if re.search(r"\b(ad|advertisement|campaign|poster|promotion|promo)\b.*\b(banao|bana do|banado|create|make|draft|prepare)\b|\b(banao|create|make|draft|prepare)\b.*\b(ad|advertisement|campaign|poster|promotion)\b|विज्ञापन|कैंपेन", t):
        occ = re.search(r"(?:for|ke liye|par|पर)\s+(?:my\s+)?(?:shop\s+)?([a-z\u0900-\u097F ]{3,30}?)(?:\s+(?:ka|ki|ke|ad|advertisement|campaign|poster|offer)\b|$)", t) or \
              re.search(r"\b(diwali|holi|eid|christmas|navratri|raksha bandhan|dussehra|ganesh|onam|pongal|new year|दिवाली|होली)\b", t)
        return "campaign", {"occasion": (occ.group(1) if occ else "special offer").strip(), "discount_pct": _discount(t)}
    if re.search(r"next month|agle mahine|forecast|working capital|cash ?flow (kaisa|next|forecast)|paisa kab (kam|tight)|अगले महीने", t):
        return "forecast", {}
    if re.search(r"refunds? (kitne|how many|kitna)|kitne refunds?|how much (did i )?collect|kitna collect|monthly (report|summary)|finance report|is (month|mahine) (ka )?(report|hisab)", t) and not re.search(r"customer", t):
        return "finance_report", {"period": "last_month" if re.search(r"last month|pichle|पिछले", t) else "this_month"}
    if re.search(r"(new|naye|nae).{0,12}(repeat|purane)|segment|high[- ]?value|best customers|sabse achhe customers|vip customers|nayi? customers?", t):
        return "segments", {}
    if re.search(r"increase (my )?sales|grow (my )?(business|sales)|growth|badhao|badhana|sales badh|business badh|kaise badhe|opportunit|बढ़ाऊं|बढ़ाना|ग्रोथ", t):
        return "growth", {}
    if re.search(r"compare|vs last|last week|pichle hafte|is hafte|this week|week over week|month over month", t) and re.search(r"sales|business|bikri|bikree", t) and re.search(r"compare|vs|better|worse|behtar", t):
        return "compare", {}

    # -- writes first (carry entities)
    m = re.search(rf"(?P<name>[^\d]+?)\s*(?:ji\s*)?(?:ne|ka)\s*{NUM}\s*(?:rs|rupees|rupaye|₹)?\s*(?:rupaye|rupay)?\s*"
                  r"(?:diye|diya|de diye|de diya|chukaya|chuka diya|paid|bheje|bheja|wapas|जमा|दिए|दिया|चुकाया)", t)
    if m and not re.search(r"udhaar likho|udhaar add", t):
        return "payment_received", {"customer": _clean_name(m["name"]), "amount": _n(m["amt"])}
    m = re.search(rf"(?:received|got|collected)\s*{NUM}\s*(?:rs|rupees)?\s*from\s+(?P<name>[\w ]+)", t)
    if m:
        return "payment_received", {"customer": _clean_name(m["name"]), "amount": _n(m["amt"])}
    for rx in (
        rf"(?P<name>[^\d]+?)\s*(?:ji\s*)?(?:ka|ke|ki|ko)\s*{NUM}\s*(?:rs|rupees|rupaye|₹)?\s*(?:ka\s*)?(?:udhaar|credit|उधार)",
        rf"(?:add|put|write|note)\s*{NUM}\s*(?:rs|rupees|₹)?\s*(?:udhaar|credit)?\s*(?:for|to|on)\s+(?P<name>[\w ]+)",
        rf"(?P<name>[\w ]+?)\s*(?:ji\s*)?(?:ko|ka)\s*(?:udhaar|credit)\s*(?:diya|dena|likho)?\s*{NUM}",
    ):
        m = re.search(rx, t)
        if m and re.search(r"udhaar|credit|उधार", t) and re.search(r"likho|add|diya|dena|de do|write|put|note|लिखो|दिया", t):
            return "add_udhaar", {"customer": _clean_name(m["name"]), "amount": _n(m["amt"])}
    m = re.search(rf"(?P<item>[a-zऀ-ॿ][a-zऀ-ॿ ]*?)\s+{NUM}\s*(?P<unit>{UNITS})?\s*(?P<verb>aaya|aayi|aaye|received|came|arrived|added|mila|आया|आई|आए|bacha|bachi|bache|left|remaining|बचा|बची|hai)\b", t)
    if m and not re.search(r"kitna|how much|udhaar|baaki", t):
        verb = m["verb"]
        mode = "add" if verb in ("aaya", "aayi", "aaye", "received", "came", "arrived", "added", "mila", "आया", "आई", "आए") else "set"
        item = re.sub(r"\b(stock|update|mein|me|ka|ki|ke|new|nayi|naya)\b", "", m["item"]).strip()
        if item:
            return "update_stock", {"item": item, "quantity": _n(m["amt"]), "mode": mode}

    # -- specific questions that must win over the generic keyword intents
    m = re.search(r"how much does (?P<name>[a-z ]+?) owe|(?P<name2>[a-z\u0900-\u097F ]+?)\s*(?:ji\s*)?(?:ka|ke|ki|par|pe)\s*(?:kitna|kitni)\s*(?:udhaar|baaki|dena|bakaya)?", t)
    if m and re.search(r"owe|baaki|udhaar|dena|bakaya|बाकी|उधार", t):
        nm = _clean_name(m["name"] or m["name2"] or "")
        if nm and not re.search(r"\b(sales|stock|gst|aaj|kal)\b", nm):
            return "customer_balance", {"customer": nm}
    if re.search(r"\b(why|kyu|kyun|kyon|kaaran|wajah|reason)\b|क्यों|कारण|वजह", t) and re.search(r"sales|sale|bikri|kam|down|drop|dip|low|कम|बिक्री|girawat|gir", t):
        return "explain", {}
    if re.search(r"\b(news|khabar|khabren|samachar|headlines?)\b|खबर|समाचार", t):
        return "news", {}
    if re.search(r"festival|tyohar|tyauhar|diwali|holi|season|shaadi|wedding|kya mangwa|kya mangau|kitna mangwa|stock badha|stock kam kar|"
                 r"what (should|to) (i )?(stock|buy|order)|stock up|discount kis|kis par discount|slow sell|price badh|prices? (rising|going up)|"
                 r"business advice|financial advice|paise ki salah|त्योहार|दिवाली|शादी|सीज़न|क्या मंगवा|छूट किस", t):
        return "season_plan", {}
    if re.search(r"what should i do|kya karun|kya karu|kya karna chahiye|suggest|advice|salah|sujhav|priorit|to ?do|aaj kya karna|क्या करूँ|क्या करूं|सलाह|सुझाव", t):
        return "advice", {}

    # -- reads
    if re.search(r"\b(briefing|summary|haal|good morning|morning|subah)\b|सुप्रभात|ब्रीफिंग|सारांश", t):
        return "briefing", {}
    if re.search(r"\b(close|day end|end of day|din ka hisab|din band|hisab)\b|दिन का हिसाब|दिन खत्म|हिसाब", t):
        return "close_day", {}
    if re.search(r"remind|reminder|yaad dila|tagada|vasooli|collect.*(dues|udhaar)|वसूली|याद दिला|तगादा", t):
        return "remind", {"customer": _after_for(t)}
    if re.search(r"\b(order|reorder|re order|mangwa|mangao|supplier)\b|मंगवा|सप्लायर|ऑर्डर", t):
        return "order", {}
    if re.search(r"udhaar|baaki|bakaya|dues|ledger|owe|outstanding|\bdebts?\b|\bowed\b|\blent\b|loan balance|balance (due|pending)|pending (amount|money|payment)|has to pay|उधार|बकाया|बाकी", t):
        return "dues", {}
    if re.search(r"settlement|payout|bank mein|bank me|paisa nahi aaya|सेटलमेंट|बैंक में", t):
        return "settlements", {}
    if re.search(r"\bgst|gstr|\btax\b|जीएसटी|टैक्स", t):
        return "gst", {"period": "last_month" if re.search(r"last month|pichle|पिछले", t) else "this_month" if re.search(r"this month|is mahine|इस महीने", t) else "last_month"}
    if re.search(r"\bloan\b|credit line|working capital|cash ?flow|cash gap|karz|paisa chahiye|funding|लोन|कर्ज|पैसे चाहिए", t):
        return "credit", {}
    if re.search(r"win ?back|offer|discount|chhoot|chhut|छूट|ऑफर", t):
        return "winback", {"discount_pct": _discount(t)}
    if re.search(r"customer|grahak|regular|lapsed|nahi aaye|ग्राहक|रेगुलर", t):
        return "customers", {}
    if re.search(r"best|top sell|sabse zyada|kya bika|popular|sabse jyada|सबसे ज़्यादा|सबसे ज्यादा|क्या बिका|बेस्ट", t):
        return "best", {"period": period_of(t)}
    if re.search(r"slow|peak|busy|rush|which hour|kaunse ghante|kab|धीमा|भीड़", t):
        return "hours", {}
    if re.search(r"stock|inventory|khatam|maal|saaman|run out|running out|running low|runs out|lacking|short of|finishing|almost over|kam hai|स्टॉक|खत्म|ख़त्म|सामान|माल", t):
        return "stock", {}
    if re.search(r"sales|sale|\bsell\b|\bsold\b|\bselling\b|bikri|bikree|kamai|revenue|collection|income|kitna aaya|earn|बिक्री|कमाई|कलेक्शन|आमदनी", t):
        return "sales", {"period": period_of(t)}
    if re.search(r"\b(help|what can you do|kya kar sakte|madad|options)\b|मदद|क्या कर सकते", t):
        return "help", {}
    if re.search(r"^(hi|hello|hey|namaste|namaskar|नमस्ते|नमस्कार)\b", t):
        return "greet", {}
    return "unknown", {}


def _clean_name(s: str) -> str:
    s = re.sub(r"\b(ji|ka|ke|ki|ko|ne|add|udhaar|credit|for|to|from|mr|mrs|bhai|bhaiya|didi|aunty|uncle)\b", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _after_for(t: str) -> str | None:
    m = re.search(r"(?:remind|reminder|yaad dila(?:o|do)?|tagada|vasooli)\s+(?:to\s+|for\s+|ko\s+)?(?P<n>[a-zऀ-ॿ ]+)", t)
    if m:
        n = _clean_name(re.sub(r"\b(all|sabko|everyone|customers?|dues|udhaar|pending)\b", "", m["n"]))
        return n or None
    return None


def _discount(t: str) -> int:
    m = re.search(r"(\d{1,2})\s*(?:%|percent|pratishat|प्रतिशत)", t)
    return int(m[1]) if m else 10


# ---------------------------------------------------------------- handlers: call tools then render
def handle(ctx: Ctx, intent: str, ent: dict, lang: str) -> str:
    m = ctx.merchant
    run = lambda name, **a: tools.run(ctx, name, a)  # noqa: E731

    def consent_msg(res: dict) -> str | None:
        if res.get("error") == "consent_off":
            return i18n.t(lang, "consent_off", scope=res["scope"])
        if res.get("error") in ("tool_failed", "bad_arguments"):
            return L(lang, "Sorry, something went wrong while fetching that. Please try again.", "क्षमा करें, कुछ गड़बड़ हो गई। कृपया फिर कोशिश करें।",
                     "Maaf kijiye, kuch gadbad ho gayi. Dobara try kijiye.")
        return None

    if intent == "greet":
        return L(lang, f"Hello {m.owner_name.split()[0]}! Ask me about sales, stock, udhaar, GST or say 'briefing'.",
                 f"नमस्ते {m.owner_name.split()[0]} जी! बिक्री, स्टॉक, उधार या GST के बारे में पूछिए, या 'ब्रीफिंग' बोलिए।",
                 f"Namaste {m.owner_name.split()[0]} ji! Sales, stock, udhaar ya GST ke baare mein poochiye, ya 'briefing' boliye.")
    if intent == "help":
        return L(lang, "I can: tell you sales and best sellers, warn about low stock and draft supplier orders, track udhaar and send reminders, "
                       "find lapsed regulars for win-back offers, estimate GST, watch settlements and suggest credit when cash is tight.",
                 "मैं बिक्री, स्टॉक, उधार, GST, सेटलमेंट और क्रेडिट में मदद कर सकता हूँ। कुछ भी पूछिए।",
                 "Main sales, stock, udhaar, GST, settlement aur credit mein madad kar sakta hoon. Kuch bhi poochiye.")
    if intent == "empty":
        return L(lang, "I didn't catch that. Please say it again.", "मैं समझ नहीं पाया। कृपया फिर से बोलिए।", "Samajh nahi aaya. Phir se boliye.")
    if intent == "unknown":
        return L(lang, "I'm not sure I understood. You can ask about sales, stock, udhaar, customers, GST, settlements or credit.",
                 "मैं पूरी तरह समझ नहीं पाया। बिक्री, स्टॉक, उधार, ग्राहक, GST, सेटलमेंट या क्रेडिट के बारे में पूछिए।",
                 "Poori tarah samajh nahi paaya. Sales, stock, udhaar, customers, GST, settlement ya credit ke baare mein poochiye.")

    if intent == "advice":
        b = run("get_daily_briefing")
        if e := consent_msg(b):
            return e
        top = [c for c in b["cards"] if c["severity"] in ("high", "medium")][:3] or b["cards"][:3]
        if not top:
            return i18n.t(lang, "all_good")
        lines = "; ".join(f"{i + 1}) {c['title']}: {c['detail']}" for i, c in enumerate(top))
        return L(lang, f"Here is what I'd do first: {lines}.", f"सबसे पहले ये करें: {lines}।", f"Sabse pehle yeh kijiye: {lines}.")

    if intent == "explain":
        x = run("explain_sales_change")
        if e := consent_msg(x):
            return e
        if x.get("no_data"):
            return L(lang, "I need payments from both days to compare. Not enough data yet.", "तुलना के लिए दोनों दिनों का डेटा चाहिए।", "Tulna ke liye dono din ka data chahiye.")
        up = (x["change_pct"] or 0) >= 0
        pct = abs(round(x["change_pct"] or 0))
        wd = i18n.weekday(lang, x["weekday"])
        head = L(lang, f"{x['weekday']}'s sales were {inr(x['total'])}, {pct}% {'above' if up else 'below'} last {x['weekday']} ({inr(x['ref_total'])}).",
                 f"{wd} की बिक्री {inr(x['total'])} रही, पिछले {wd} से {pct}% {'ज़्यादा' if up else 'कम'} ({inr(x['ref_total'])})।",
                 f"{wd} ki sales {inr(x['total'])} rahi, pichle {wd} se {pct}% {'zyada' if up else 'kam'} ({inr(x['ref_total'])}).")
        pc, tc = x["payments_change_pct"] or 0, x["ticket_change_pct"] or 0
        why = L(lang, f" Main reason: {'fewer customers' if x['driver'] == 'footfall' and pc < 0 else 'more customers' if x['driver'] == 'footfall' else 'smaller bills' if tc < 0 else 'bigger bills'} "
                      f"(payments {x['payments']} vs {x['ref_payments']}, average bill {inr(x['avg_ticket'])} vs {inr(x['ref_avg_ticket'])}).",
                f" मुख्य कारण: {'कम ग्राहक' if x['driver'] == 'footfall' and pc < 0 else 'ज़्यादा ग्राहक' if x['driver'] == 'footfall' else 'छोटे बिल' if tc < 0 else 'बड़े बिल'} "
                f"(भुगतान {x['payments']} बनाम {x['ref_payments']}, औसत बिल {inr(x['avg_ticket'])} बनाम {inr(x['ref_avg_ticket'])})।",
                f" Mukhya wajah: {'kam customers' if x['driver'] == 'footfall' and pc < 0 else 'zyada customers' if x['driver'] == 'footfall' else 'chhote bill' if tc < 0 else 'bade bill'} "
                f"(payments {x['payments']} vs {x['ref_payments']}, average bill {inr(x['avg_ticket'])} vs {inr(x['ref_avg_ticket'])}).")
        extra = ""
        if x["item_swings"]:
            sw = ", ".join(f"{i['item']} ({'+' if i['delta'] > 0 else '-'}{inr(abs(i['delta']))})" for i in x["item_swings"][:2])
            extra += L(lang, f" Biggest item changes: {sw}.", f" सबसे ज़्यादा बदलाव: {sw}।", f" Sabse zyada badlav: {sw}.")
        if x["hour_swings"]:
            h = x["hour_swings"][0]
            hh = f"{h['hour'] % 12 or 12}{'am' if h['hour'] < 12 else 'pm'}"
            extra += L(lang, f" Biggest hourly swing around {hh}.", f" सबसे बड़ा बदलाव लगभग {hh} पर।", f" Sabse bada badlav lagbhag {hh} par.")
        from ..services import calendar as _cal
        past = _cal.recent(ctx.merchant.segment, 10) if not up else []
        if past:
            extra += L(lang, f" This follows {past[0]['name']}, so a dip is expected.", f" यह {past[0]['name']} के बाद है, इसलिए गिरावट स्वाभाविक है।", f" Yeh {past[0]['name']} ke baad hai, isliye girawat swaabhaavik hai.")
        if x["failed"] > x["ref_failed"] + 1:
            extra += L(lang, f" Also {x['failed']} payments failed (vs {x['ref_failed']}).", f" साथ ही {x['failed']} भुगतान विफल हुए।", f" Saath hi {x['failed']} payments fail hue.")
        return head + why + extra

    if intent == "customer_balance":
        r = run("get_customer_balance", customer=ent["customer"])
        if e := consent_msg(r):
            return e
        if not r.get("ok"):
            if r["error"] == "ambiguous_customer":
                return L(lang, "Which customer: " + _cands(r) + "?", "कौन सा ग्राहक: " + _cands(r) + "?", "Kaun sa customer: " + _cands(r) + "?")
            return L(lang, f"I couldn't find '{ent['customer']}'.", f"'{ent['customer']}' नहीं मिला।", f"'{ent['customer']}' nahi mila.")
        if r["outstanding"] <= 0:
            return L(lang, f"{r['customer']} has nothing pending.", f"{r['customer']} पर कुछ बाकी नहीं।", f"{r['customer']} par kuch baaki nahi.")
        out = L(lang, f"{r['customer']} owes {inr(r['outstanding'])}, oldest due {r['oldest_days']} days ago.", f"{r['customer']} पर {inr(r['outstanding'])} बाकी है, सबसे पुराना {r['oldest_days']} दिन पुराना।",
                f"{r['customer']} par {inr(r['outstanding'])} baaki hai, sabse purana {r['oldest_days']} din purana.")
        if r["overdue"]:
            out += L(lang, f" {inr(r['overdue'])} is overdue. Shall I send a reminder?", f" {inr(r['overdue'])} की तारीख निकल चुकी है। रिमाइंडर भेजूँ?", f" {inr(r['overdue'])} ki date nikal chuki hai. Reminder bhejoon?")
        return out

    if intent == "item_info":
        r = run("get_item_report", item=ent["item"])
        if e := consent_msg(r):
            return e
        if not r.get("ok"):
            return L(lang, f"I couldn't find '{ent['item']}'.", f"'{ent['item']}' नहीं मिला।", f"'{ent['item']}' nahi mila.")
        q = qty_fmt
        out = L(lang, f"{r['item']}: sold {q(r['qty_7d'])} {r['unit']} ({inr(r['revenue_7d'])}) in the last 7 days",
                f"{r['item']}: पिछले 7 दिन में {q(r['qty_7d'])} {r['unit']} बिका ({inr(r['revenue_7d'])})", f"{r['item']}: pichle 7 din mein {q(r['qty_7d'])} {r['unit']} bika ({inr(r['revenue_7d'])})")
        if r["trend_pct"] is not None:
            out += L(lang, f", {abs(r['trend_pct'])}% {'up' if r['trend_pct'] >= 0 else 'down'} on the week before.", f", पिछले हफ्ते से {abs(r['trend_pct'])}% {'ज़्यादा' if r['trend_pct'] >= 0 else 'कम'}।",
                     f", pichle hafte se {abs(r['trend_pct'])}% {'zyada' if r['trend_pct'] >= 0 else 'kam'}.")
        else:
            out += "."
        st = r.get("stock")
        if st and st.get("current_stock") is not None:
            out += L(lang, f" Estimated stock {q(st['current_stock'])} {r['unit']}" + (f", about {st['days_left']:.0f} days left." if st.get("days_left") is not None else "."),
                     f" अनुमानित स्टॉक {q(st['current_stock'])} {r['unit']}" + (f", लगभग {st['days_left']:.0f} दिन चलेगा।" if st.get("days_left") is not None else "।"),
                     f" Anumaanit stock {q(st['current_stock'])} {r['unit']}" + (f", lagbhag {st['days_left']:.0f} din chalega." if st.get("days_left") is not None else "."))
            if st["status"] in ("out", "critical", "low"):
                out += " " + i18n.t(lang, "offer_order")
        elif st and st["status"] == "unknown":
            out += L(lang, " I don't have a stock count for it; tell me how much is left.", " इसका स्टॉक मुझे नहीं पता; बताइए कितना बचा है।", " Iska stock mujhe nahi pata; batayiye kitna bacha hai.")
        return out

    if intent == "briefing":
        b = run("get_daily_briefing")
        return consent_msg(b) or b["script"]

    if intent == "close_day":
        s = run("get_sales_summary", period="today")
        if e := consent_msg(s):
            return e
        d = run("get_udhaar_dues")
        st = run("get_stock_status", only_risky=True)
        lines = [L(lang, f"Today so far: {inr(s['total'])} from {s['payments']} payments.", f"आज अब तक: {inr(s['total'])}, {s['payments']} भुगतान।",
                   f"Aaj ab tak: {inr(s['total'])}, {s['payments']} payments.")]
        if not d.get("error"):
            lines.append(i18n.t(lang, "dues", n=d["count"], total=inr(d["total_outstanding"])) if d["count"] else i18n.t(lang, "no_dues"))
        if not st.get("error") and st["items"]:
            names = ", ".join(f"{r['item']}" + (f" ({qty_fmt(r['suggested_qty'])} {r['unit']})" if r.get("suggested_qty") else "") for r in st["items"][:5])
            lines.append(L(lang, f"Tomorrow's stock list: {names}.", f"कल की स्टॉक सूची: {names}।", f"Kal ki stock list: {names}."))
            lines.append(i18n.t(lang, "offer_order"))
        return " ".join(lines)

    if intent == "sales":
        s = run("get_sales_summary", period=ent.get("period", "yesterday"))
        if e := consent_msg(s):
            return e
        label = {"today": ("today", "आज", "aaj"), "yesterday": ("yesterday", "कल", "kal"), "last_7_days": ("the last 7 days", "पिछले 7 दिन", "pichle 7 din"),
                 "this_month": ("this month", "इस महीने", "is mahine"), "last_month": ("last month", "पिछले महीने", "pichle mahine"),
                 "last_30_days": ("the last 30 days", "पिछले 30 दिन", "pichle 30 din")}.get(s["period"], (s["period"],) * 3)
        if s["no_data"]:
            return L(lang, f"No payments recorded for {label[0]}.", f"{label[1]} कोई भुगतान दर्ज नहीं हुआ।", f"{label[2]} koi payment record nahi hua.")
        out = L(lang, f"Sales for {label[0]}: {inr(s['total'])} from {s['payments']} payments (average {inr(s['avg_ticket'])}).",
                f"{label[1]} की बिक्री: {inr(s['total'])}, {s['payments']} भुगतान (औसत {inr(s['avg_ticket'])})।",
                f"{label[2]} ki sales: {inr(s['total'])}, {s['payments']} payments (average {inr(s['avg_ticket'])}).")
        if s["change_pct"] is not None and s["period"] != "today":
            suffix = "" if s["period"] == "yesterday" else "_p"
            out += " " + i18n.t(lang, ("vs_up" if s["change_pct"] >= 0 else "vs_down") + suffix, pct=abs(round(s["change_pct"])))
        if s["failed_count"]:
            out += L(lang, f" {s['failed_count']} payments failed.", f" {s['failed_count']} भुगतान विफल हुए।", f" {s['failed_count']} payments fail hue.")
        if s["refund_count"]:
            out += L(lang, f" {s['refund_count']} refunds ({inr(s['refund_amount'])}).", f" {s['refund_count']} रिफंड ({inr(s['refund_amount'])})।",
                     f" {s['refund_count']} refunds ({inr(s['refund_amount'])}).")
        if s["period"] in ("yesterday", "last_7_days", "this_month", "last_month"):
            bs = run("get_best_sellers", period=s["period"], limit=1)
            if bs.get("items"):
                out += L(lang, f" Top seller: {bs['items'][0]['item']}.", f" सबसे ज़्यादा बिका: {bs['items'][0]['item']}।", f" Sabse zyada bika: {bs['items'][0]['item']}.")
        if s["period"] == "yesterday" and (s["change_pct"] or 0) <= -20:
            out += L(lang, " That's a clear dip. Ask me 'why' to see what changed.", " यह साफ गिरावट है। 'क्यों' पूछिए, मैं कारण बताऊँगा।", " Yeh saaf girawat hai. 'Kyun' poochiye, main wajah bataunga.")
        if s["period"] == "today":
            out += L(lang, " (day still in progress)", " (दिन अभी जारी है)", " (din abhi chal raha hai)")
        return out

    if intent == "best":
        b = run("get_best_sellers", period=ent.get("period", "last_7_days"))
        if e := consent_msg(b):
            return e
        if b["no_data"]:
            return L(lang, "I don't have itemised sales for that period yet. Bill through Paytm to see best sellers.",
                     "उस अवधि का आइटम-वार डेटा अभी नहीं है। बेस्ट सेलर देखने के लिए Paytm से बिल बनाइए।",
                     "Us period ka item-wise data abhi nahi hai. Best seller dekhne ke liye Paytm se bill banaiye.")
        top = ", ".join(f"{r['item']} ({inr(r['revenue'])})" for r in b["items"][:3])
        out = L(lang, f"Best sellers: {top}.", f"सबसे ज़्यादा बिके: {top}।", f"Sabse zyada bike: {top}.")
        if b["slow_items"]:
            out += L(lang, " Slow movers: " + ", ".join(r["item"] for r in b["slow_items"]) + ".",
                     " धीमे बिकने वाले: " + ", ".join(r["item"] for r in b["slow_items"]) + "।",
                     " Slow bikne wale: " + ", ".join(r["item"] for r in b["slow_items"]) + ".")
        if b["coverage_pct"] < 90:
            out += L(lang, f" (Based on {b['coverage_pct']}% of payments that had item details.)", f" ({b['coverage_pct']}% भुगतान के आइटम विवरण के आधार पर।)",
                     f" ({b['coverage_pct']}% payments ke item details ke aadhaar par.)")
        return out

    if intent == "hours":
        h = run("get_hourly_insights")
        if e := consent_msg(h):
            return e
        if h["no_data"]:
            return L(lang, "Not enough data yet.", "अभी पर्याप्त डेटा नहीं है।", "Abhi kaafi data nahi hai.")
        fmt = lambda hr: f"{hr % 12 or 12}{'am' if hr < 12 else 'pm'}"  # noqa: E731
        peak = ", ".join(fmt(x) for x in h["peak_hours"])
        slow = ", ".join(fmt(x) for x in (h["slow_hours"] or h["quietest_hours"]))
        return L(lang, f"Your busiest hours are {peak}. Quietest: {slow}. A small offer in the quiet hours can fill them.",
                 f"सबसे व्यस्त समय: {peak}। सबसे शांत: {slow}। शांत समय में छोटा ऑफर दे सकते हैं।",
                 f"Sabse busy time: {peak}. Sabse shaant: {slow}. Shaant time mein chhota offer de sakte hain.")

    if intent == "stock":
        st = run("get_stock_status", only_risky=True)
        if e := consent_msg(st):
            return e
        if not st["tracks_stock"]:
            return L(lang, "Your shop has no stock-tracked items (services only).", "आपकी दुकान में स्टॉक-ट्रैक वाले आइटम नहीं हैं।", "Aapki dukaan mein stock-tracked items nahi hain.")
        if not st["items"]:
            return L(lang, "Stock looks fine for now. Nothing is about to run out.", "अभी स्टॉक ठीक है, कुछ भी खत्म होने वाला नहीं।", "Abhi stock theek hai, kuch khatam hone wala nahi.")
        parts = []
        for r in st["items"][:5]:
            if r["status"] == "out":
                parts.append(L(lang, f"{r['item']} (out)", f"{r['item']} (खत्म)", f"{r['item']} (khatam)"))
            else:
                parts.append(L(lang, f"{r['item']} (~{r['days_left']:.0f} days)", f"{r['item']} (~{r['days_left']:.0f} दिन)", f"{r['item']} (~{r['days_left']:.0f} din)"))
        out = L(lang, "Running low: " + ", ".join(parts) + ".", "कम स्टॉक: " + ", ".join(parts) + "।", "Kam stock: " + ", ".join(parts) + ".")
        return out + " " + i18n.t(lang, "offer_order")

    if intent == "update_stock":
        r = run("update_stock", item=ent["item"], quantity=ent["quantity"], mode=ent["mode"])
        if e := consent_msg(r):
            return e
        if r.get("ok"):
            return L(lang, f"Updated. {r['text']}.", f"अपडेट हो गया। {r['text']}।", f"Update ho gaya. {r['text']}.")
        err = r["error"]
        if err == "ambiguous_item":
            return L(lang, "Which one: " + _cands(r) + "?", "कौन सा: " + _cands(r) + "?", "Kaun sa: " + _cands(r) + "?")
        if err == "item_not_found":
            return L(lang, f"I couldn't find '{ent['item']}' in your items.", f"'{ent['item']}' आपके आइटम में नहीं मिला।", f"'{ent['item']}' aapke items mein nahi mila.")
        if err == "item_not_stock_tracked":
            return L(lang, f"{r['item']} isn't stock-tracked.", f"{r['item']} का स्टॉक ट्रैक नहीं होता।", f"{r['item']} ka stock track nahi hota.")
        return L(lang, "That quantity doesn't look right.", "यह मात्रा सही नहीं लग रही।", "Yeh quantity sahi nahi lag rahi.")

    if intent == "order":
        r = run("propose_supplier_order")
        if e := consent_msg(r):
            return e
        if not r.get("ok"):
            return {"nothing_to_order": L(lang, "Nothing needs ordering right now.", "अभी कुछ ऑर्डर करने की ज़रूरत नहीं।", "Abhi kuch order karne ki zaroorat nahi."),
                    "no_supplier_contact": L(lang, "I don't have a supplier contact for these items: " + ", ".join(r.get("items", [])),
                                             "इन आइटम के लिए सप्लायर का नंबर नहीं है: " + ", ".join(r.get("items", [])),
                                             "In items ke liye supplier ka number nahi hai: " + ", ".join(r.get("items", [])))}.get(r.get("error"), "—")
        titles = "; ".join(p["title"] for p in r["proposals"])
        return L(lang, f"Drafted: {titles}. Shall I send? (yes/no)", f"ड्राफ्ट तैयार: {titles}। भेज दूँ? (हाँ/नहीं)", f"Draft ready: {titles}. Bhej doon? (haan/nahi)")

    if intent == "dues":
        d = run("get_udhaar_dues")
        if e := consent_msg(d):
            return e
        if not d["count"]:
            return i18n.t(lang, "no_dues")
        top = ", ".join(f"{r['name']} {inr(r['outstanding'])}" for r in d["customers"][:3])
        return i18n.t(lang, "dues", n=d["count"], total=inr(d["total_outstanding"])) + L(
            lang, f" Biggest overdue: {top}. Want me to draft reminders?", f" सबसे ज़्यादा बकाया: {top}। रिमाइंडर भेजूँ?", f" Sabse zyada baaki: {top}. Reminder bhejoon?")

    if intent == "add_udhaar":
        r = run("add_udhaar", customer=ent["customer"], amount=ent["amount"])
        if e := consent_msg(r):
            return e
        if r.get("ok"):
            return L(lang, f"Noted {inr(r['added'])} udhaar for {r['customer']}. Total due: {inr(r['balance'])}.",
                     f"{r['customer']} के नाम {inr(r['added'])} उधार लिख लिया। कुल बकाया: {inr(r['balance'])}।",
                     f"{r['customer']} ke naam {inr(r['added'])} udhaar likh liya. Kul baaki: {inr(r['balance'])}.")
        if r["error"] == "ambiguous_customer":
            return L(lang, "Which customer: " + _cands(r) + "?", "कौन सा ग्राहक: " + _cands(r) + "?", "Kaun sa customer: " + _cands(r) + "?")
        if r["error"] == "customer_not_found":
            return L(lang, f"I don't have a customer named '{ent['customer']}'. Tell me the full name to add them.",
                     f"'{ent['customer']}' नाम का ग्राहक नहीं मिला। जोड़ने के लिए पूरा नाम बताइए।",
                     f"'{ent['customer']}' naam ka customer nahi mila. Jodne ke liye poora naam batayiye.")
        return L(lang, "That amount doesn't look right.", "यह रकम सही नहीं लग रही।", "Yeh amount sahi nahi lag raha.")

    if intent == "payment_received":
        r = run("record_udhaar_payment", customer=ent["customer"], amount=ent["amount"])
        if e := consent_msg(r):
            return e
        if r.get("ok"):
            return L(lang, f"Recorded {inr(r['received'])} from {r['customer']}. Remaining: {inr(r['balance'])}.",
                     f"{r['customer']} से {inr(r['received'])} मिले। बाकी: {inr(r['balance'])}।",
                     f"{r['customer']} se {inr(r['received'])} mile. Baaki: {inr(r['balance'])}.")
        er = r["error"]
        if er == "exceeds_balance":
            return L(lang, f"{r['customer']} only owes {inr(r['balance'])}, which is less than that.", f"{r['customer']} पर सिर्फ {inr(r['balance'])} बाकी है।", f"{r['customer']} par sirf {inr(r['balance'])} baaki hai.")
        if er == "nothing_due":
            return L(lang, f"{r['customer']} has nothing pending.", f"{r['customer']} पर कुछ बाकी नहीं है।", f"{r['customer']} par kuch baaki nahi hai.")
        if er == "ambiguous_customer":
            return L(lang, "Which customer: " + _cands(r) + "?", "कौन सा ग्राहक: " + _cands(r) + "?", "Kaun sa customer: " + _cands(r) + "?")
        if er == "customer_not_found":
            return L(lang, f"I couldn't find '{ent['customer']}'.", f"'{ent['customer']}' नहीं मिला।", f"'{ent['customer']}' nahi mila.")
        return L(lang, "That amount doesn't look right.", "यह रकम सही नहीं लग रही।", "Yeh amount sahi nahi lag raha.")

    if intent == "remind":
        r = run("propose_udhaar_reminders", customer=ent.get("customer"))
        if e := consent_msg(r):
            return e
        if not r.get("ok"):
            er = r["error"]
            if er == "nothing_due":
                return i18n.t(lang, "no_dues")
            if er == "ambiguous_customer":
                return L(lang, "Which customer: " + _cands(r) + "?", "कौन सा ग्राहक?", "Kaun sa customer?")
            return L(lang, "I couldn't find that customer.", "वह ग्राहक नहीं मिला।", "Woh customer nahi mila.")
        if not r["proposals"]:
            return L(lang, "No reminders to send right now (nobody is overdue, or contact details are missing).", "अभी कोई रिमाइंडर नहीं भेजना है।", "Abhi koi reminder nahi bhejna hai.")
        titles = "; ".join(p["title"] for p in r["proposals"])
        return L(lang, f"Drafted {len(r['proposals'])} reminder(s): {titles}. Send them? (yes/no)", f"{len(r['proposals'])} रिमाइंडर तैयार: {titles}। भेज दूँ? (हाँ/नहीं)",
                 f"{len(r['proposals'])} reminder ready: {titles}. Bhej doon? (haan/nahi)")

    if intent == "customers":
        c = run("get_customer_insights")
        if e := consent_msg(c):
            return e
        if not c["lapsed"]:
            return L(lang, f"{c['repeat_30d']} customers came back more than once this month. No regulars have gone missing.",
                     f"इस महीने {c['repeat_30d']} ग्राहक एक से ज़्यादा बार आए। कोई नियमित ग्राहक गायब नहीं है।",
                     f"Is mahine {c['repeat_30d']} customers ek se zyada baar aaye. Koi regular gaayab nahi hai.")
        names = ", ".join(r["name"] for r in c["lapsed"][:3])
        return i18n.t(lang, "lapsed", n=len(c["lapsed"])) + L(lang, f" Including {names}. Want to send them a win-back offer?", f" जैसे {names}। ऑफर भेजें?", f" Jaise {names}. Offer bhejein?")

    if intent == "winback":
        r = run("propose_winback_offer", discount_pct=ent.get("discount_pct", 10))
        if e := consent_msg(r):
            return e
        if not r.get("ok"):
            if r["error"] == "no_lapsed_customers":
                return L(lang, "No lapsed regulars to target right now.", "अभी कोई नियमित ग्राहक छूटा नहीं है।", "Abhi koi regular chhoota nahi hai.")
            return L(lang, "That discount doesn't look right.", "यह छूट सही नहीं लग रही।", "Yeh discount sahi nahi lag raha.")
        extra = L(lang, f" (capped at your {r['cap_pct']}% limit)", f" (आपकी {r['cap_pct']}% सीमा तक)", f" (aapki {r['cap_pct']}% limit tak)") if r["discount_capped"] else ""
        w = r.get("window")
        wl = (L(lang, f" Timed for your quiet slot, {w['label']} {w['when']}.", f" आपके शांत समय, {w['label']} ({'आज' if w['when'] == 'today' else 'कल'}) के लिए।",
                f" Aapke quiet time, {w['label']} ({'aaj' if w['when'] == 'today' else 'kal'}) ke liye.") if w else "")
        return L(lang, f"Drafted a {r['discount_pct']}% offer{extra} for {r['recipients']} lapsed regulars.{wl} Send? (yes/no)",
                 f"{r['recipients']} छूटे हुए ग्राहकों के लिए {r['discount_pct']}% का ऑफर तैयार{extra}।{wl} भेज दूँ? (हाँ/नहीं)",
                 f"{r['recipients']} chhoote hue customers ke liye {r['discount_pct']}% ka offer ready{extra}.{wl} Bhej doon? (haan/nahi)")

    if intent == "gst":
        g = run("get_gst_summary", period=ent.get("period", "last_month"))
        if e := consent_msg(g):
            return e
        if g.get("no_data"):
            return L(lang, "No payments in that period.", "उस अवधि में कोई भुगतान नहीं।", "Us period mein koi payment nahi.")
        if not g["registered"]:
            msg = L(lang, f"You are not GST-registered. Annualised turnover is about {inr(g['annualised_turnover'])} against the {inr(g['registration_threshold'])} limit.",
                    f"आप GST पंजीकृत नहीं हैं। अनुमानित वार्षिक टर्नओवर {inr(g['annualised_turnover'])}, सीमा {inr(g['registration_threshold'])}।",
                    f"Aap GST registered nahi hain. Anumaanit saalana turnover {inr(g['annualised_turnover'])}, limit {inr(g['registration_threshold'])}.")
            if g.get("threshold_crossed"):
                msg += L(lang, " You may need to register soon. Please check with your CA.", " जल्द पंजीकरण ज़रूरी हो सकता है। CA से पूछिए।", " Jaldi registration zaroori ho sakta hai. CA se poochiye.")
            return msg
        d1, d3 = g["days_to_gstr1"], g["days_to_gstr3b"]
        due = lambda n, d: (L(lang, f"{n} due in {d} days", f"{n} {d} दिन में", f"{n} {d} din mein") if d > 0 else L(lang, f"{n} due today", f"{n} आज है", f"{n} aaj hai") if d == 0 else  # noqa: E731
                            L(lang, f"{n} was due {-d} days ago (please confirm it is filed)", f"{n} {-d} दिन पहले था (फाइल हुआ या नहीं जाँचें)", f"{n} {-d} din pehle tha (file hua ya nahi check karein)"))
        out = L(lang, f"Turnover {inr(g['turnover'])}; estimated GST collected {inr(g['estimated_tax'])}. ",
                f"टर्नओवर {inr(g['turnover'])}; अनुमानित GST {inr(g['estimated_tax'])}। ", f"Turnover {inr(g['turnover'])}; anumaanit GST {inr(g['estimated_tax'])}. ") + f"{due('GSTR-1', d1)}; {due('GSTR-3B', d3)}."
        if g.get("unallocated_note"):
            out += L(lang, f" Note: {inr(g['unallocated_sales'])} of sales had no item details.", f" ध्यान दें: {inr(g['unallocated_sales'])} की बिक्री में आइटम विवरण नहीं था।", f" Dhyan dein: {inr(g['unallocated_sales'])} ki sales mein item detail nahi tha.")
        return out + L(lang, " (Estimate only; confirm with your CA.)", " (केवल अनुमान; CA से पुष्टि करें।)", " (Sirf anumaan; CA se confirm karein.)")

    if intent == "campaign":
        r = run("propose_campaign", occasion=ent.get("occasion", "special offer").title(), discount_pct=ent.get("discount_pct", 10))
        if e := consent_msg(r):
            return e
        if not r.get("ok"):
            return L(lang, "I couldn't find customers to send a campaign to yet.", "अभी भेजने के लिए कोई ग्राहक नहीं मिला।", "Abhi bhejne ke liye koi customer nahi mila.")
        c = r["campaign"]
        cap = L(lang, f" (capped at your {r['cap_pct']}% limit)", f" (आपकी {r['cap_pct']}% सीमा तक)", f" (aapki {r['cap_pct']}% limit tak)") if r["discount_capped"] else ""
        return L(lang, f"Drafted '{c['title']}'{cap} for {c['recipient_count']} customers. You can add a poster on the Marketing page. Send the message? (yes/no)",
                 f"'{c['title']}'{cap} {c['recipient_count']} ग्राहकों के लिए तैयार। पोस्टर Marketing पेज पर बना सकते हैं। मैसेज भेज दूँ? (हाँ/नहीं)",
                 f"'{c['title']}'{cap} {c['recipient_count']} customers ke liye ready. Poster Marketing page par bana sakte hain. Message bhej doon? (haan/nahi)")

    if intent == "segments":
        r = run("get_customer_segments")
        if e := consent_msg(r):
            return e
        if r.get("no_data"):
            return L(lang, "No identified customers yet. Segments appear once customers pay through Paytm repeatedly.", "अभी कोई पहचाने हुए ग्राहक नहीं हैं।", "Abhi koi pehchane hue customers nahi hain.")
        return r["summary"] + L(lang, " Want me to draft an offer for one of these groups?", " किसी समूह के लिए ऑफर तैयार करूँ?", " Kisi group ke liye offer ready karoon?")

    if intent == "finance_report":
        r = run("get_finance_report", period=ent.get("period", "this_month"))
        if e := consent_msg(r):
            return e
        if r.get("no_data"):
            return L(lang, "No payments in that period yet.", "इस अवधि में कोई भुगतान नहीं है।", "Is period mein koi payment nahi hai.")
        hl = " ".join(r["highlights"][:3])
        return hl + (L(lang, " (Month so far, not complete yet.)", " (महीना अभी पूरा नहीं हुआ।)", " (Mahina abhi poora nahi hua.)") if r["partial"] else "")

    if intent == "forecast":
        f = run("get_cashflow_forecast")
        if e := consent_msg(f):
            return e
        if f.get("no_data"):
            return L(lang, "I need about four weeks of payments to forecast. Not enough history yet.", "अनुमान के लिए करीब चार हफ्ते का डेटा चाहिए।", "Anumaan ke liye lagbhag chaar hafte ka data chahiye.")
        c = f["collections"]
        tail = ""
        if f["crunch"] or f["crunch_if_low"]:
            k = f["crunch"] or f["crunch_if_low"]
            tail = L(lang, f" Cash may get tight around {k['date']}: bills could exceed sales by about {inr(k['shortfall'])}. Indicative working capital need: {inr(f['working_capital_needed'] or k['shortfall'])}.",
                     f" {k['date']} के आसपास नकदी तंग हो सकती है: बिल बिक्री से लगभग {inr(k['shortfall'])} ज़्यादा हो सकते हैं।",
                     f" {k['date']} ke aaspaas cash tight ho sakta hai: bill sales se lagbhag {inr(k['shortfall'])} zyada ho sakte hain.")
        return L(lang, f"Next 30 days I expect about {inr(c['likely'])} in collections (range {inr(c['low'])} to {inr(c['high'])}) against {inr(f['bills_total'])} of recorded bills.{tail} This is an estimate.",
                 f"अगले 30 दिनों में लगभग {inr(c['likely'])} कलेक्शन ({inr(c['low'])} से {inr(c['high'])}), और {inr(f['bills_total'])} के बिल।{tail} यह अनुमान है।",
                 f"Agle 30 din mein lagbhag {inr(c['likely'])} collection ({inr(c['low'])} se {inr(c['high'])}), aur {inr(f['bills_total'])} ke bill.{tail} Yeh anumaan hai.")

    if intent == "growth":
        g = run("get_growth_advice")
        if e := consent_msg(g):
            return e
        if g.get("no_data"):
            return L(lang, "I need about two weeks of payments to find reliable growth patterns.", "भरोसेमंद सुझाव के लिए करीब दो हफ्ते का डेटा चाहिए।", "Bharosemand suggestion ke liye lagbhag do hafte ka data chahiye.")
        top = g["opportunities"][:2]
        txt = " ".join(f"{i + 1}) {o['title']}: {o['detail']}" for i, o in enumerate(top))
        if g["biggest_problem"]:
            p_ = g["biggest_problem"]
            txt += L(lang, f" Biggest problem: {p_['title']} ({p_['detail']})", f" सबसे बड़ी समस्या: {p_['title']} ({p_['detail']})", f" Sabse badi problem: {p_['title']} ({p_['detail']})")
        return txt or L(lang, "No clear growth gaps right now.", "अभी कोई बड़ी कमी नहीं दिख रही।", "Abhi koi badi kami nahi dikh rahi.")

    if intent == "compare":
        c = run("compare_periods")
        if e := consent_msg(c):
            return e
        w = c["week"]
        if c.get("no_data") or w["change_pct"] is None:
            return L(lang, "Not enough data to compare weeks yet.", "हफ्तों की तुलना के लिए डेटा काफी नहीं है।", "Hafton ki tulna ke liye data kaafi nahi hai.")
        up = w["change_pct"] >= 0
        return L(lang, f"Last 7 days: {inr(w['current'])}, {abs(w['change_pct'])}% {'above' if up else 'below'} the 7 before ({inr(w['previous'])}).",
                 f"पिछले 7 दिन: {inr(w['current'])}, पिछले 7 दिनों ({inr(w['previous'])}) से {abs(w['change_pct'])}% {'ज़्यादा' if up else 'कम'}।",
                 f"Pichle 7 din: {inr(w['current'])}, pehle ke 7 din ({inr(w['previous'])}) se {abs(w['change_pct'])}% {'zyada' if up else 'kam'}.")

    if intent == "explain_payout":
        r = run("explain_settlement", amount=ent.get("amount")) if ent.get("amount") else run("explain_settlement")
        if e := consent_msg(r):
            return e
        if not r.get("ok"):
            return L(lang, "I couldn't find a settlement to explain yet." if r.get("error") != "not_found" else "I couldn't find a payout of that amount.",
                     "अभी समझाने के लिए कोई सेटलमेंट नहीं मिला।" if r.get("error") != "not_found" else "इस रकम का कोई पेआउट नहीं मिला।",
                     "Abhi samjhane ke liye koi settlement nahi mila." if r.get("error") != "not_found" else "Is amount ka koi payout nahi mila.")
        from ..services import settlements as _st
        return _st.summarize(r, lang) + L(lang, f" (Settlement of {r['settlement']['expected_date']}.)", f" ({r['settlement']['expected_date']} का सेटलमेंट।)",
                                          f" ({r['settlement']['expected_date']} ka settlement.)")

    if intent == "chargebacks":
        c = run("get_chargebacks")
        if e := consent_msg(c):
            return e
        open_ = [x for x in c["chargebacks"] if x["status"] == "open"]
        if not open_:
            return L(lang, "No chargebacks are open. Nothing to send.", "कोई चार्जबैक खुला नहीं है।", "Koi chargeback open nahi hai.")
        x = open_[0]
        late = x["days_left"] < 0
        return L(lang, f"{len(open_)} open chargeback(s) worth {inr(c['open_amount'])}. "
                       + (f"The proof deadline for {inr(x['amount'])} has passed." if late else f"Send proof for {inr(x['amount'])} within {x['days_left']} day(s) or it will be debited.")
                       + " Want me to draft the proof message?",
                 f"{len(open_)} चार्जबैक खुले हैं, कुल {inr(c['open_amount'])}। "
                 + (f"{inr(x['amount'])} की सबूत भेजने की तारीख निकल चुकी है।" if late else f"{inr(x['amount'])} का सबूत {x['days_left']} दिन में भेजें, वरना कट जाएगा।") + " सबूत का मैसेज तैयार करूँ?",
                 f"{len(open_)} chargeback open hain, kul {inr(c['open_amount'])}. "
                 + (f"{inr(x['amount'])} ka proof bhejne ki date nikal chuki hai." if late else f"{inr(x['amount'])} ka proof {x['days_left']} din mein bhejiye, warna kat jayega.") + " Proof ka message ready kar doon?")

    if intent == "chargeback_proof":
        r = run("propose_chargeback_proof")
        if e := consent_msg(r):
            return e
        if not r.get("ok"):
            if r["error"] == "deadline_passed":
                return L(lang, "The deadline to send proof has passed. Please contact Paytm support.", "सबूत भेजने की तारीख निकल चुकी है। Paytm सपोर्ट से संपर्क करें।",
                         "Proof bhejne ki date nikal chuki hai. Paytm support se baat kijiye.")
            return L(lang, "There is no open chargeback to respond to.", "जवाब देने के लिए कोई खुला चार्जबैक नहीं है।", "Jawab dene ke liye koi open chargeback nahi hai.")
        return L(lang, f"Drafted the proof message ({r['days_left']} day(s) left). Attach your bill or delivery proof, then approve. Send? (yes/no)",
                 f"सबूत का मैसेज तैयार है ({r['days_left']} दिन बचे)। अपना बिल या डिलीवरी का सबूत जोड़ें, फिर मंज़ूर करें। भेज दूँ? (हाँ/नहीं)",
                 f"Proof ka message ready hai ({r['days_left']} din bache). Apna bill ya delivery proof jodiye, phir approve kijiye. Bhej doon? (haan/nahi)")

    if intent == "mdr":
        f = run("get_upi_fee_estimate", period=ent.get("period", "this_month"))
        if e := consent_msg(f):
            return e
        note = L(lang, " This is an estimate; your data doesn't say which payments were QR.", " यह सिर्फ अनुमान है; डेटा में QR का फ़र्क नहीं है।", " Yeh sirf anumaan hai; data mein QR ka farq nahi hai.")
        if f["no_data"]:
            return L(lang, "No UPI payments in this period, so no fee to estimate.", "इस अवधि में कोई UPI भुगतान नहीं है।", "Is period mein koi UPI payment nahi hai.")
        if f["estimated_mdr"] == 0:
            return L(lang, f"UPI fee: ₹0 on {inr(f['upi_receipts'])} of UPI receipts. Small merchants up to ₹1 lakh a month by QR pay nothing, and payments up to ₹2,000 are free." + note,
                     f"UPI फीस: {inr(f['upi_receipts'])} के UPI भुगतान पर ₹0। ₹1 लाख महीने तक QR पर और ₹2,000 तक के भुगतान पर कोई फीस नहीं।" + note,
                     f"UPI fee: {inr(f['upi_receipts'])} ke UPI payments par ₹0. Mahine ke ₹1 lakh tak QR par aur ₹2,000 tak ke payment par koi fee nahi." + note)
        return L(lang, f"Estimated UPI fee: {inr(f['estimated_mdr'])} (0.4% on {f['chargeable_count']} payments above ₹2,000, {f['share_charged_pct']}% of your UPI receipts)." + note,
                 f"अनुमानित UPI फीस: {inr(f['estimated_mdr'])} (₹2,000 से ऊपर के {f['chargeable_count']} भुगतान पर 0.4%, UPI का {f['share_charged_pct']}%)।" + note,
                 f"Anumaanit UPI fee: {inr(f['estimated_mdr'])} (₹2,000 se upar ke {f['chargeable_count']} payments par 0.4%, UPI ka {f['share_charged_pct']}%)." + note)

    if intent == "verify_payment":
        if not ent.get("amount"):
            return L(lang, "Tell me the amount the customer says they paid, for example 'did 450 come in?'. I'll check your Paytm records.",
                     "ग्राहक ने कितना भेजा बताइए, जैसे '450 आया?'। मैं आपके Paytm रिकॉर्ड में देखूँगा।",
                     "Customer ne kitna bheja bataiye, jaise '450 aaya?'. Main aapke Paytm records mein dekhunga.")
        v = run("verify_payment", amount=ent["amount"])
        if e := consent_msg(v):
            return e
        if not v.get("ok"):
            return L(lang, "That amount doesn't look right.", "यह रकम सही नहीं लग रही।", "Yeh amount sahi nahi lag raha.")
        a = inr(v["amount"], 2 if v["amount"] % 1 else 0)
        tail = L(lang, " Trust only your Paytm app or soundbox, not a screenshot. If it looks like fraud, call 1930.",
                 " सिर्फ अपने Paytm ऐप या साउंडबॉक्स पर भरोसा करें, स्क्रीनशॉट पर नहीं। धोखाधड़ी लगे तो 1930 पर कॉल करें।",
                 " Sirf apne Paytm app ya soundbox par bharosa kijiye, screenshot par nahi. Fraud lage to 1930 par call kijiye.")
        if v["received"]:
            mt = v["matches"][0]
            return L(lang, f"Yes, {a} was received {mt['minutes_ago']} minute(s) ago in your Paytm records.", f"हाँ, {a} आपके Paytm रिकॉर्ड में {mt['minutes_ago']} मिनट पहले आया है।",
                     f"Haan, {a} aapke Paytm records mein {mt['minutes_ago']} minute pehle aaya hai.") + tail
        if v["verdict"].startswith("not_received_"):
            st = v["verdict"].split("_")[-1]
            return L(lang, f"No. A {a} payment shows as {st}, so the money did NOT reach you. Do not hand over the goods.",
                     f"नहीं। {a} का भुगतान '{st}' दिख रहा है, पैसे आपको नहीं मिले। सामान न दें।",
                     f"Nahi. {a} ka payment '{st}' dikh raha hai, paisa aapko NAHI mila. Saaman mat dijiye.") + tail
        if v["verdict"] == "earlier_only":
            mt = v["earlier"][0]
            return L(lang, f"Not in the last {v['window_minutes']} minutes. The only {a} credit was {mt['minutes_ago']} minutes ago, so it may be a different customer's." ,
                     f"पिछले {v['window_minutes']} मिनट में नहीं। {a} का एक ही भुगतान {mt['minutes_ago']} मिनट पहले आया था, शायद किसी और का है।",
                     f"Pichle {v['window_minutes']} minute mein nahi. {a} ka ek hi payment {mt['minutes_ago']} minute pehle aaya tha, shayad kisi aur ka hai.") + tail
        return L(lang, f"No. I can't find a {a} payment in the last {v['window_minutes']} minutes in your records. Don't hand over the goods yet.",
                 f"नहीं। पिछले {v['window_minutes']} मिनट में {a} का कोई भुगतान आपके रिकॉर्ड में नहीं है। अभी सामान न दें।",
                 f"Nahi. Pichle {v['window_minutes']} minute mein {a} ka koi payment aapke records mein nahi hai. Abhi saaman mat dijiye.") + tail

    if intent == "settlements":
        s = run("get_settlements")
        if e := consent_msg(s):
            return e
        parts = []
        for x in s["failed"][:1]:
            parts.append(i18n.t(lang, "settle_fail", amt=inr(x["amount"]), reason=x["failure_reason"]))
        for x in s["delayed"][:2]:
            parts.append(i18n.t(lang, "settle_delay", amt=inr(x["amount"]), days=x["days_late"]))
        if not parts:
            return L(lang, f"All settlements are on track. {inr(s['pending_amount'])} is upcoming.", f"सब सेटलमेंट समय पर हैं। {inr(s['pending_amount'])} आने वाला है।", f"Sab settlement time par hain. {inr(s['pending_amount'])} aane wala hai.")
        return " ".join(parts) + L(lang, " Please contact Paytm support or update your bank details.", " कृपया Paytm सपोर्ट से संपर्क करें या बैंक विवरण अपडेट करें।", " Kripya Paytm support se baat kijiye ya bank details update kijiye.")

    if intent == "credit":
        c = run("get_cashflow_and_credit")
        if e := consent_msg(c):
            return e
        cf = c["cashflow"]
        if not c.get("eligible"):
            return L(lang, "I can't suggest credit yet: " + c.get("reason", "not enough history").replace("_", " ") + ".", "अभी क्रेडिट सुझाव नहीं दे सकता।", "Abhi credit suggest nahi kar sakta.")
        if not c["needs_credit"]:
            return L(lang, "No cash gap in the next 14 days, so you don't need credit right now. Upcoming bills are covered by expected sales.",
                     "अगले 14 दिनों में नकदी की कमी नहीं है, अभी क्रेडिट की ज़रूरत नहीं।", "Agle 14 din mein cash ki kami nahi hai, abhi credit ki zaroorat nahi.")
        return L(lang, f"Bills of {inr(cf['bills_due_total'])} fall due in 14 days but expected sales cover {inr(cf['expected_inflow'])} (gap {inr(cf['gap'])}). "
                       f"An indicative offer: {inr(c['suggested_amount'])} over {c['tenor_months']} months, EMI about {inr(c['indicative_emi'])}. Terms are set by Paytm's lending partner.",
                 f"14 दिन में {inr(cf['bills_due_total'])} के बिल हैं, पर अनुमानित बिक्री {inr(cf['expected_inflow'])} है (कमी {inr(cf['gap'])})। सांकेतिक ऑफर: {inr(c['suggested_amount'])}, {c['tenor_months']} महीने, EMI लगभग {inr(c['indicative_emi'])}।",
                 f"14 din mein {inr(cf['bills_due_total'])} ke bill hain, par expected sales {inr(cf['expected_inflow'])} hai (gap {inr(cf['gap'])}). Indicative offer: {inr(c['suggested_amount'])}, {c['tenor_months']} mahine, EMI lagbhag {inr(c['indicative_emi'])}.")

    if intent == "news":
        n = run("get_market_news")
        heads = n.get("headlines", [])[:3]
        if not heads:
            return L(lang, "I couldn't fetch market news right now. Please try again later.", "अभी बाज़ार की खबरें नहीं मिल पाईं। थोड़ी देर बाद कोशिश करें।",
                     "Abhi market ki khabar nahi mil paayi. Thodi der baad try kijiye.")
        lines = "; ".join(f"{h['title']} ({h['source']})" for h in heads)
        return L(lang, f"Latest for your business: {lines}.", f"आपके कारोबार की ताज़ा खबरें: {lines}।", f"Aapke business ki taaza khabar: {lines}.")

    if intent == "season_plan":
        p = run("get_season_plan")
        if p.get("error"):
            return consent_msg(p) or L(lang, "I couldn't build the plan right now.", "अभी योजना नहीं बन पाई।", "Abhi plan nahi ban paaya.")
        tips = (p.get("stock_moves") or [])[:2] + (p.get("service_moves") or [])[:1] + (p.get("slow_sellers") or [])[:1] + (p.get("money") or [])[:1]
        if not tips:
            return L(lang, "Nothing special to change right now. Keep your usual stock levels.", "अभी कुछ खास बदलने की ज़रूरत नहीं। सामान्य स्टॉक रखें।",
                     "Abhi kuch khaas badalne ki zaroorat nahi. Normal stock rakhiye.")
        text = " ".join(tips)
        if i18n.lang_of(lang) == "hi":
            from ..services import sarvam
            text = sarvam.translate(ctx.db, text, "hi", merchant_id=ctx.merchant.id)
        return text

    if intent == "festivals":
        f = run("get_upcoming_festivals")["upcoming"]
        if not f:
            return L(lang, "No major festival in the next 45 days.", "अगले 45 दिनों में कोई बड़ा त्योहार नहीं।", "Agle 45 din mein koi bada tyohar nahi.")
        return " ".join(i18n.t(lang, "festival", name=x["name"], days=x["days"], hint=x["hint"]) for x in f[:2])

    return L(lang, "Sorry, I couldn't do that.", "क्षमा करें, यह नहीं हो पाया।", "Maaf kijiye, yeh nahi ho paaya.")


def item_in_text(ctx: Ctx, text: str) -> str | None:
    """Return the item (name) mentioned in the text, if any. Whole-word match on name/aliases, so 'tea' != 'steam'."""
    from ..models import Item
    t = " " + words_to_digits(norm(text)) + " "
    best, blen = None, 0
    for it in ctx.db.query(Item).filter_by(merchant_id=ctx.merchant.id, active=True):
        for a in [it.name, *(it.aliases or [])]:
            na = norm(a)
            if len(na) >= 3 and f" {na} " in t and len(na) > blen:
                best, blen = it.name, len(na)
    return best
