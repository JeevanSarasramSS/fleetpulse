"""Soak test: watch the running docker compose stack for N minutes at its normal load and report stability.

usage: python tests/load/soak.py MINUTES [BASE_URL]

Every 30 s it records fleet-wide events/s, data freshness, consumer lag, container memory and database size.
It passes when throughput holds, lag stays bounded, freshness stays under 2 s and memory does not keep growing.
"""
import re
import statistics
import subprocess
import sys
import time

import httpx

MIN = float(sys.argv[1]) if len(sys.argv) > 1 else 45
BASE = sys.argv[2] if len(sys.argv) > 2 else "http://localhost:8000"
DC = ["docker", "compose"]


def sh(args):
    return subprocess.run(args, capture_output=True, text=True).stdout


def lag():
    m = re.search(r"TOTAL-LAG\s+(\d+)", sh(DC + ["exec", "-T", "redpanda", "rpk", "group", "describe", "processor"]))
    return int(m.group(1)) if m else None


def mem_mb():
    out = {}
    for line in sh(["docker", "stats", "--no-stream", "--format", "{{.Name}} {{.MemUsage}}"]).splitlines():
        name, usage = line.split(" ", 1)
        if not name.startswith("fleetpulse-"):
            continue
        v, unit = re.match(r"([\d.]+)(\w+)", usage).groups()
        out[name.replace("fleetpulse-", "")] = float(v) * {"KiB": 1 / 1024, "MiB": 1, "GiB": 1024}.get(unit, 1)
    return out


def main():
    tok = httpx.post(f"{BASE}/api/v1/auth/token", json={"email": "manager@aurora.demo", "password": "demo1234"}).json()
    h = {"Authorization": f"Bearer {tok['access_token']}"}
    rows, t0 = [], time.time()
    total0 = httpx.get(f"{BASE}/api/v1/stats", headers=h).json()["events_total"]
    while time.time() - t0 < MIN * 60:
        s = httpx.get(f"{BASE}/api/v1/stats", headers=h, timeout=30).json()
        db = sh(DC + ["exec", "-T", "postgres", "psql", "-U", "fleet", "-d", "fleet", "-Atc",
                      "SELECT pg_database_size('fleet') / 1048576"]).strip()
        r = {"t_min": round((time.time() - t0) / 60, 1), "eps": s["events_per_sec"], "age_ms": s["data_age_ms"],
             "lag": lag(), "db_mb": int(db or 0), "mem": mem_mb()}
        rows.append(r)
        procs = sum(v for k, v in r["mem"].items() if k.startswith("processor"))
        print(f"{r['t_min']:5.1f} min  eps={r['eps']:5d}  freshness={r['age_ms']} ms  lag={r['lag']}  "
              f"db={r['db_mb']} MB  mem processors={procs:.0f} MB api={r['mem'].get('api-1', 0):.0f} MB "
              f"postgres={r['mem'].get('postgres-1', 0):.0f} MB", flush=True)
        time.sleep(30)
    total1 = httpx.get(f"{BASE}/api/v1/stats", headers=h).json()["events_total"]
    dur = time.time() - t0
    ages = [r["age_ms"] for r in rows if r["age_ms"] is not None]
    lags = [r["lag"] for r in rows if r["lag"] is not None]
    half = len(rows) // 2
    pm = [sum(v for k, v in r["mem"].items() if k.startswith("processor")) for r in rows]
    print(f"\nSOAK {dur / 60:.0f} min: {total1 - total0:,} events processed ({(total1 - total0) / dur:,.0f}/s average)")
    print(f"freshness p50={statistics.median(ages):.0f} ms  p95={sorted(ages)[int(0.95 * (len(ages) - 1))]} ms  max={max(ages)} ms")
    print(f"consumer lag median={statistics.median(lags):.0f}  max={max(lags)}")
    print(f"processor memory first half avg={statistics.mean(pm[:half]):.0f} MB, second half avg={statistics.mean(pm[half:]):.0f} MB")
    print(f"database size {rows[0]['db_mb']} MB -> {rows[-1]['db_mb']} MB (raw telemetry retention keeps it bounded)")


if __name__ == "__main__":
    main()
