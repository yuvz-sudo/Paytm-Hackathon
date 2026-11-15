"""Tool registry shared by the LLM planner and the rule router.

Every tool: (1) is consent-gated, (2) never moves money or sends messages directly — `propose_*`
tools only create pending Actions, (3) returns plain JSON-serialisable dicts and never raises."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable

from sqlalchemy.orm import Session

from ..models import Merchant
from ..services import advisor, news
from ..services import (actions, analytics, audit, briefing, calendar, consent, credit, customers, fees, finance, growth, gst, marketing, inventory, ledger,
                        payments, retention, procurement, settlements)

YES = re.compile(r"^\s*(yes|y|yeah|yep|ok|okay|sure|confirm(ed)?|send( it)?|go ahead|do it|haan|han|ha|haa|haanji|han ji|ji|theek hai|thik hai|"
                 r"bhej( do| dijiye| de)?|kar do|kardo|kar dijiye|हाँ|हां|हा|जी|ठीक है|भेज दो|भेज दीजिए|कर दो)\b", re.I)
NO = re.compile(r"^\s*(no|n|nope|nahi|nahin|nai|mat|cancel|stop|rehne do|rahne do|ruko|नहीं|नही|मत|रहने दो|रुको)\b", re.I)


@dataclass
class Ctx:
    db: Session
    merchant: Merchant
    last_user_message: str = ""
    trace: list[dict] = field(default_factory=list)
    proposed_action_ids: list[int] = field(default_factory=list)


def _p(ctx: Ctx, res: dict) -> dict:
    """Track created actions so the UI can show approval cards."""
    a = res.get("action")
    for x in ([a] if a else []) + res.get("proposals", []):
        if x and x.get("id") not in ctx.proposed_action_ids:
            ctx.proposed_action_ids.append(x["id"])
    return res


def t_sales(ctx, period="yesterday"):
    return analytics.sales_summary(ctx.db, ctx.merchant, period)


def t_best(ctx, period="last_7_days", limit=5):
    return analytics.best_sellers(ctx.db, ctx.merchant, period, max(1, min(int(limit), 10)))


def t_hours(ctx):
    h = analytics.hourly_profile(ctx.db, ctx.merchant)
    h["weekdays"] = analytics.weekday_profile(ctx.db, ctx.merchant)
    return h


def t_stock(ctx, only_risky=False):
    return inventory.stock_status(ctx.db, ctx.merchant, bool(only_risky))


def t_update_stock(ctx, item, quantity, mode="set"):
    r = inventory.update_stock(ctx.db, ctx.merchant, item, quantity, mode if mode in ("set", "add") else "set")
    if r.get("ok"):
        audit.log(ctx.db, ctx.merchant.id, "merchant", "stock_updated", {"item": r["item"], "stock": r["stock"]})
        ctx.db.commit()
    return r


def t_order(ctx, items=None):
    return _p(ctx, procurement.propose_supplier_orders(ctx.db, ctx.merchant, items or None))


def t_dues(ctx):
    return ledger.dues(ctx.db, ctx.merchant)


def t_add_udhaar(ctx, customer, amount, note="", create_if_missing=False):
    return ledger.add_credit(ctx.db, ctx.merchant, customer, amount, note, create_if_missing=bool(create_if_missing))


def t_payment(ctx, customer, amount):
    return ledger.record_payment(ctx.db, ctx.merchant, customer, amount)


def t_remind(ctx, customer=None):
    return _p(ctx, ledger.propose_reminders(ctx.db, ctx.merchant, customer))


def t_customers(ctx):
    return customers.summary(ctx.db, ctx.merchant)


def t_winback(ctx, discount_pct=10, valid_days=7, send_hour=None):
    return _p(ctx, customers.propose_winback(ctx.db, ctx.merchant, discount_pct, valid_days, send_hour=send_hour))




def t_gst(ctx, period="last_month"):
    return gst.summary(ctx.db, ctx.merchant, period)


def t_settlements(ctx):
    return settlements.status(ctx.db, ctx.merchant)


def t_explain_settlement(ctx, settlement_id=None, amount=None):
    return settlements.explain(ctx.db, ctx.merchant, settlement_id, amount)


def t_chargebacks(ctx):
    return settlements.chargebacks(ctx.db, ctx.merchant)


def t_chargeback_proof(ctx, chargeback_id=None):
    return _p(ctx, settlements.propose_proof(ctx.db, ctx.merchant, chargeback_id))


def t_mdr(ctx, period="this_month"):
    return fees.mdr_estimate(ctx.db, ctx.merchant, period)


def t_verify_payment(ctx, amount, minutes=5):
    try:
        return payments.verify(ctx.db, ctx.merchant, float(amount), int(minutes))
    except (TypeError, ValueError):
        return {"ok": False, "error": "invalid_input"}


def t_growth(ctx):
    return growth.advisor(ctx.db, ctx.merchant)


def t_compare(ctx):
    return growth.compare(ctx.db, ctx.merchant)


def t_campaign(ctx, occasion, discount_pct=10, valid_days=7, audience="lapsed"):
    # use_llm=False here: the chat turn already used the LLM, so the copy comes from the template (no second paid call)
    return _p(ctx, marketing.create(ctx.db, ctx.merchant, occasion, discount_pct, valid_days, audience if audience in marketing.AUDIENCES else "lapsed", use_llm=False))


def t_segments(ctx):
    return retention.segments(ctx.db, ctx.merchant)


def t_finance_report(ctx, period="this_month"):
    return finance.report(ctx.db, ctx.merchant, period)


def t_forecast(ctx):
    return finance.forecast(ctx.db, ctx.merchant)


def t_credit(ctx):
    return credit.suggestion(ctx.db, ctx.merchant)


def t_briefing(ctx):
    return briefing.get_or_create(ctx.db, ctx.merchant)


def t_festivals(ctx):
    return {"upcoming": calendar.upcoming(ctx.merchant.segment, 45)}


def t_explain(ctx, day=None):
    return analytics.explain_change(ctx.db, ctx.merchant, day)


def t_item(ctx, item):
    return inventory.item_report(ctx.db, ctx.merchant, item)


def t_cust_balance(ctx, customer):
    return ledger.customer_balance(ctx.db, ctx.merchant, customer)


def t_pending(ctx):
    return {"pending": actions.list_actions(ctx.db, ctx.merchant.id, "pending")}


def t_decide(ctx, action_id, decision):
    """Approve/reject a pending action. Guarded: the merchant's *latest message* must be an explicit yes/no."""
    msg = ctx.last_user_message or ""
    if decision == "approve":
        if not YES.search(msg):
            return {"ok": False, "error": "explicit_confirmation_required",
                    "hint": "Ask the merchant to confirm. Only approve if their latest message clearly says yes."}
        return actions.approve(ctx.db, ctx.merchant.id, int(action_id))
    if decision == "reject":
        return actions.reject(ctx.db, ctx.merchant.id, int(action_id))
    return {"ok": False, "error": "invalid_decision"}


