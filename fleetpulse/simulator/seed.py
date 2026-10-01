"""Seed Postgres with 100K vehicles, drivers, users and the fault knowledge base. Idempotent."""
import io
import os
import sys
import time

import psycopg

from .. import config
from ..core.embed import embed, to_pgvector
from ..core.security import hash_password
from .fleetgen import MODELS, TENANTS, make_drivers, make_fleets, make_vehicles

KNOWLEDGE = [
    ("P0301", "Cylinder 1 misfire", "Misfire on cylinder 1. Common causes: worn spark plug, failed ignition coil, injector clog. Continued driving damages the catalytic converter. Replace plug and coil, inspect injector.", 180),
    ("P0217", "Engine over-temperature", "Coolant over-temperature. Stop the vehicle. Causes: low coolant, failed water pump, stuck thermostat, radiator fan failure. Risk of head gasket failure and engine seizure.", 650),
    ("P0420", "Catalyst efficiency low", "Catalytic converter efficiency below threshold. Often follows untreated misfires. Check O2 sensors first, then replace converter.", 900),
    ("P0171", "System too lean", "Lean fuel mixture. Vacuum leak, dirty MAF sensor or weak fuel pump. Clean MAF, smoke-test intake.", 220),
    ("P0562", "Low system voltage", "12V system voltage low. Failing 12V battery or alternator. Vehicle may not start; replace battery if below 11.8V at rest.", 160),
    ("P0A80", "Replace hybrid/EV battery", "High-voltage battery pack degradation, cell imbalance detected. Reduced range. Schedule HV battery diagnostics and module replacement.", 4200),
    ("P0AA6", "HV isolation fault", "High-voltage isolation fault. Safety critical: risk of shock. Vehicle must be stopped and inspected by certified EV technician.", 1500),
    ("C0035", "Wheel speed sensor", "Left front wheel speed sensor fault. ABS and stability control disabled. Replace sensor and check wiring.", 140),
    ("C1214", "Brake control relay", "Brake control relay circuit open. ABS warning. Inspect relay and fuse; braking performance may be reduced.", 260),
    ("U0100", "Lost comms with ECM", "CAN bus lost communication with engine control module. Check wiring harness and ECM power; vehicle may stall.", 480),
    (None, "Excessive idling", "Idling over 10 minutes wastes about 0.8 L of fuel per hour for vans and accelerates engine wear. Coach drivers and enable auto start-stop.", 0),
    (None, "Harsh braking pattern", "Repeated harsh braking wears pads and rotors early and signals unsafe following distance. Driver coaching cuts brake wear by about 20 percent.", 300),
    (None, "Coolant temperature trend", "Coolant temperature creeping above 100C over several days usually precedes thermostat or water pump failure within a week.", 400),
    (None, "12V battery voltage trend", "Resting voltage dropping below 12.2V across days predicts a no-start within 7 days in most fleet vans.", 160),
]

USERS = [  # (tenant, email, role)
    (1, "admin@aurora.demo", "admin"), (1, "manager@aurora.demo", "fleet_manager"), (1, "analyst@aurora.demo", "analyst"),
    (2, "admin@borealis.demo", "admin"), (2, "manager@borealis.demo", "fleet_manager"),
    (3, "admin@coastal.demo", "admin"), (3, "manager@coastal.demo", "fleet_manager"),
]


def _copy(cur, table, cols, rows):
    with cur.copy(f"COPY {table} ({', '.join(cols)}) FROM STDIN") as cp:
        for r in rows:
            cp.write_row(r)


def seed(n_vehicles: int):
    with psycopg.connect(config.PG_DSN, autocommit=False) as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM vehicle")
        if cur.fetchone()[0] >= n_vehicles:
            print(f"already seeded ({n_vehicles}+ vehicles)")
            return
        t0 = time.time()
        _copy(cur, "tenant", ["tenant_id", "name"], TENANTS)
        cur.execute("INSERT INTO subscription_plan VALUES ('growth', 50000, 4.50), ('enterprise', 1000000, 3.20)")
        cur.executemany("INSERT INTO subscription (tenant_id, plan_code, starts_on) VALUES (%s, %s, '2026-01-01')",
                        [(1, "enterprise"), (2, "enterprise"), (3, "growth")])
        pw = hash_password(os.environ.get("DEMO_PASSWORD", "demo1234"))
        cur.executemany("INSERT INTO app_user (tenant_id, email, password_hash, role) VALUES (%s,%s,%s,%s)",
                        [(t, e, pw, r) for t, e, r in USERS])
        fleets = make_fleets()
        _copy(cur, "fleet", ["fleet_id", "tenant_id", "name", "home_lat", "home_lon"], fleets)
        _copy(cur, "vehicle_model", ["model_id", "oem", "name", "powertrain", "service_interval_km"], MODELS)
        _copy(cur, "vehicle", ["vin", "fleet_id", "model_id", "model_year", "last_service_odo_km"],
              (v[:5] for v in make_vehicles(n_vehicles, fleets)))
        _copy(cur, "driver", ["driver_id", "fleet_id", "full_name", "licence_no"], make_drivers(n_vehicles // 3, fleets))
        _copy(cur, "fault_knowledge", ["dtc", "title", "body", "avg_repair_usd", "embedding"],
              ((d, t, b, c, to_pgvector(embed(f"{d or ''} {t} {b}"))) for d, t, b, c in KNOWLEDGE))
        conn.commit()
        print(f"seeded {n_vehicles} vehicles in {time.time() - t0:.1f}s")


if __name__ == "__main__":
    for i in range(30):
        try:
            seed(int(sys.argv[1]) if len(sys.argv) > 1 else config.NUM_VEHICLES)
            break
        except psycopg.OperationalError as e:
            print("waiting for postgres:", e)
            time.sleep(2)
