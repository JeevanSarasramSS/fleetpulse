"""FleetPulse REST + WebSocket API (presentation layer). Business logic lives in core/ and agent/."""
import asyncio
import base64
import json
import pathlib
import time
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from prometheus_client import Histogram, make_asgi_app
from pydantic import BaseModel, Field

from ..agent.copilot import Copilot
from ..core.security import can, decode_token, issue_token, mask_location, verify_password
from .deps import Principal, audit, current_user, pool, problem, rds, require

REQ_LATENCY = Histogram("fp_api_latency_seconds", "API latency", ["route"],
                        buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.2, 0.5, 1))
WEB = pathlib.Path(__file__).resolve().parents[2] / "web"


@asynccontextmanager
async def lifespan(app):
    await pool.open(wait=True, timeout=60)
    yield
    await pool.close()


app = FastAPI(title="FleetPulse API", version="1.0.0", lifespan=lifespan,
              description="Predictive maintenance and live fault alerts for mixed ICE/EV fleets.")
app.mount("/metrics", make_asgi_app())


@app.middleware("http")
async def timing_and_headers(request: Request, call_next):
    t0 = time.perf_counter()
    resp = await call_next(request)
    route = request.scope.get("route")
    REQ_LATENCY.labels(getattr(route, "path", "other")).observe(time.perf_counter() - t0)
    resp.headers.update({"X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY",
                         # origin only: map tile servers reject requests with no Referer at all
                         "Referrer-Policy": "strict-origin-when-cross-origin", "Cache-Control": "no-store"})
    return resp


@app.exception_handler(HTTPException)
async def http_problem(request: Request, exc: HTTPException):  # RFC 7807 problem+json errors
    return JSONResponse(problem(exc.status_code, str(exc.detail), request), status_code=exc.status_code,
                        headers=exc.headers, media_type="application/problem+json")


def _cursor_enc(v) -> str:
    return base64.urlsafe_b64encode(json.dumps(v).encode()).decode()


def _cursor_dec(c: str | None):
    if not c:
        return None
    try:
        return json.loads(base64.urlsafe_b64decode(c.encode()))
    except Exception:
        raise HTTPException(400, "bad cursor")


# ---------- auth ----------
class LoginIn(BaseModel):
    email: str = Field(max_length=200)
    password: str = Field(max_length=200)


@app.post("/api/v1/auth/token")
async def login(body: LoginIn):
    async with pool.connection() as conn:
        cur = await conn.execute("SELECT user_id, tenant_id, password_hash, role FROM app_user WHERE email = %s",
                                 (body.email.lower(),))
        row = await cur.fetchone()
        if not row or not verify_password(body.password, row[2]):
            await audit(conn, None, "login_failed", f"user:{body.email.lower()}", actor=body.email.lower()[:200])
            raise HTTPException(401, "invalid credentials")
        p = Principal({"sub": row[0], "email": body.email.lower(), "tid": row[1], "role": row[3]})
        await audit(conn, p, "login", f"user:{row[0]}")
    return {"access_token": issue_token(row[0], body.email.lower(), row[1], row[3]), "token_type": "bearer",
            "role": row[3], "tenant_id": row[1]}


# ---------- fleet overview ----------
@app.get("/api/v1/stats")
async def stats(p: Principal = Depends(current_user)):
    cached, fresh = await rds.mget(f"cache:stats:{p.tenant_id}", "stats:fresh_ms")
    if cached:  # 2 s TTL cache for the SQL counts; the freshness figure is always read live
        out = json.loads(cached)
        out["data_age_ms"] = None if fresh is None else int(fresh)
        return out
    async with pool.connection() as conn:
        cur = await conn.execute("""
          SELECT (SELECT count(*) FROM vehicle v JOIN fleet f USING (fleet_id) WHERE f.tenant_id = %(t)s),
                 (SELECT count(*) FROM alert WHERE tenant_id = %(t)s AND acked_at IS NULL),
                 (SELECT count(*) FROM alert WHERE tenant_id = %(t)s AND acked_at IS NULL AND severity >= 4),
                 (SELECT count(*) FROM risk_score WHERE tenant_id = %(t)s AND score >= 0.3)""", {"t": p.tenant_id})
        vehicles, open_alerts, critical, high_risk = await cur.fetchone()
    now = int(time.time())  # fleet-wide events/s: mean of the last 5 complete per-second buckets (all replicas)
    total, top, fresh, *secs = await rds.mget("stats:events", "stats:topdtc", "stats:fresh_ms",
                                              *(f"stats:eps:{now - i}" for i in range(1, 6)))
    eps = sum(int(x or 0) for x in secs) / 5
    out = {"vehicles": vehicles, "open_alerts": open_alerts, "critical_alerts": critical, "high_risk": high_risk,
            "events_per_sec": int(eps or 0), "events_total": int(total or 0), "top_dtcs": json.loads(top or "[]"),
            "data_age_ms": None if fresh is None else int(fresh)}  # vehicle timestamp -> readable in the API (median)
    await rds.set(f"cache:stats:{p.tenant_id}", json.dumps(out), ex=2)
    return out


