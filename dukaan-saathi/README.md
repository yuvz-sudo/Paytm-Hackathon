# Dukaan Saathi: an AI business partner for every Paytm merchant

Merchant-growth copilot for the Paytm AI Hackathon. It reads a merchant's Paytm payments (with consent) and turns them
into a spoken morning briefing, stock-out warnings, udhaar reminders, win-back offers, review replies, GST and
settlement alerts, and credit suggestions *only when there is a real cash gap*.

## Run it

```bash
# backend (Python 3.11+)
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env            # optional: add ANTHROPIC_API_KEY for open-ended questions
.venv/bin/uvicorn app.main:app --port 8000     # seeds 3 demo merchants on first start

# frontend (Node 18+)
cd frontend && npm install && npm run dev      # http://localhost:5173

# tests
cd backend && .venv/bin/python -m pytest -q
```

Reset demo data: `cd backend && .venv/bin/python -m app.seed`. Sample data rolls forward by itself: on the first request each
day, a sample-data shop's history moves to today and today's payments fill in up to now (`app/demo_clock.py`). Real merchants are never touched.

## Sign-up and login

New merchant: **mobile number -> OTP -> 3-step setup** (shop details, language and per-scope privacy choices, then
"explore with sample data" or "start fresh") -> **My Shop** to add items and suppliers. Returning merchants log in with the
same number. Sessions are bearer tokens (only a hash is stored, 30-day expiry, sign-out revokes).

- OTPs are 6 random digits, stored salted+hashed, single-use, 5-minute expiry, 5 attempts, 5 requests per hour per number.
- **Prototype only:** no SMS is sent. With `DEV_OTP_ECHO=true` the code is shown on screen. For production set
  `DEV_OTP_ECHO=false` and `ALLOW_DEMO_HEADER=false` and deliver OTPs through Paytm login / an SMS provider.
- A brand-new merchant has no data. Every screen and every chat question has an empty state (tested against all endpoints).
- Demo merchants also log in by OTP: 9876500001 (Ramesh), 9876500002 (Sharma Sweets), 9876500003 (Glow Salon).

## Demo merchants (switch from the header)

| Merchant | Why it is interesting |
|---|---|
| Ramesh Kirana Store, Pune (Hinglish) | Low stock, failed + delayed settlements, udhaar, lapsed regulars, unreported stock |
| Sharma Sweets, Jaipur (Hindi) | Post-Diwali dip (explained, not alarmed), ₹2.2L cash gap, credit suggestion, perishables |
| Glow Salon, Bengaluru (English) | Service business (no stock), nearing GST registration limit, tiny volumes |

**Money features**: *Why this amount?* on every settlement (gross minus commission, GST on commission, rental, refunds, chargebacks),
chargeback deadlines with a drafted proof message (approval first), an estimated UPI fee (MDR) card, win-back offers timed to the shop's
quiet hours, and a *Check a payment* box on Home (is the money really in my Paytm records? helpline 1930). Rates in the demo data are illustrative.
Existing databases created before these features keep working (old settlements show no breakdown); run `python -m app.seed` for the full demo.

Try in **Ask Saathi**: "briefing", "stock mein kya kam hai?" then "order kar do" then "haan bhej do",
"Mohan Singh ka 500 udhaar likho", "atta 20 bag aaya", "GST kitna banega", "आज की बिक्री".

## Languages and voice (Sarvam AI)

Set `SARVAM_API_KEY` in `backend/.env`. Merchants pick from 12 languages: Hinglish, Hindi, English, Bengali, Gujarati, Kannada,
Malayalam, Marathi, Odia, Punjabi, Tamil, Telugu.

- **Whole UI translated**: `frontend/src/translator.ts` translates the rendered page in place (React-safe). Numbers are templated
  (`{1} payments`), translations are cached in the browser and in the `translation_cache` table, and short labels get context
  (`Stock` is sent as "shop inventory") so they are not mistranslated. Hand-written Hindi in `i18n.tsx` wins. Mark names and typed
  content `translate="no"`.
