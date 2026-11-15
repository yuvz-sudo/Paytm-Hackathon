# Next steps: four features from the merchant research

Handoff for Claude Code. Source: "Merchant Problems & AI Opportunities" research doc (https://claude.ai/artifact/SikdPaUP3QpAYmog97Vh5z), section "What to build next".
**Status (2026-11-14): all four features are implemented, with tests in `backend/tests/test_next_steps.py`.** The text below is the original spec. The frontend restyle (Paytm for Business look) is already done; originals are in `src-backup-before-paytm-ui/`.

## Ground rules (follow the existing architecture, see README)
- Services are pure functions, consent-gated; the agent only *proposes*, the merchant approves (`services/actions.py`).
- Add routes in `backend/app/api/routes.py`, agent tools in `agent/tools.py`, intent rules in `agent/router.py`, text in `messages.py` / `i18n.py` (en, hi, hinglish).
- Every new screen/endpoint needs an empty state and a test (`backend/tests/`, run `.venv/bin/python -m pytest -q`).
- Avoid altering existing tables: the DB is SQLite with no migrations. Prefer NEW tables (created by `create_all`; confirm in `app/main.py`) and add seed data in `seed.py`.

## 1. Settlement explainer + chargeback helper (highest priority)
Problem: net payout is lower than sales and the merchant cannot see why. Paytm's rule: net = payments - commission - 18% GST on commission - rental - refunds - chargebacks - recoveries; a chargeback is debited if proof of delivery is not sent in time.
- New tables: `SettlementLine(settlement_id, kind, label, amount)` and `Chargeback(merchant_id, txn_id?, amount, raised_date, proof_due_date, status: open|proof_sent|lost|won, reason)`.
- Seed: change `_seed_settlements` so `amount` = gross - lines (today it is `total * 0.99`); add one open chargeback for Ramesh Kirana with a deadline in ~2 days.
- `services/settlements.py`: add `explain(db, m, settlement_id)` returning gross, each deduction, net, and a plain-words summary; add `chargebacks(db, m)` with `days_left` and an `urgent` flag.
- Routes: `GET /settlements/{id}/explain`, `GET /chargebacks`; action type `chargeback_proof` (drafts the proof message for approval).
- Agent: tool + router rules for "payout kam kyun aaya", "why did I get X", "chargeback".
- UI: Money page, "Why this amount?" button per settlement row; chargeback card with countdown; surface urgent chargebacks in the briefing (`services/briefing.py`).

## 2. UPI fee (MDR) explainer
Rule (Inc42, effective 15 Oct 2026): 0.4% MDR on P2M UPI above Rs 2,000 (capped Rs 300 at Rs 75,000+); small merchants receiving up to Rs 1 lakh a month by QR pay zero. Verify current rules before shipping.
- `services/fees.py`: for a period, split UPI receipts into exempt (<= Rs 1 lakh/month QR) vs. chargeable (> Rs 2,000 per txn), return estimated MDR and what share of payments it touches.
- Route `GET /fees/mdr?period=this_month`; agent tool + rules ("MDR kya hai", "UPI fee lagega?").
- UI: card in Money & GST. Always label as an estimate; the data has no QR-vs-other flag, so state the assumption.

## 3. Quiet-hour offers
`analytics.hourly_profile` already returns `slow_hours`/`quietest_hours`; `customers.propose_winback` drafts offers but ignores timing.
- Extend `propose_winback` (keep the discount cap) to accept `send_hour` defaulting to the next quiet hour, and mention the window in `messages.winback_offer`.
- UI: show the suggested window on the Customers page next to the discount selector.

## 4. Counter-fraud nudge (lowest effort)
AI cannot judge a screenshot; the nudge confirms the credit in the merchant's own records.
- `GET /payments/verify?amount=...&minutes=5`: is there a successful transaction of that amount in the last few minutes? Return yes/no + time.
- Agent rule: "payment aaya?", "customer ne screenshot dikhaya" -> check, answer, and remind helpline 1930.
- UI: small "Check a payment" box on Home.

## Done when
- Each feature has an endpoint, agent route, UI entry, empty state and a passing test.
- Demo story: Ramesh Kirana -> "why was my payout short?" -> chargeback deadline warning -> quiet-hour win-back offer.