@app.get("/api/v1/vehicles")
async def list_vehicles(p: Principal = Depends(require("read")), limit: int = Query(50, ge=1, le=500),
                        cursor: str | None = None, powertrain: str | None = Query(None, pattern="^(ICE|HEV|EV)$")):
    """Keyset pagination on VIN: O(log n) per page regardless of depth (no OFFSET scans)."""
    after = _cursor_dec(cursor) or ""
    async with pool.connection() as conn:
        cur = await conn.execute("""
          SELECT v.vin, m.name, m.powertrain, v.model_year, f.name, r.score
          FROM vehicle v JOIN fleet f USING (fleet_id) JOIN vehicle_model m USING (model_id)
          LEFT JOIN risk_score r USING (vin)
          WHERE f.tenant_id = %s AND v.vin > %s AND (%s::text IS NULL OR m.powertrain = %s)
          ORDER BY v.vin LIMIT %s""", (p.tenant_id, after, powertrain, powertrain, limit))
        rows = await cur.fetchall()
    items = [{"vin": r[0], "model": r[1], "powertrain": r[2], "year": r[3], "fleet": r[4],
              "risk": None if r[5] is None else round(r[5], 3)} for r in rows]
    return {"items": items, "next_cursor": _cursor_enc(rows[-1][0]) if len(rows) == limit else None}


@app.get("/api/v1/vehicles/{vin}")
async def vehicle_detail(vin: str, p: Principal = Depends(require("read"))):
    vin = vin.upper()
    async with pool.connection() as conn:
        cur = await conn.execute("""
          SELECT v.vin, m.oem, m.name, m.powertrain, v.model_year, f.name, m.service_interval_km, v.last_service_odo_km,
                 r.score, r.baseline_score, r.top_factors, r.scored_at
          FROM vehicle v JOIN fleet f USING (fleet_id) JOIN vehicle_model m USING (model_id)
          LEFT JOIN risk_score r USING (vin) WHERE v.vin = %s AND f.tenant_id = %s""", (vin, p.tenant_id))
        r = await cur.fetchone()
        if not r:
            raise HTTPException(404, "vehicle not found")  # same answer for other tenants' VINs: no enumeration
        cur = await conn.execute("""SELECT alert_id, rule, severity, detail, event_ts FROM alert
                                    WHERE tenant_id = %s AND vin = %s ORDER BY alert_id DESC LIMIT 10""", (p.tenant_id, vin))
        alerts = await cur.fetchall()
        cur = await conn.execute("""SELECT ts, speed_kmh, coolant_c, batt_v, soc_pct FROM telemetry
                                    WHERE vin = %s AND ts > now() - interval '30 minutes' ORDER BY ts DESC LIMIT 60""", (vin,))
        series = await cur.fetchall()
        await audit(conn, p, "read", f"vehicle:{vin}")
    live = await rds.hgetall(f"v:{vin}")
    if live:
        live.update(mask_location(float(live["lat"]), float(live["lon"]), p.role))
    return {"vin": r[0], "oem": r[1], "model": r[2], "powertrain": r[3], "year": r[4], "fleet": r[5],
            "service_interval_km": r[6], "last_service_odo_km": r[7],
            "risk": None if r[8] is None else {"score": r[8], "baseline": r[9], "factors": r[10], "scored_at": r[11]},
            "alerts": [{"alert_id": a[0], "rule": a[1], "severity": a[2], "detail": a[3], "event_ts": a[4]} for a in alerts],
            "series": [{"ts": s[0], "speed_kmh": s[1], "coolant_c": s[2], "batt_v": s[3], "soc_pct": s[4]} for s in series][::-1],
            "live": live or None}


