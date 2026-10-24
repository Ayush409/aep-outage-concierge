"""Password hashing, session tokens, role checks and field-level encryption."""
import hashlib
import secrets
import time

import bcrypt
import jwt
from cryptography.fernet import Fernet
from fastapi import Cookie, Depends, HTTPException

from . import db
from .config import FIELD_KEY, JWT_SECRET, SESSION_HOURS

_fernet = Fernet(FIELD_KEY.encode())
COOKIE = "concierge_session"


def hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt(rounds=12)).decode()


def check_password(pw: str, hashed: str) -> bool:
    return bcrypt.checkpw(pw.encode(), hashed.encode())


def encrypt(value: str | None) -> str | None:
    return None if value is None else _fernet.encrypt(value.encode()).decode()


def decrypt(token: str | None) -> str | None:
    return None if token is None else _fernet.decrypt(token.encode()).decode()


def make_session(user_id: int, role: str) -> str:
    now = int(time.time())
    return jwt.encode({"sub": str(user_id), "role": role, "iat": now, "exp": now + SESSION_HOURS * 3600},
                      JWT_SECRET, algorithm="HS256")


def new_reset_token() -> tuple[str, str]:
    token = secrets.token_urlsafe(32)
    return token, hashlib.sha256(token.encode()).hexdigest()


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def current_user(concierge_session: str | None = Cookie(default=None)) -> dict:
    if not concierge_session:
        raise HTTPException(401, "Not signed in")
    try:
        claims = jwt.decode(concierge_session, JWT_SECRET, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(401, "Session expired")
    with db.tx() as con:
        row = con.execute("SELECT id, email, name, role FROM users WHERE id = ?", (int(claims["sub"]),)).fetchone()
    if row is None:
        raise HTTPException(401, "Account not found")
    return dict(row)


def require_aep(user: dict = Depends(current_user)) -> dict:
    """Server-side role check: every /api/aep route depends on this, not just hidden tabs."""
    if user["role"] != "aep":
        db.audit(user["id"], "denied_aep_access")
        raise HTTPException(403, "AEP operators only")
    return user


def require_customer(user: dict = Depends(current_user)) -> dict:
    if user["role"] != "customer":
        raise HTTPException(403, "Customer accounts only")
    return user
