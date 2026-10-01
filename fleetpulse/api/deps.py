"""Infrastructure adapters and request-scoped dependencies (auth, tenancy, rate limiting, audit)."""
import json
import time

import psycopg_pool
import redis.asyncio as aioredis
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .. import config
from ..core.security import can, decode_token

pool = psycopg_pool.AsyncConnectionPool(config.PG_DSN, min_size=2, max_size=20, open=False)
rds = aioredis.Redis.from_url(config.REDIS_URL, decode_responses=True)
bearer = HTTPBearer(auto_error=False)


class Principal:
    def __init__(self, claims: dict):
        self.user_id = int(claims["sub"])
        self.email = claims["email"]
        self.tenant_id = int(claims["tid"])
        self.role = claims["role"]


async def current_user(creds: HTTPAuthorizationCredentials | None = Depends(bearer)) -> Principal:
    if creds is None:
        raise HTTPException(401, "missing bearer token")
    try:
        p = Principal(decode_token(creds.credentials))
    except Exception:
        raise HTTPException(401, "invalid or expired token")
    # Fixed-window rate limit per user (Redis INCR + EXPIRE): O(1), shared across API replicas
    key = f"rl:{p.user_id}:{int(time.time() // 60)}"
    try:
        n = await rds.incr(key)
        if n == 1:
            await rds.expire(key, 61)
        if n > config.RATE_LIMIT_PER_MIN:
            raise HTTPException(429, "rate limit exceeded", headers={"Retry-After": "60"})
    except aioredis.RedisError:
        pass  # graceful degradation: fail open on limiter outage, never block reads
    return p


def require(perm: str):
    async def dep(p: Principal = Depends(current_user)) -> Principal:
        if not can(p.role, perm):
            raise HTTPException(403, f"role '{p.role}' lacks '{perm}'")
        return p
    return dep


async def audit(conn, p: Principal | None, action: str, resource: str, detail: dict | None = None, actor: str | None = None):
    await conn.execute(
        "INSERT INTO audit_log (tenant_id, actor, action, resource, detail) VALUES (%s, %s, %s, %s, %s)",
        (p.tenant_id if p else None, actor or (p.email if p else "anonymous"), action, resource, json.dumps(detail or {})))


def problem(status: int, title: str, request: Request):
    return {"type": "about:blank", "title": title, "status": status, "instance": str(request.url.path)}
