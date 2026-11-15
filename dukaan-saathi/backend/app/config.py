"""Runtime configuration, read from environment (.env supported)."""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./dukaan_saathi.db")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")
# anthropic | openai. Empty = whichever key is set (Anthropic first).
# Cost guards (OpenAI credits are limited). Requests are API calls, not chat messages: a tool loop uses several.
LLM_DAILY_REQUESTS = int(os.getenv("LLM_DAILY_REQUESTS", "60"))      # per merchant per day, then rules answer
LLM_MAX_STEPS = int(os.getenv("LLM_MAX_STEPS", "4"))                  # tool-loop rounds per chat message
LLM_MAX_OUTPUT_TOKENS = int(os.getenv("LLM_MAX_OUTPUT_TOKENS", "450"))
LLM_HISTORY_TURNS = int(os.getenv("LLM_HISTORY_TURNS", "6"))
# Ask Saathi conversations are kept this long, then deleted.
CHAT_RETENTION_DAYS = int(os.getenv("CHAT_RETENTION_DAYS", "7"))
# llm_first = LLM answers everything except approvals; rules_first = rules answer routine questions, LLM only the open-ended ones.
LLM_MODE = os.getenv("LLM_MODE", "llm_first").strip().lower()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_IMAGE_MODEL = os.getenv("GEMINI_IMAGE_MODEL", "gemini-2.5-flash-image")
SARVAM_API_KEY = os.getenv("SARVAM_API_KEY", "")
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "").strip().lower()
PLANNER_MODEL = os.getenv("PLANNER_MODEL", "claude-sonnet-5-5")
SMALL_MODEL = os.getenv("SMALL_MODEL", "claude-haiku-5-5")
# Comma separated list of allowed browser origins for the dashboard.
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",")]
# Merchant-set guardrail: largest discount an AI-drafted offer may carry.
MAX_OFFER_DISCOUNT_PCT = int(os.getenv("MAX_OFFER_DISCOUNT_PCT", "15"))
# Pending actions expire if the merchant does not answer.
ACTION_TTL_HOURS = int(os.getenv("ACTION_TTL_HOURS", "48"))

# --- sign-up / login
# DEV ONLY: return the OTP in the API response so the prototype works without an SMS gateway.
# In production this must be false and the OTP delivered through Paytm's own login / an SMS provider.
DEV_OTP_ECHO = os.getenv("DEV_OTP_ECHO", "true").lower() == "true"
# DEV ONLY: lets the demo switcher and tests act as a merchant via the X-Merchant-Id header (no login).
ALLOW_DEMO_HEADER = os.getenv("ALLOW_DEMO_HEADER", "true").lower() == "true"
OTP_TTL_MINUTES = int(os.getenv("OTP_TTL_MINUTES", "5"))
OTP_MAX_ATTEMPTS = 5
OTP_MAX_REQUESTS_PER_HOUR = 5
SESSION_DAYS = int(os.getenv("SESSION_DAYS", "30"))

# --- SMS delivery: console (default, sends nothing) | twilio_verify (works on trial) | twilio | msg91
SMS_PROVIDER = os.getenv("SMS_PROVIDER", "console").lower()
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM = os.getenv("TWILIO_FROM", "")
TWILIO_MESSAGING_SERVICE_SID = os.getenv("TWILIO_MESSAGING_SERVICE_SID", "")
MSG91_AUTH_KEY = os.getenv("MSG91_AUTH_KEY", "")
MSG91_TEMPLATE_ID = os.getenv("MSG91_TEMPLATE_ID", "")
TWILIO_VERIFY_SERVICE_SID = os.getenv("TWILIO_VERIFY_SERVICE_SID", "")