@app.get("/api/v1/live")
async def live_positions(p: Principal = Depends(require("read")), lat: float = 20.5, lon: float = 78.9,
                         radius_km: float = Query(2500, le=3000), limit: int = Query(3000, le=10000)):
    """Positions from the Redis geo index (hot tier). Analysts get coarse, masked positions.

    COUNT would return only the `limit` vehicles nearest the centre (one depot city), so we take every
    match and keep an even stride: the map shows all depots. ~33K members per tenant is a few ms in Redis.
    """
    res = await rds.geosearch(f"geo:{p.tenant_id}", longitude=lon, latitude=lat, radius=radius_km, unit="km",
                              withcoord=True)
    total = len(res)
    if total > limit:
        res = res[::-(-total // limit)][:limit]
    out = []
    for vin, (lo, la) in res:
        m = mask_location(la, lo, p.role)
        out.append({"vin": vin, "lat": m["lat"], "lon": m["lon"]})
    return {"items": out, "total": total, "masked": not can(p.role, "precise_location")}


# Two static statements (not string-built SQL) so the open-alerts one can use the partial index.
ALERTS_ALL_SQL = """
  SELECT alert_id, vin, rule, severity, detail, event_ts, created_at, acked_at FROM alert
  WHERE tenant_id = %s AND alert_id < %s AND severity >= %s ORDER BY alert_id DESC LIMIT %s"""
ALERTS_OPEN_SQL = """
  SELECT alert_id, vin, rule, severity, detail, event_ts, created_at, acked_at FROM alert
  WHERE tenant_id = %s AND alert_id < %s AND severity >= %s AND acked_at IS NULL ORDER BY alert_id DESC LIMIT %s"""


@app.get("/api/v1/alerts")
async def list_alerts(p: Principal = Depends(require("read")), limit: int = Query(50, ge=1, le=200),
                      cursor: str | None = None, open_only: bool = True, min_severity: int = Query(1, ge=1, le=5)):
    before = _cursor_dec(cursor) or 2 ** 62
    async with pool.connection() as conn:
        cur = await conn.execute(ALERTS_OPEN_SQL if open_only else ALERTS_ALL_SQL, (p.tenant_id, before, min_severity, limit))
        rows = await cur.fetchall()
    items = [{"alert_id": r[0], "vin": r[1], "rule": r[2], "severity": r[3], "detail": r[4], "event_ts": r[5],
              "created_at": r[6], "acked_at": r[7]} for r in rows]
    return {"items": items, "next_cursor": _cursor_enc(rows[-1][0]) if len(rows) == limit else None}


@app.post("/api/v1/alerts/{alert_id}/ack")
async def ack_alert(alert_id: int, p: Principal = Depends(require("ack"))):
    async with pool.connection() as conn:
        cur = await conn.execute("""UPDATE alert SET acked_by = %s, acked_at = now()
                                    WHERE alert_id = %s AND tenant_id = %s AND acked_at IS NULL RETURNING alert_id""",
                                 (p.user_id, alert_id, p.tenant_id))
        if not await cur.fetchone():
            raise HTTPException(404, "alert not found or already acknowledged")
        await audit(conn, p, "ack", f"alert:{alert_id}")
    return {"ok": True}


@app.get("/api/v1/risk")
async def top_risk(p: Principal = Depends(require("read")), limit: int = Query(25, ge=1, le=200)):
    async with pool.connection() as conn:
        cur = await conn.execute("""
          SELECT r.vin, r.score, r.baseline_score, r.top_factors, m.name, m.powertrain, f.name
          FROM risk_score r JOIN vehicle v USING (vin) JOIN vehicle_model m USING (model_id) JOIN fleet f USING (fleet_id)
          WHERE r.tenant_id = %s ORDER BY r.score DESC LIMIT %s""", (p.tenant_id, limit))
        rows = await cur.fetchall()
    return {"items": [{"vin": r[0], "score": round(r[1], 3), "baseline": round(r[2], 3), "factors": r[3],
                       "model": r[4], "powertrain": r[5], "fleet": r[6]} for r in rows]}


# ---------- copilot + human-approved actions ----------
class AskIn(BaseModel):
    question: str = Field(min_length=2, max_length=500)


@app.post("/api/v1/copilot")
async def ask_copilot(body: AskIn, p: Principal = Depends(require("copilot"))):
    async with pool.connection() as conn:
        return await Copilot(conn, p).ask(body.question)


@app.get("/api/v1/work-orders")
async def list_work_orders(p: Principal = Depends(require("read"))):
    async with pool.connection() as conn:
        cur = await conn.execute("""SELECT work_order_id, vin, reason, est_cost_usd, status, proposed_by, created_at
                                    FROM work_order WHERE tenant_id = %s ORDER BY work_order_id DESC LIMIT 50""", (p.tenant_id,))
        rows = await cur.fetchall()
    return {"items": [dict(zip(["work_order_id", "vin", "reason", "est_cost_usd", "status", "proposed_by", "created_at"], r))
                      for r in rows]}


class DecisionIn(BaseModel):
    approve: bool


@app.post("/api/v1/work-orders/{wo_id}/decision")
async def decide_work_order(wo_id: int, body: DecisionIn, p: Principal = Depends(require("approve"))):
    async with pool.connection() as conn:
        cur = await conn.execute("""UPDATE work_order SET status = %s, approved_by = %s
                                    WHERE work_order_id = %s AND tenant_id = %s AND status = 'proposed' RETURNING vin""",
                                 ("approved" if body.approve else "rejected", p.user_id, wo_id, p.tenant_id))
        if not await cur.fetchone():
            raise HTTPException(404, "work order not found or already decided")
        await audit(conn, p, "approve" if body.approve else "reject", f"work_order:{wo_id}")
    return {"ok": True}


# ---------- compliance ----------
@app.delete("/api/v1/drivers/{driver_id}")
async def erase_driver(driver_id: int, p: Principal = Depends(require("erase"))):
    """Right to erasure (GDPR Art. 17 / DPDP s.12): null PII, keep anonymous operational rows."""
    async with pool.connection() as conn:
        cur = await conn.execute("""UPDATE driver d SET full_name = NULL, licence_no = NULL, erased_at = now()
                                    FROM fleet f WHERE d.fleet_id = f.fleet_id AND f.tenant_id = %s
                                    AND d.driver_id = %s AND d.erased_at IS NULL RETURNING d.driver_id""", (p.tenant_id, driver_id))
        if not await cur.fetchone():
            raise HTTPException(404, "driver not found or already erased")
        await audit(conn, p, "erase", f"driver:{driver_id}")
    return {"ok": True, "erased": driver_id}


@app.get("/api/v1/audit")
async def audit_log(p: Principal = Depends(require("audit")), limit: int = Query(50, le=200)):
    async with pool.connection() as conn:
        cur = await conn.execute("""SELECT audit_id, at, actor, action, resource, detail FROM audit_log
                                    WHERE tenant_id = %s ORDER BY audit_id DESC LIMIT %s""", (p.tenant_id, limit))
        rows = await cur.fetchall()
    return {"items": [dict(zip(["audit_id", "at", "actor", "action", "resource", "detail"], r)) for r in rows]}


@app.get("/healthz")
async def healthz():
    return {"ok": True}


@app.get("/readyz")
async def readyz():
    try:
        async with pool.connection(timeout=2) as conn:
            await conn.execute("SELECT 1")
        await rds.ping()
    except Exception as ex:
        raise HTTPException(503, f"not ready: {type(ex).__name__}")
    return {"ok": True}


# ---------- live alerts push ----------
@app.websocket("/ws/alerts")
async def ws_alerts(ws: WebSocket, token: str):
    try:
        claims = decode_token(token)
    except Exception:
        await ws.close(code=4401)
        return
    await ws.accept()
    ps = rds.pubsub()
    await ps.subscribe(f"alerts:{int(claims['tid'])}")  # tenant isolation at the channel level
    try:
        while True:
            msg = await ps.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if msg:
                data = json.loads(msg["data"])
                data["pushed_ms"] = int(time.time() * 1000)
                await ws.send_json(data)
            else:
                await asyncio.sleep(0.05)
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        await ps.unsubscribe()
        await ps.aclose()


if WEB.exists():
    app.mount("/static", StaticFiles(directory=WEB), name="static")

    @app.get("/")
    async def index():
        return FileResponse(WEB / "index.html")
