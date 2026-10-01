"""Password hashing, JWT issue/verify, RBAC and privacy masking."""
import base64
import hashlib
import hmac
import os
import time

import jwt

from .. import config
from .geo import geohash

ROLE_PERMS = {
    "admin": {"read", "ack", "approve", "erase", "audit", "copilot", "precise_location"},
    "fleet_manager": {"read", "ack", "approve", "copilot", "precise_location"},
    "analyst": {"read", "copilot"},  # analysts see masked (geohash-5, ~5 km) locations only
}


def hash_password(pw: str, iterations: int = 200_000) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, iterations)
    return f"pbkdf2${iterations}${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"


def verify_password(pw: str, stored: str) -> bool:
    try:
        _, it, salt, dk = stored.split("$")
        calc = hashlib.pbkdf2_hmac("sha256", pw.encode(), base64.b64decode(salt), int(it))
        return hmac.compare_digest(calc, base64.b64decode(dk))
    except (ValueError, TypeError):
        return False


def issue_token(user_id: int, email: str, tenant_id: int, role: str, now: float | None = None) -> str:
    now = now or time.time()
    claims = {"sub": str(user_id), "email": email, "tid": tenant_id, "role": role,
              "iat": int(now), "exp": int(now + config.JWT_TTL_MIN * 60), "iss": "fleetpulse"}
    return jwt.encode(claims, config.JWT_SECRET, algorithm="HS256")


def decode_token(token: str) -> dict:
    return jwt.decode(token, config.JWT_SECRET, algorithms=["HS256"], issuer="fleetpulse")


def can(role: str, perm: str) -> bool:
    return perm in ROLE_PERMS.get(role, set())


def mask_location(lat: float, lon: float, role: str) -> dict:
    if can(role, "precise_location"):
        return {"lat": lat, "lon": lon, "masked": False}
    gh = geohash(lat, lon, 5)
    return {"lat": round(lat, 1), "lon": round(lon, 1), "geohash": gh, "masked": True}
