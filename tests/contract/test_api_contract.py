"""Consumer-driven contract tests (Pact-style, without a broker).

The consumer is the web dashboard (web/index.html). Each contract lists the request it makes and the
fields and types it reads from the response. The provider (the live API) is verified against them, so a
renamed or retyped field breaks CI before it breaks the dashboard. Run with the integration suite.
"""
import os
import time

import httpx
import pytest

BASE = os.environ.get("FP_BASE", "http://localhost:8000")
pytestmark = pytest.mark.integration

NUM = (int, float)
OPT = type(None)

# (method, path, body, expected status, {field path: allowed types}); "items[]" checks the first list element.
CONTRACTS = [
    ("GET", "/api/v1/stats", None, 200,
     {"vehicles": int, "events_per_sec": int, "critical_alerts": int, "open_alerts": int, "high_risk": int,
      "events_total": int, "top_dtcs": list}),
    ("GET", "/api/v1/live?limit=10", None, 200,
     {"masked": bool, "total": int, "items[].vin": str, "items[].lat": NUM, "items[].lon": NUM}),
    ("GET", "/api/v1/alerts?limit=5&min_severity=3", None, 200,
     {"items[].alert_id": int, "items[].vin": str, "items[].rule": str, "items[].severity": int,
      "items[].detail": dict, "next_cursor": (str, OPT)}),
    ("GET", "/api/v1/risk?limit=5", None, 200,
     {"items[].vin": str, "items[].score": NUM, "items[].baseline": NUM, "items[].model": str,
      "items[].factors": list}),
    ("GET", "/api/v1/vehicles?limit=5", None, 200,
     {"items[].vin": str, "items[].model": str, "items[].powertrain": str, "next_cursor": (str, OPT)}),
    ("GET", "/api/v1/work-orders", None, 200, {"items": list}),
    ("POST", "/api/v1/copilot", {"question": "what's critical right now"}, 200,
     {"answer": str, "mode": str, "trace": list}),
    ("POST", "/api/v1/copilot", {"question": "x" * 600}, 422, {}),  # input bound enforced
    ("GET", "/api/v1/vehicles/NOTAVIN0000000000", None, 404, {"title": str, "status": int}),  # RFC 7807
]


def _get(obj, path):
    for part in path.split("."):
        if part.endswith("[]"):
            lst = obj[part[:-2]]
            assert lst, f"{part[:-2]} is empty, cannot verify element fields"
            obj = lst[0]
        else:
            obj = obj[part]
    return obj


@pytest.fixture(scope="module")
def headers():
    r = httpx.post(f"{BASE}/api/v1/auth/token", json={"email": "manager@aurora.demo", "password": "demo1234"})
    r.raise_for_status()
    body = r.json()
    assert isinstance(body["access_token"], str) and body["token_type"] == "bearer"  # login contract
    h = {"Authorization": f"Bearer {body['access_token']}"}
    deadline = time.time() + 240  # fresh stack: first risk scores land after a batch run or two
    while time.time() < deadline and not (httpx.get(f"{BASE}/api/v1/risk?limit=1", headers=h).json()["items"]
                                          and httpx.get(f"{BASE}/api/v1/alerts?limit=1", headers=h).json()["items"]):
        time.sleep(5)
    return h


@pytest.mark.parametrize("method,path,body,status,fields", CONTRACTS, ids=[f"{c[0]} {c[1][:40]}" for c in CONTRACTS])
def test_provider_honours_consumer_contract(headers, method, path, body, status, fields):
    r = httpx.request(method, BASE + path, json=body, headers=headers, timeout=30)
    assert r.status_code == status, r.text[:200]
    data = r.json()
    for field, types in fields.items():
        assert isinstance(_get(data, field), types), f"{field}: {type(_get(data, field)).__name__}"


def test_openapi_documents_every_consumed_route():
    spec = httpx.get(f"{BASE}/openapi.json").json()["paths"]
    for method, path, *_ in CONTRACTS:
        route = path.split("?")[0]
        templ = "/api/v1/vehicles/{vin}" if route.startswith("/api/v1/vehicles/") else route
        assert method.lower() in spec[templ], f"{method} {templ} missing from OpenAPI"
