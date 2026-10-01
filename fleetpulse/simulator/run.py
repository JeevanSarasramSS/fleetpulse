"""Telemetry simulator: 100K vehicles, two OEM payload formats, bursts, duplicates, out-of-order.

Every vehicle has a hidden wear level that drives coolant temperature, 12V voltage, misfires and
HV battery faults, so the stream carries a learnable pre-failure signal.
"""
import argparse
import json
import math
import random
import time
from datetime import datetime, timezone

import numpy as np

from .. import config
from .fleetgen import MODELS, make_fleets, make_vehicles

MODEL = {m[0]: m for m in MODELS}


class Fleet:
    def __init__(self, n: int, seed: int = 3):
        fleets = make_fleets()
        home = {f[0]: (f[3], f[4]) for f in fleets}
        rows = list(make_vehicles(n, fleets))
        self.vins = [r[0] for r in rows]
        self.oem = [MODEL[r[2]][1] for r in rows]
        self.pt = [MODEL[r[2]][3] for r in rows]
        self.rng = np.random.default_rng(seed)
        self.lat = np.array([home[r[1]][0] for r in rows]) + self.rng.normal(0, 0.08, n)
        self.lon = np.array([home[r[1]][1] for r in rows]) + self.rng.normal(0, 0.08, n)
        self.heading = self.rng.uniform(0, 2 * math.pi, n)
        self.speed = self.rng.uniform(0, 60, n)
        self.odo = np.array([r[5] for r in rows])
        self.wear = np.array([r[6] for r in rows])
        self.soc = self.rng.uniform(20, 95, n)
        self.fuel = self.rng.uniform(15, 95, n)
        self.seq = np.zeros(n, dtype=np.int64)
        self.n = n

    def step(self, idx: np.ndarray, dt: float):
        k = len(idx)
        r = self.rng
        # speed random walk with stops (traffic lights, deliveries)
        sp = np.clip(self.speed[idx] + r.normal(0, 6, k), 0, 110)
        sp[r.random(k) < 0.05] = 0
        self.speed[idx] = sp
        self.heading[idx] += r.normal(0, 0.2, k)
        d_km = sp * dt / 3600
        self.lat[idx] += d_km / 111 * np.cos(self.heading[idx])
        self.lon[idx] += d_km / 111 * np.sin(self.heading[idx])
        self.odo[idx] += d_km
        self.soc[idx] = np.clip(self.soc[idx] - d_km * 0.18, 3, 100)
        self.fuel[idx] = np.clip(self.fuel[idx] - d_km * 0.08, 2, 100)
        self.seq[idx] += 1


def _dtcs(rnd: random.Random, wear: float, pt: str) -> list[str]:
    out = []
    p = 0.0004 + 0.02 * wear ** 4
    if rnd.random() < p:
        pool = ["P0301", "P0420", "P0171", "P0562", "C0035", "C1214", "U0100"]
        if pt != "ICE":
            pool += ["P0A80", "P0AA6"]
        out.append(rnd.choice(pool))
    if wear > 0.85 and rnd.random() < 0.004:
        out.append("P0217" if pt != "EV" else "P0AA6")  # critical
    return out


