"""SQLite storage. Customer address, ZIP and phone are encrypted at the field level (see security.py)."""
import json
import sqlite3
import time
from contextlib import contextmanager

from .config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  email TEXT UNIQUE NOT NULL,
  name TEXT NOT NULL,
  pw_hash TEXT NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('customer', 'aep')),
  created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS customer_profiles (
  user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  premise TEXT NOT NULL,            -- anonymized premise id (link to grid data)
  address_enc TEXT NOT NULL,        -- Fernet ciphertext
  zip_enc TEXT NOT NULL,            -- Fernet ciphertext
  phone_enc TEXT,                   -- Fernet ciphertext
  needs_enc TEXT,                   -- Fernet ciphertext of declared needs (JSON list)
  alerts_sms INTEGER NOT NULL DEFAULT 1,
  alerts_inapp INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS reset_tokens (
  token_hash TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  expires REAL NOT NULL,
  used INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS mailbox (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  to_email TEXT NOT NULL, subject TEXT NOT NULL, body TEXT NOT NULL, created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS notifications (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,  -- NULL = AEP operations feed
  scenario TEXT NOT NULL, kind TEXT NOT NULL, band TEXT, channel TEXT NOT NULL,
  title TEXT NOT NULL, body TEXT NOT NULL, created REAL NOT NULL, read INTEGER NOT NULL DEFAULT 0,
  escalation INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS phone_codes (
  user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  code_hash TEXT NOT NULL, expires REAL NOT NULL, attempts INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS audit (
  id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, action TEXT NOT NULL, detail TEXT, ts REAL NOT NULL
);
"""

DEFAULT_SETTINGS = {
    "customer_alert_threshold": "Elevated",
    "active_scenario": "live",
    "life_support_one_band_lower": "1",
}


def connect() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


@contextmanager
def tx():
    con = connect()
    try:
        yield con
        con.commit()
    finally:
        con.close()


def init():
    with tx() as con:
        con.executescript(SCHEMA)
        cols = {r["name"] for r in con.execute("PRAGMA table_info(customer_profiles)")}
        if "phone_verified" not in cols:  # added after the first release
            con.execute("ALTER TABLE customer_profiles ADD COLUMN phone_verified INTEGER NOT NULL DEFAULT 0")
        for k, v in DEFAULT_SETTINGS.items():
            con.execute("INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)", (k, v))


def get_setting(key: str) -> str:
    with tx() as con:
        row = con.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else DEFAULT_SETTINGS.get(key, "")


def set_setting(key: str, value: str):
    with tx() as con:
        con.execute("INSERT INTO settings(key, value) VALUES (?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))


def audit(user_id, action: str, detail=None):
    with tx() as con:
        con.execute("INSERT INTO audit(user_id, action, detail, ts) VALUES (?, ?, ?, ?)",
                    (user_id, action, json.dumps(detail) if detail is not None else None, time.time()))