@dataclass
class Tool:
    name: str
    description: str
    schema: dict
    fn: Callable[..., dict]
    scope: str | None = None  # consent scope required


def _obj(props: dict | None = None, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": props or {}, "required": required or [], "additionalProperties": False}


PERIOD = {"type": "string", "description": "today | yesterday | last_7_days | last_30_days | this_month | last_month | YYYY-MM-DD"}

def t_season_plan(ctx):
    """Compact advisor plan for the LLM: seasonal stock moves, slow sellers, money advice, price news."""
    p = advisor.plan(ctx.db, ctx.merchant)
    return {"season": p["season"], "stock_moves": [x["advice"] for x in p["stock_moves"][:6]],
            "service_moves": [x["advice"] for x in p["service_moves"][:3]],
            "slow_sellers": [x["advice"] for x in p["slow_sellers"][:3]], "max_discount_pct": p["max_discount_pct"],
            "money": [f"{x['title']}: {x['detail']}" for x in p["money"][:5]],
            "price_news": [{"commodity": x["commodity"], "direction": x["direction"], "sources": [s["source"] for s in x["sources"]]}
                           for x in p["price_signals"][:4]]}


def t_news(ctx):
    n = news.for_merchant(ctx.db, ctx.merchant, limit=5)
    return {"headlines": [{"title": x["title"], "source": x["source"], "hours_ago": x["age_hours"]} for x in n["items"]],
            "note": "Real headlines; quote the source. Do not add facts that are not in a headline."}


TOOLS: list[Tool] = [
    Tool("get_sales_summary", "Sales total, payment count, average ticket, refunds, failed payments and change vs previous period.",
         _obj({"period": PERIOD}), t_sales, "transactions"),
    Tool("get_best_sellers", "Best and slowest selling items for a period (from itemised payments; includes coverage %).",
         _obj({"period": PERIOD, "limit": {"type": "integer"}}), t_best, "transactions"),
    Tool("get_hourly_insights", "Peak and slow hours of the day and weekday profile.", _obj(), t_hours, "transactions"),
    Tool("get_stock_status", "Estimated stock, days left and risk per tracked item.",
         _obj({"only_risky": {"type": "boolean"}}), t_stock, "transactions"),
    Tool("update_stock", "Record stock the merchant reports. mode='set' when they counted what is left, 'add' when new stock arrived.",
         _obj({"item": {"type": "string"}, "quantity": {"type": "number"}, "mode": {"type": "string", "enum": ["set", "add"]}},
              ["item", "quantity"]), t_update_stock, "transactions"),
    Tool("propose_supplier_order", "Draft supplier order message(s) for low-stock items (or named items). Creates a PENDING action; nothing is sent until the merchant confirms.",
         _obj({"items": {"type": "array", "items": {"type": "string"}}}), t_order, "transactions"),
    Tool("get_udhaar_dues", "Customers who owe money with ageing buckets and overdue amounts.", _obj(), t_dues, "ledger"),
    Tool("add_udhaar", "Record new credit (udhaar) given to a customer. If the customer is not found, ask the merchant before create_if_missing=true.",
         _obj({"customer": {"type": "string"}, "amount": {"type": "number"}, "note": {"type": "string"}, "create_if_missing": {"type": "boolean"}},
              ["customer", "amount"]), t_add_udhaar, "ledger"),
    Tool("record_udhaar_payment", "Record a repayment received from a customer.",
         _obj({"customer": {"type": "string"}, "amount": {"type": "number"}}, ["customer", "amount"]), t_payment, "ledger"),
    Tool("propose_udhaar_reminders", "Draft polite payment reminders (one customer, or all overdue). Creates PENDING actions.",
         _obj({"customer": {"type": "string"}}), t_remind, "ledger"),
    Tool("get_customer_insights", "Top regulars and lapsed regulars with spend and visit gaps.", _obj(), t_customers, "customers"),
    Tool("propose_winback_offer", "Draft a win-back discount offer for lapsed regulars. Discount is capped by merchant guardrail. Creates a PENDING action.",
         _obj({"discount_pct": {"type": "integer"}, "valid_days": {"type": "integer"},
               "send_hour": {"type": "integer", "description": "0-23; hour to steer the offer into. Default: the shop's next quiet hour."}}),
         t_winback, "customers"),
    Tool("get_gst_summary", "Turnover, estimated GST by slab, filing due dates, or registration-threshold status.",
         _obj({"period": PERIOD}), t_gst, "transactions"),
    Tool("get_settlements", "Settlement status: delayed, failed, upcoming.", _obj(), t_settlements, "transactions"),
    Tool("explain_settlement", "Why a payout is lower than sales: gross payments minus commission, GST on commission, rental, refunds, chargebacks, recoveries = net. "
         "Defaults to the latest settlement; pass amount to find the one the merchant is asking about.",
         _obj({"settlement_id": {"type": "integer"}, "amount": {"type": "number"}}), t_explain_settlement, "transactions"),
    Tool("get_chargebacks", "Chargebacks with days left to send proof of delivery; urgent ones will be debited if proof is late.", _obj(), t_chargebacks, "transactions"),
    Tool("propose_chargeback_proof", "Draft the proof-of-delivery message for an open chargeback. Creates a PENDING action; the merchant must attach their bill/proof.",
         _obj({"chargeback_id": {"type": "integer"}}), t_chargeback_proof, "transactions"),
    Tool("get_upi_fee_estimate", "Estimated UPI merchant fee (MDR 0.4% above Rs 2,000; zero up to Rs 1 lakh/month by QR). Always an estimate with stated assumptions.",
         _obj({"period": PERIOD}), t_mdr, "transactions"),
    Tool("verify_payment", "Check the merchant's own Paytm records for a successful payment of an amount in the last few minutes. Use when a customer shows a payment screenshot.",
         _obj({"amount": {"type": "number"}, "minutes": {"type": "integer"}}, ["amount"]), t_verify_payment, "transactions"),
    Tool("get_growth_advice", "Ranked growth opportunities (quiet time-of-day, weak weekdays, bill size) with rupee estimates, plus the single biggest problem. Use for 'how can I increase sales'.",
         _obj(), t_growth, "transactions"),
    Tool("compare_periods", "Last 7 days vs the 7 before, and this month so far vs the same days last month.", _obj(), t_compare, "transactions"),
    Tool("propose_campaign", "Draft a marketing campaign (e.g. Diwali offer) for lapsed customers, regulars or everyone with a discount capped by the merchant guardrail. "
         "Creates a PENDING action; nothing is sent until the merchant confirms. A poster can be made from the Marketing page.",
         _obj({"occasion": {"type": "string"}, "discount_pct": {"type": "integer"}, "valid_days": {"type": "integer"},
               "audience": {"type": "string", "enum": ["lapsed", "regulars", "all", "high_value", "repeat", "new", "at_risk"]}}, ["occasion"]), t_campaign, "customers"),
    Tool("get_customer_segments", "Customer segments (high-value, repeat, new, drifting away, lapsed) with counts, spend and each customer's usual item.", _obj(), t_segments, "customers"),
    Tool("get_finance_report", "Month/period money report: collections, refunds, failed payments, settlement deductions and highlights vs the previous period.",
         _obj({"period": PERIOD}), t_finance_report, "transactions"),
    Tool("get_cashflow_forecast", "Cautious 30-day collections forecast (low/likely/high), bills due and when cash may get tight, with an indicative working-capital need.",
         _obj(), t_forecast, "transactions"),
    Tool("get_cashflow_and_credit", "Upcoming bills vs expected sales and an indicative credit suggestion (only when there is a gap).",
         _obj(), t_credit, "credit"),
    Tool("get_daily_briefing", "The full morning briefing with prioritised alerts.", _obj(), t_briefing, None),
    Tool("get_upcoming_festivals", "Upcoming festivals with stocking hints for this segment.", _obj(), t_festivals, None),
    Tool("get_season_plan", "Business-advisor plan: which items to stock up or slow down on (festival, wedding season, weather), with quantities and "
         "dates; slow sellers with a suggested discount; money advice (cash flow, festival stock budget, udhaar, stuck settlements, UPI fees); "
         "price direction from real news. Use for festival/season stocking, 'kya mangwau', pricing, discounts, financial advice.",
         _obj(), t_season_plan, "transactions"),
    Tool("get_market_news", "Recent real news headlines relevant to this shop's business and the commodities it sells.", _obj(), t_news, None),
    Tool("explain_sales_change", "Why a day's sales were up or down vs the same weekday last week: footfall vs basket size, hours and items driving it.",
         _obj({"day": {"type": "string", "description": "YYYY-MM-DD; default yesterday"}}), t_explain, "transactions"),
    Tool("get_item_report", "One item: estimated stock, days left, 7-day sales and trend.", _obj({"item": {"type": "string"}}, ["item"]), t_item, "transactions"),
    Tool("get_customer_balance", "How much one customer owes and how old it is.", _obj({"customer": {"type": "string"}}, ["customer"]), t_cust_balance, "ledger"),
    Tool("get_pending_actions", "List actions waiting for the merchant's approval.", _obj(), t_pending, None),
    Tool("decide_action", "Approve or reject a pending action. ONLY approve when the merchant's most recent message is an explicit yes.",
         _obj({"action_id": {"type": "integer"}, "decision": {"type": "string", "enum": ["approve", "reject"]}}, ["action_id", "decision"]),
         t_decide, None),
]
BY_NAME = {t.name: t for t in TOOLS}


def anthropic_specs() -> list[dict]:
    return [{"name": t.name, "description": t.description, "input_schema": t.schema} for t in TOOLS]


def run(ctx: Ctx, name: str, args: dict[str, Any] | None) -> dict:
    tool = BY_NAME.get(name)
    args = args or {}
    if not tool:
        return {"error": "unknown_tool"}
    try:
        if tool.scope:
            consent.require(ctx.db, ctx.merchant.id, tool.scope)
        res = tool.fn(ctx, **args)
    except consent.ConsentDenied as e:
        res = {"error": "consent_off", "scope": e.scope}
    except TypeError:
        ctx.db.rollback()
        res = {"error": "bad_arguments"}
    except Exception as e:  # tools must never crash a conversation
        ctx.db.rollback()
        res = {"error": "tool_failed", "type": type(e).__name__}
    ctx.trace.append({"tool": name, "args": args, "ok": "error" not in res and res.get("ok", True) is not False})
    return res
