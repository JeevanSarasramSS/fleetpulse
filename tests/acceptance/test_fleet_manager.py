import httpx
import pytest
from conftest import BASE, login
from pytest_bdd import given, scenarios, then, when

pytestmark = pytest.mark.integration
scenarios("features/fleet_manager.feature")


@when("I open the 7-day risk list", target_fixture="risk")
def open_risk(s):
    r = s.get("/api/v1/risk?limit=25")
    assert r.status_code == 200
    return r.json()["items"]


@then("I see vehicles ordered from highest to lowest risk")
def ordered(risk):
    assert risk, "no risk scores yet: the batch scorer runs every minute"
    scores = [v["score"] for v in risk]
    assert scores == sorted(scores, reverse=True)


@then("every vehicle has a reason for its risk")
def reasons(risk):
    assert all(v["factors"] for v in risk)


@given("there is an open alert in my fleet", target_fixture="alert")
def open_alert(s):
    items = s.get("/api/v1/alerts?limit=5").json()["items"]
    assert items, "no open alerts yet"
    return items[0]


@when("I acknowledge that alert")
def ack(s, alert):
    assert s.post(f"/api/v1/alerts/{alert['alert_id']}/ack").status_code == 200


@then("it is no longer in my open alerts")
def not_open(s, alert):
    ids = {a["alert_id"] for a in s.get("/api/v1/alerts?limit=200").json()["items"]}
    assert alert["alert_id"] not in ids


@then("the audit log records who acknowledged it")
def ack_audited(s, alert):
    rows = httpx.get(f"{BASE}/api/v1/audit?limit=200", headers=login("admin@aurora.demo"), timeout=30).json()["items"]
    assert any(a["action"] == "ack" and a["resource"] == f"alert:{alert['alert_id']}" and a["actor"] == s.email
               for a in rows)


@when("I ask the copilot to schedule a work order for my riskiest vehicle", target_fixture="answer")
def ask_copilot(s):
    vin = s.get("/api/v1/risk?limit=1").json()["items"][0]["vin"]
    r = s.post("/api/v1/copilot", json={"question": f"schedule a work order for {vin}"})
    assert r.status_code == 200
    s.ctx["vin"] = vin
    return r.json()


@then("a work order is proposed and waiting for approval")
def proposed(s, answer):
    assert "propose_work_order" in [t["tool"] for t in answer["trace"]]
    wo = next(w for w in s.get("/api/v1/work-orders").json()["items"] if w["vin"] == s.ctx["vin"])
    assert wo["status"] == "proposed" and wo["proposed_by"].startswith("agent:")
    s.ctx["wo"] = wo["work_order_id"]


@when("I approve that work order")
def approve(s):
    assert s.post(f"/api/v1/work-orders/{s.ctx['wo']}/decision", json={"approve": True}).status_code == 200


@then("the work order is approved")
def approved(s):
    wo = next(w for w in s.get("/api/v1/work-orders").json()["items"] if w["work_order_id"] == s.ctx["wo"])
    assert wo["status"] == "approved"
