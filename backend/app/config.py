"""Settings from environment / backend/.env. Secrets are generated on first run if missing."""
import os
import secrets
from pathlib import Path

from cryptography.fernet import Fernet
from dotenv import load_dotenv

BACKEND = Path(__file__).resolve().parents[1]
ENV_PATH = BACKEND / ".env"
load_dotenv(ENV_PATH)


def _ensure(name: str, factory) -> str:
    val = os.environ.get(name)
    if val:
        return val
    val = factory()
    with ENV_PATH.open("a", encoding="utf-8") as f:
        f.write(f"{name}={val}\n")
    os.environ[name] = val
    return val


JWT_SECRET = _ensure("JWT_SECRET", lambda: secrets.token_urlsafe(48))
FIELD_KEY = _ensure("FIELD_ENCRYPTION_KEY", lambda: Fernet.generate_key().decode())
DB_PATH = Path(os.environ.get("DB_PATH", BACKEND / "concierge.db"))
DEV_MODE = os.environ.get("DEV_MODE", "1") == "1"  # enables the dev mailbox page
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-opus-5-5")
AI_ENABLED = os.environ.get("AI_ENABLED", "1") == "1"
TWILIO_SID = os.environ.get("TWILIO_ACCOUNT_SID")
TWILIO_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN")
TWILIO_FROM = os.environ.get("TWILIO_FROM_NUMBER")
SESSION_HOURS = 12
