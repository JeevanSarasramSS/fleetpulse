"""Shared steps for the BDD acceptance suite (pytest-bdd), run against the docker compose stack."""
import os
import time

import httpx
import pytest
from pytest_bdd import given, parsers

BASE = os.environ.get("FP_BASE", "http://localhost:8000")


def login(email: str) -> dict:
    r = httpx.post(f"{BASE}/api/v1/auth/token", json={"email": email, "password": "demo1234"}, timeout=30)
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


class Session:
    """The signed-in user plus whatever earlier steps found (alert, VIN, work order)."""

    def __init__(self):
        self.email, self.headers, self.ctx = None, {}, {}

    def get(self, path):
        return httpx.get(BASE + path, headers=self.headers, timeout=30)

    def post(self, path, **kw):
        return httpx.post(BASE + path, headers=self.headers, timeout=30, **kw)

    def delete(self, path):
        return httpx.delete(BASE + path, headers=self.headers, timeout=30)


@pytest.fixture
def s():
    return Session()


@pytest.fixture(scope="session", autouse=True)
def stack_warmed_up():
    """On a fresh stack the first risk scores land after one or two batch runs; wait rather than flake."""
    h, deadline = login("manager@aurora.demo"), time.time() + 240
    while time.time() < deadline:
        risk = httpx.get(f"{BASE}/api/v1/risk?limit=1", headers=h, timeout=30).json()["items"]
        alerts = httpx.get(f"{BASE}/api/v1/alerts?limit=1", headers=h, timeout=30).json()["items"]
        if risk and alerts:
            return
        time.sleep(5)


@given(parsers.parse('I am signed in as "{email}"'))
def signed_in(s, email):
    s.email, s.headers = email, login(email)
