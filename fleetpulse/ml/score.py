"""Batch job: refresh warm-tier rollups, score every vehicle, upsert risk_score. Runs on an interval."""
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


def run_once(conn, bundle):
    t0 = time.time()
    with conn.cursor() as c:
        c.execute("SELECT ensure_telemetry_partitions(1, 3)")
        c.execute("SELECT ispopulated FROM pg_matviews WHERE matviewname = 'vehicle_daily'")
        c.execute("REFRESH MATERIALIZED VIEW " + ("CONCURRENTLY " if c.fetchone()[0] else "") + "vehicle_daily")
        conn.commit()
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
                while True:
                    n, dt = run_once(conn, bundle)
                    print(f"scored {n} vehicles in {dt:.1f}s", flush=True)
                    time.sleep(interval)
        except psycopg.Error as ex:
            print("batch error, retrying:", ex, flush=True)
            time.sleep(5)


if __name__ == "__main__":
    main()
