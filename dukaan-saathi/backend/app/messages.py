"""Drafted outbound messages. Templates for en / hi / hinglish; other languages fall back to English
until the language layer (Sarvam) is connected."""
from __future__ import annotations

from .util import inr, qty_fmt


def _lang(lang: str) -> str:
    return lang if lang in ("en", "hi", "hinglish") else "en"


def supplier_order(lang: str, shop: str, owner: str, lines: list[dict]) -> str:
    lang = _lang(lang)
    body = "\n".join(f"• {l['item']}: {qty_fmt(l['qty'])} {l['unit']}" for l in lines)
    if lang == "hi":
        return f"नमस्ते, {shop} ({owner}) की ओर से ऑर्डर:\n{body}\nकृपया जल्द से जल्द भेज दें और डिलीवरी का समय बताएं। धन्यवाद।"
    if lang == "hinglish":
        return f"Namaste, {shop} ({owner}) ki taraf se order:\n{body}\nKripya jaldi bhej dijiye aur delivery ka time bataiye. Dhanyawad."
    return f"Hello, order from {shop} ({owner}):\n{body}\nPlease deliver at the earliest and confirm the delivery time. Thank you."


def udhaar_reminder(lang: str, shop: str, name: str, amount: float, overdue_days: int) -> str:
    lang = _lang(lang)
    first = name.split()[0]
    firm = overdue_days > 30
    if lang == "hi":
        t = f"नमस्ते {first} जी, {shop} में आपका {inr(amount)} बकाया है।"
        t += " कृपया इसे इस हफ्ते चुका दें।" if firm else " जब सुविधा हो, UPI से भुगतान कर दें।"
        return t + " धन्यवाद 🙏"
    if lang == "hinglish":
        t = f"Namaste {first} ji, {shop} mein aapka {inr(amount)} baaki hai."
        t += " Kripya is hafte tak chuka dijiye." if firm else " Jab suvidha ho, UPI se bhej dijiye."
        return t + " Dhanyawad 🙏"
    t = f"Hello {first}, this is a gentle reminder from {shop}: {inr(amount)} is pending."
    t += " Please clear it this week." if firm else " Please pay via UPI whenever convenient."
    return t + " Thank you 🙏"


def winback_offer(lang: str, shop: str, name: str, discount_pct: int, valid_days: int, window: str | None = None) -> str:
    """`window` (e.g. '3 pm to 5 pm') ties the discount to the shop's quiet hours; omit for an all-day offer."""
    lang = _lang(lang)
    first = name.split()[0]
    if lang == "hi":
        when = f"{window} के बीच आने पर " if window else ""
        return f"नमस्ते {first} जी, {shop} में आपकी याद आ रही है! {when}अगली खरीदारी पर {discount_pct}% छूट, {valid_days} दिन तक मान्य। 🙏"
    if lang == "hinglish":
        when = f"{window} ke beech aane par " if window else ""
        return f"Namaste {first} ji, {shop} mein aapki yaad aa rahi hai! {when}Agli khareedari par {discount_pct}% chhoot, {valid_days} din tak. 🙏"
    when = f" when you visit between {window}" if window else ""
    return f"Hi {first}, we miss you at {shop}! Enjoy {discount_pct}% off on your next visit{when}, valid for {valid_days} days. 🙏"


def campaign_message(lang: str, shop: str, occasion: str, discount_pct: int, valid_days: int) -> str:
    """Template campaign text; {name} is replaced per recipient. Used when the LLM is off, over budget, or returns something unsafe."""
    lang = _lang(lang)
    off = f"{discount_pct}% " if discount_pct else ""
    if not discount_pct and occasion.lower().startswith("thank"):
        return {"hi": f"नमस्ते {{name}} जी! {shop} के खास ग्राहक होने के लिए धन्यवाद। 🙏",
                "hinglish": f"Namaste {{name}} ji! {shop} ke khaas customer hone ke liye dhanyawad. 🙏",
                "en": f"Hi {{name}}! Thank you for being one of our best customers at {shop}. 🙏"}[lang]
    if lang == "hi":
        deal = f"{discount_pct}% छूट, {valid_days} दिन तक।" if discount_pct else "आपका स्वागत है।"
        return f"नमस्ते {{name}} जी! {occasion} पर {shop} में खास ऑफर: {deal} 🙏"
    if lang == "hinglish":
        deal = f"{discount_pct}% chhoot, {valid_days} din tak." if discount_pct else "Aapka swagat hai."
        return f"Namaste {{name}} ji! {occasion} par {shop} mein khaas offer: {deal} 🙏"
    deal = f"enjoy {off}off for {valid_days} days." if discount_pct else "we'd love to see you."
    return f"Hi {{name}}! This {occasion} at {shop}, {deal} 🙏"


def with_item(lang: str, text: str, item: str | None) -> str:
    """Personalise: add the customer's usual item. Replaces an {item} placeholder (LLM copy) or appends a line (template copy)."""
    lang = _lang(lang)
    if "{item}" in text:
        return text.replace("{item}", item or {"hi": "पसंदीदा सामान", "hinglish": "pasandida saaman", "en": "your favourites"}[lang])
    if not item:
        return text
    return text + {"hi": f" आपका पसंदीदा {item} तैयार है।", "hinglish": f" Aapka pasandida {item} ready hai.", "en": f" Your usual {item} is ready for you."}[lang]