- **Chat in any language**: en / hi / hinglish are answered directly; other languages are translated to English, answered by the same
  rules / LLM (identical approval rules) and translated back (`agent.respond`). The daily briefing is translated too.
- **Voice everywhere**: the floating mic on every page (and the mic in Ask Saathi) records, auto-stops when you finish, and calls
  `POST /api/voice/ask`: Sarvam speech-to-text (language auto-detected) -> Saathi -> answer read aloud with Sarvam text-to-speech,
  one sentence at a time. "Open stock" / "स्टॉक खोलो" navigates. Every Listen button uses Sarvam voices.
- **Never breaks**: without a key or when Sarvam is down, UI text stays English, chat still answers, and Listen falls back to the
  browser's own voice. A per-merchant daily character budget (`SARVAM_DAILY_CHARS`, default 400k) bounds spend.

## Growth Advisor and market news

- **Market news on Home** (`services/news.py`): real headlines from Google News for the shop's business type and the commodities it
  sells or buys (a sweet shop sees milk and ghee prices). Each shows the publisher, age and a link. Share-market noise, lifestyle
  pieces and non-English results are dropped; at most two stories per commodity. Cached 2 hours; offline keeps the last good copy.
  Only the business type is searched; no merchant data leaves the app. Headlines that say a commodity is getting dearer or cheaper
  become **price signals** (with sources).
- **Advisor plan** (`services/advisor.py`, `GET /api/growth/plan`): computed, not generated. Next 14 days of demand per item from the
  shop's own sales pace x festival / wedding-season / winter-summer multipliers (planning rules of thumb, shown as estimates) ->
  *stock up* (quantity and order-by date from supplier lead time; price news says buy now or in two lots) or *go slow*. Slow or weak
  sellers get a discount within the merchant's cap, drafted only for approval. Money advice: cash after known bills, whether festival
  stock is affordable (never "comfortable" during a cash gap), udhaar share, stuck settlements, UPI fees, sales trend.
- **Advisor's note**: one LLM call per merchant per day (cached, counted in the LLM budget) turns the plan into a warm, specific
  note using only those facts; without an LLM a template note is used. Every card has "Ask Saathi about this", which opens chat
  with the advice quoted; chat has `get_season_plan` and `get_market_news` tools plus offline rules ("Diwali ke liye kya mangwau?", "aaj ki news").
- Mandi price APIs (data.gov.in) were tried but did not respond reliably, so prices come only from cited news, never invented.

## How it works

```
Paytm payments -> analytics/inventory/ledger/... services (pure functions, consent-gated)
                          |
   chat ──> confirmation? ──> approval workflow (deterministic, never LLM)
        └─> rule router (routine Qs, en/hi/hinglish, offline) ──> tools
        └─> LLM planner with tool calling (open-ended Qs, needs API key) ──> same tools
```

**Trust guardrails (all covered by tests)**
- Consent per data scope; off means the API returns 403, the agent explains, and the briefing hides that section.
- The agent can only *propose*. Messages go out only after approval; approvals are atomic and idempotent, expire after 48h,
  re-validate at send time (a customer who already paid is not reminded) and respect "do not contact".
- A stray "yes" never approves a stale proposal; confirmation applies only to the latest proposal batch.
- Numbers always come from tools; customer-written text (reviews) is treated as untrusted data in the LLM prompt.
- Offer discounts are capped by a merchant guardrail; credit is only suggested when bills fall due before sales cover them.
- Every state change is in the audit log.

**Data honesty**: best sellers and stock use only *itemised* payments and show coverage %. Un-itemised sales are reported
separately in GST. Stock is an estimate from last reported count minus sales since, and flags stale or never-reported items.

## Not built yet
- Server-side WhatsApp/SMS delivery. Approved messages go to **Approvals → Ready to send**, each with a one-tap "Open in WhatsApp"
  (wa.me) / SMS link that sends from the merchant's own number; tapping marks it sent. A WhatsApp Business API would automate this.
- Real Paytm data feeds, inbound supplier replies.
- Soundbox hardware channel, nightly scheduler (briefings are computed on demand and cached per day), weather feed.
