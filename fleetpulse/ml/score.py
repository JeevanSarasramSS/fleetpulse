"""Batch job: roll new telemetry into the warm tier, enforce hot-tier retention, score every vehicle. Runs on an interval."""
import json
import os
import pathlib
import time

import joblib
import numpy as np
import psycopg

from .. import config
from .features import FEATURE_SQL, FEATURES, row_to_features

MODEL_PATH = pathlib.Path(__file__).parent / "model.joblib"
LIFECYCLE_SQL = pathlib.Path(__file__).resolve().parents[2] / "db" / "002_lifecycle.sql"
RETENTION_HOURS = int(os.environ.get("TELEMETRY_RETENTION_HOURS", "2"))
LATE_S = 60  # rows newer than this may still be in flight (out-of-order, processor backlog); rolled up next run
LABELS = {"service_overdue_ratio": "overdue for service", "vehicle_age_yrs": "vehicle age", "odo_10k_km": "high mileage",
          "max_coolant_7d": "coolant running hot", "min_batt_v_7d": "12V battery voltage low",
          "dtc_events_7d": "frequent fault codes", "harsh_brakes_7d": "harsh braking", "is_ev": "EV", "is_hybrid": "hybrid"}

UPSERT = """
INSERT INTO risk_score (vin, tenant_id, score, baseline_score, top_factors, scored_at)
SELECT vin, tenant_id, score, baseline, factors::jsonb, now()
FROM unnest(%s::char(17)[], %s::smallint[], %s::real[], %s::real[], %s::text[]) AS t(vin, tenant_id, score, baseline, factors)
ON CONFLICT (vin) DO UPDATE SET score = EXCLUDED.score, baseline_score = EXCLUDED.baseline_score,
  top_factors = EXCLUDED.top_factors, scored_at = EXCLUDED.scored_at
"""


def explain(x, medians, importance, k=3):
    # contribution proxy: importance x signed deviation, direction-aware for "lower is worse" features
    out = []
    for j, f in enumerate(FEATURES):
        dev = x[j] - medians[j]
        if f == "min_batt_v_7d":
            dev = -dev
        if dev > 0 and f not in ("is_ev", "is_hybrid"):
            out.append((importance.get(f, 0) * dev / (abs(medians[j]) + 1e-6), f, round(float(x[j]), 2)))
    return [{"feature": f, "label": LABELS[f], "value": v} for _, f, v in sorted(out, reverse=True)[:k]]


# Incremental rollup: aggregate only (watermark, now - LATE_S] and merge into the day's row. The watermark moves
# in the same transaction, so each telemetry row is counted exactly once even if the job crashes mid-run.
ROLLUP = """
WITH w AS (
  SELECT coalesce((SELECT upto FROM rollup_watermark WHERE name = 'vehicle_daily'), now() - interval '1 day') AS lo,
         now() - make_interval(secs => %(late)s) AS hi
), ins AS (
  INSERT INTO vehicle_daily AS d (vin, day, events, min_odo, max_odo, sum_speed, max_coolant, min_batt_v,
                                  harsh_brakes, idle_samples, dtc_events)
  SELECT vin, (ts AT TIME ZONE 'UTC')::date, count(*), min(odo_km), max(odo_km), sum(speed_kmh), max(coolant_c), min(batt_v),
         count(*) FILTER (WHERE evt = 'HARSH_BRAKE'), count(*) FILTER (WHERE speed_kmh < 1),
         count(*) FILTER (WHERE dtcs IS NOT NULL)
  FROM telemetry, w WHERE ts > w.lo AND ts <= w.hi GROUP BY 1, 2
  ON CONFLICT (vin, day) DO UPDATE SET
    events = d.events + EXCLUDED.events, min_odo = LEAST(d.min_odo, EXCLUDED.min_odo),
    max_odo = GREATEST(d.max_odo, EXCLUDED.max_odo), sum_speed = d.sum_speed + EXCLUDED.sum_speed,
    max_coolant = GREATEST(d.max_coolant, EXCLUDED.max_coolant), min_batt_v = LEAST(d.min_batt_v, EXCLUDED.min_batt_v),
    harsh_brakes = d.harsh_brakes + EXCLUDED.harsh_brakes, idle_samples = d.idle_samples + EXCLUDED.idle_samples,
    dtc_events = d.dtc_events + EXCLUDED.dtc_events
  RETURNING 1
)
INSERT INTO rollup_watermark (name, upto) SELECT 'vehicle_daily', hi FROM w
ON CONFLICT (name) DO UPDATE SET upto = EXCLUDED.upto
RETURNING (SELECT count(*) FROM ins)
"""


def apply_lifecycle(conn):
    with conn.cursor() as c:
        c.execute(LIFECYCLE_SQL.read_text())
    conn.commit()


def run_once(conn, bundle):
    t0 = time.time()
    with conn.cursor() as c:
        c.execute("SELECT ensure_telemetry_partitions(2, 24)")
        c.execute(ROLLUP, {"late": LATE_S})
        conn.commit()
        c.execute("SELECT drop_old_telemetry(%s)", (RETENTION_HOURS,))
        dropped = c.fetchone()[0]
        conn.commit()
        if dropped:
            print(f"retention: dropped {dropped} telemetry partition(s) older than {RETENTION_HOURS} h", flush=True)
        c.execute(FEATURE_SQL)
        rows = c.fetchall()
    if not rows:
        return 0, time.time() - t0
    X = np.array([row_to_features(*r[2:]) for r in rows])
    scores = bundle["model"].predict_proba(X)[:, 1]
    base = np.clip(X[:, 0] / 1.5, 0, 1)
    factors = [json.dumps(explain(x, bundle["medians"], bundle["importance"])) for x in X]
    with conn.cursor() as c:
        c.execute(UPSERT, ([r[0] for r in rows], [r[1] for r in rows], scores.tolist(), base.tolist(), factors))
    conn.commit()
    return len(rows), time.time() - t0


def main():
    bundle = joblib.load(MODEL_PATH)
    interval = int(os.environ.get("BATCH_INTERVAL_S", "60"))
    while True:
        try:
            with psycopg.connect(config.PG_DSN) as conn:
                apply_lifecycle(conn)
                while True:
                    n, dt = run_once(conn, bundle)
                    print(f"scored {n} vehicles in {dt:.1f}s", flush=True)
                    time.sleep(interval)
        except psycopg.Error as ex:
            print("batch error, retrying:", ex, flush=True)
            time.sleep(5)


if __name__ == "__main__":
    main()
