"""Small string catalogue for spoken/written replies: en, hi (Devanagari) and hinglish.
Other languages fall back to English until the language layer is connected."""
from __future__ import annotations

S = {
    "greet_morning": {"en": "Good morning, {name}.", "hi": "सुप्रभात, {name} जी।", "hinglish": "Good morning, {name} ji."},
    "greet_afternoon": {"en": "Good afternoon, {name}.", "hi": "नमस्कार, {name} जी।", "hinglish": "Namaste, {name} ji."},
    "greet_evening": {"en": "Good evening, {name}.", "hi": "शुभ संध्या, {name} जी।", "hinglish": "Good evening, {name} ji."},
    "sales_line": {
        "en": "Yesterday's sales: {total} from {n} payments.",
        "hi": "कल की बिक्री: {total}, {n} भुगतान से।",
        "hinglish": "Kal ki sales: {total}, {n} payments se.",
    },
    "no_sales": {"en": "There were no payments yesterday.", "hi": "कल कोई भुगतान नहीं आया।", "hinglish": "Kal koi payment nahi aaya."},
    "vs_up": {"en": "That is {pct}% above the previous day.", "hi": "यह पिछले दिन से {pct}% ज़्यादा है।", "hinglish": "Yeh pichle din se {pct}% zyada hai."},
    "vs_down": {"en": "That is {pct}% below the previous day.", "hi": "यह पिछले दिन से {pct}% कम है।", "hinglish": "Yeh pichle din se {pct}% kam hai."},
    "vs_up_p": {"en": "That is {pct}% above the previous period.", "hi": "यह पिछली अवधि से {pct}% ज़्यादा है।", "hinglish": "Yeh pichli period se {pct}% zyada hai."},
    "vs_down_p": {"en": "That is {pct}% below the previous period.", "hi": "यह पिछली अवधि से {pct}% कम है।", "hinglish": "Yeh pichli period se {pct}% kam hai."},
    "best": {"en": "{item} sold best.", "hi": "{item} सबसे ज़्यादा बिका।", "hinglish": "{item} sabse zyada bika."},
    "stock_soon": {
        "en": "{items} will run out in about {days} days.",
        "hi": "{items} लगभग {days} दिन में खत्म हो जाएंगे।",
        "hinglish": "{items} lagbhag {days} din mein khatam ho jayenge.",
    },
    "stock_out": {"en": "{items} may already be out of stock.", "hi": "{items} शायद खत्म हो चुके हैं।", "hinglish": "{items} shayad khatam ho chuke hain."},
    "offer_order": {"en": "Should I message your supplier?", "hi": "क्या मैं सप्लायर को मैसेज भेजूं?", "hinglish": "Kya main supplier ko message bhejoon?"},
    "dues": {
        "en": "{n} customers owe you {total} in udhaar.",
        "hi": "{n} ग्राहकों पर कुल {total} उधार बाकी है।",
        "hinglish": "{n} customers par kul {total} udhaar baaki hai.",
    },
    "no_dues": {"en": "No udhaar is pending.", "hi": "कोई उधार बाकी नहीं है।", "hinglish": "Koi udhaar baaki nahi hai."},
    "settle_delay": {
        "en": "A settlement of {amt} is {days} day(s) late.",
        "hi": "{amt} का सेटलमेंट {days} दिन देर से है।",
        "hinglish": "{amt} ka settlement {days} din late hai.",
    },
    "settle_fail": {
        "en": "A settlement of {amt} failed: {reason}.",
        "hi": "{amt} का सेटलमेंट विफल रहा: {reason}।",
        "hinglish": "{amt} ka settlement fail hua: {reason}.",
    },
    "chargeback_due": {
        "en": "A chargeback of {amt} needs proof within {days} day(s), or it will be debited.",
        "hi": "{amt} के चार्जबैक का सबूत {days} दिन में भेजें, वरना यह कट जाएगा।",
        "hinglish": "{amt} ke chargeback ka proof {days} din mein bhejiye, warna kat jayega.",
    },
    "chargeback_late": {
        "en": "The deadline to send proof for a {amt} chargeback has passed.",
        "hi": "{amt} के चार्जबैक का सबूत भेजने की तारीख निकल चुकी है।",
        "hinglish": "{amt} ke chargeback ka proof bhejne ki date nikal chuki hai.",
    },
    "sales_drop": {
        "en": "Sales were {pct}% below a typical {weekday}.",
        "hi": "बिक्री सामान्य {weekday} से {pct}% कम रही।",
        "hinglish": "Sales normal {weekday} se {pct}% kam rahi.",
    },
    "lapsed": {
        "en": "{n} regular customers haven't visited in a while.",
        "hi": "{n} नियमित ग्राहक काफी समय से नहीं आए।",
        "hinglish": "{n} regular customers kaafi time se nahi aaye.",
    },
    "gst_due": {
        "en": "GSTR-1 is due in {days} days.",
        "hi": "GSTR-1 {days} दिन में जमा करना है।",
        "hinglish": "GSTR-1 {days} din mein bharna hai.",
    },
    "cash_gap": {
        "en": "Bills of {bills} are due soon but expected sales cover only {cover}.",
        "hi": "{bills} के बिल जल्द देय हैं, पर अनुमानित बिक्री सिर्फ {cover} कवर करेगी।",
        "hinglish": "{bills} ke bill jaldi due hain, par expected sales sirf {cover} cover karegi.",
    },
    "festival": {
        "en": "{name} is in {days} days. {hint}",
        "hi": "{name} {days} दिन में है। {hint}",
        "hinglish": "{name} {days} din mein hai. {hint}",
    },
    "welcome_empty": {
        "en": "Welcome to Dukaan Saathi, {name}! I don't see any payments yet. Once customers pay through Paytm I'll share daily sales, stock and udhaar insights. To get started, add your items and suppliers, or load sample data to explore.",
        "hi": "दुकान साथी में आपका स्वागत है, {name} जी! अभी कोई भुगतान नहीं दिख रहा। जैसे ही ग्राहक Paytm से भुगतान करेंगे, मैं रोज़ की बिक्री, स्टॉक और उधार की जानकारी दूँगा। शुरू करने के लिए अपने आइटम और सप्लायर जोड़ें, या सैंपल डेटा से देखें।",
        "hinglish": "Dukaan Saathi mein aapka swagat hai, {name} ji! Abhi koi payment nahi dikh raha. Jaise hi customers Paytm se pay karenge, main roz ki sales, stock aur udhaar ki jaankari dunga. Shuru karne ke liye apne items aur suppliers jodiye, ya sample data se dekhiye.",
    },
    "all_good": {"en": "Nothing needs your attention right now.", "hi": "अभी कुछ भी ध्यान देने की ज़रूरत नहीं है।", "hinglish": "Abhi kuch bhi dhyan dene ki zaroorat nahi hai."},
    "consent_off": {
        "en": "I can't look at that because '{scope}' access is switched off. You can turn it on in Privacy settings.",
        "hi": "'{scope}' की अनुमति बंद है, इसलिए मैं यह नहीं देख सकता। आप प्राइवेसी सेटिंग में इसे चालू कर सकते हैं।",
        "hinglish": "'{scope}' ki permission band hai, isliye main yeh nahi dekh sakta. Privacy settings mein aap ise on kar sakte hain.",
    },
}


def lang_of(lang: str) -> str:
    return lang if lang in ("en", "hi", "hinglish") else "en"


def t(lang: str, key: str, **kw) -> str:
    entry = S[key]
    return entry[lang_of(lang)].format(**kw)


WEEKDAY = {
    "hi": {"Monday": "सोमवार", "Tuesday": "मंगलवार", "Wednesday": "बुधवार", "Thursday": "गुरुवार", "Friday": "शुक्रवार",
           "Saturday": "शनिवार", "Sunday": "रविवार"},
    "hinglish": {"Monday": "Somvaar", "Tuesday": "Mangalvaar", "Wednesday": "Budhvaar", "Thursday": "Guruvaar",
                 "Friday": "Shukravaar", "Saturday": "Shanivaar", "Sunday": "Ravivaar"},
}


def weekday(lang: str, name: str) -> str:
    return WEEKDAY.get(lang_of(lang), {}).get(name, name)
