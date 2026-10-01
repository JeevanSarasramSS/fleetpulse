import httpx
import pytest
from conftest import BASE, login
from pytest_bdd import scenarios, then, when

pytestmark = pytest.mark.integration
scenarios("features/privacy.feature")


@when("I open the live map", target_fixture="live")
def live(s):
    return s.get("/api/v1/live?limit=50").json()


@then("vehicle locations are masked")
def masked(live):
    assert live["masked"] is True
    assert all(round(v["lat"], 1) == v["lat"] and round(v["lon"], 1) == v["lon"] for v in live["items"])


@then("I am not allowed to acknowledge alerts")
def cannot_ack(s):
    assert s.post("/api/v1/alerts/1/ack").status_code == 403


@when("I look up a vehicle that belongs to Aurora Logistics", target_fixture="lookup")
def lookup(s):
    vin = httpx.get(f"{BASE}/api/v1/vehicles?limit=1", headers=login("manager@aurora.demo"), timeout=30).json()["items"][0]["vin"]
    return s.get(f"/api/v1/vehicles/{vin}")


@then("the vehicle is not found")
def not_found(lookup):
    assert lookup.status_code == 404


@when("I erase a driver's personal data", target_fixture="erased")
def erase(s):
    for d in range(1, 2000):
        if s.delete(f"/api/v1/drivers/{d}").status_code == 200:
            return d
    pytest.fail("no erasable driver found in this tenant")


@then("the erasure is recorded in the audit log")
def erase_audited(s, erased):
    rows = s.get("/api/v1/audit?limit=200").json()["items"]
    assert any(a["action"] == "erase" and a["resource"] == f"driver:{erased}" for a in rows)