def make_payload(f: Fleet, i: int, rnd: random.Random, now: float) -> dict:
    w, pt = float(f.wear[i]), f.pt[i]
    coolant = None if pt == "EV" else 86 + 28 * w ** 2 + rnd.gauss(0, 2)
    batt_v = 12.7 - 1.3 * w ** 1.5 + rnd.gauss(0, 0.08)
    evt = "HARSH_BRAKE" if rnd.random() < 0.002 else ("IDLE" if f.speed[i] == 0 and rnd.random() < 0.01 else None)
    dtcs = _dtcs(rnd, w, pt)
    soc = round(float(f.soc[i]), 1) if pt != "ICE" else None
    fuel = round(float(f.fuel[i]), 1) if pt != "EV" else None
    if f.oem[i] == "aurora":
        p = {"vin": f.vins[i], "ts": datetime.fromtimestamp(now, timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
             "seq": int(f.seq[i]), "lat": round(float(f.lat[i]), 5), "lon": round(float(f.lon[i]), 5),
             "speed_kmh": round(float(f.speed[i]), 1), "odo_km": round(float(f.odo[i]), 1),
             "soc_pct": soc, "fuel_pct": fuel, "batt_v": round(batt_v, 2), "dtc": dtcs, "evt": evt}
        if coolant is not None:
            p["coolant_c"] = round(coolant, 1)
        return p
    sig = {"speedMph": round(float(f.speed[i]) / 1.609344, 1), "odometerMi": round(float(f.odo[i]) / 1.609344, 1),
           "batteryPct": soc, "fuelPct": fuel, "lvBatteryVolts": round(batt_v, 2)}
    if coolant is not None:
        sig["coolantTempF"] = round(coolant * 9 / 5 + 32, 1)
    return {"vehicleId": f.vins[i], "epoch": round(now, 3), "counter": int(f.seq[i]),
            "position": {"latitude": round(float(f.lat[i]), 5), "longitude": round(float(f.lon[i]), 5)},
            "signals": sig, "eventType": evt, "faultString": ";".join(f"DTC:{d}" for d in dtcs)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--vehicles", type=int, default=config.NUM_VEHICLES)
    ap.add_argument("--rate", type=int, default=config.EVENTS_PER_SEC, help="events/sec baseline")
    ap.add_argument("--duration", type=float, default=0, help="seconds, 0 = forever")
    ap.add_argument("--dup", type=float, default=0.01)
    ap.add_argument("--ooo", type=float, default=0.02)
    ap.add_argument("--burst-every", type=float, default=120)
    ap.add_argument("--stdout", action="store_true", help="print JSON lines instead of Kafka")
    a = ap.parse_args()

    from confluent_kafka import Producer
    prod = None if a.stdout else Producer({"bootstrap.servers": config.KAFKA_BOOTSTRAP, "linger.ms": 20,
                                           "compression.type": "lz4", "enable.idempotence": True,
                                           "queue.buffering.max.messages": 2_000_000})
    t_build = time.time()
    fleet = Fleet(a.vehicles)
    print(f"simulating {fleet.n} vehicles (built in {time.time() - t_build:.1f}s), base rate {a.rate}/s", flush=True)
    rnd, tick, cursor, held, sent, t0 = random.Random(5), 0.1, 0, [], 0, time.time()
    while not a.duration or time.time() - t0 < a.duration:
        start = time.time()
        burst = a.burst_every and (start - t0) % a.burst_every < 10  # 3x burst for 10s every N s
        k = int(a.rate * tick * (3 if burst else 1))
        idx = (np.arange(cursor, cursor + k) % fleet.n)
        cursor = (cursor + k) % fleet.n
        fleet.step(idx, dt=fleet.n / max(a.rate, 1))
        out = held
        held = []
        for i in idx:
            p = make_payload(fleet, int(i), rnd, start)
            r = rnd.random()
            if r < a.ooo:
                held.append(p)  # delivered next tick -> out of order
                continue
            out.append(p)
            if r < a.ooo + a.dup:
                out.append(p)  # duplicate delivery (at-least-once device retry)
        for p in out:
            key = p.get("vin") or p.get("vehicleId")
            if prod is None:
                print(json.dumps(p))
            else:
                while True:
                    try:
                        prod.produce(config.TOPIC_RAW, json.dumps(p).encode(), key=key.encode())
                        break
                    except BufferError:  # back-pressure: wait for broker to drain
                        prod.poll(0.05)
        sent += len(out)
        if prod is not None:
            prod.poll(0)
        if int(start - t0) % 10 == 0 and (start - t0) % 10 < tick:
            print(f"t={start - t0:.0f}s sent={sent} rate~{sent / max(time.time() - t0, 1e-6):.0f}/s burst={bool(burst)}", flush=True)
        time.sleep(max(0.0, tick - (time.time() - start)))
    if prod is not None:
        prod.flush(30)
    print(f"done: {sent} events in {time.time() - t0:.1f}s", flush=True)


if __name__ == "__main__":
    main()
