"""Feature definitions shared by training (simulated history) and batch scoring (live SQL)."""
import numpy as np

FEATURES = ["service_overdue_ratio", "vehicle_age_yrs", "odo_10k_km", "max_coolant_7d", "min_batt_v_7d",
            "dtc_events_7d", "harsh_brakes_7d", "is_ev", "is_hybrid"]

FEATURE_SQL = """
WITH d AS (
  SELECT vin, max(max_odo)::float8 AS odo, max(max_coolant)::float8 AS max_coolant, min(min_batt_v)::float8 AS min_batt_v,
         sum(dtc_events)::int AS dtc_events, sum(harsh_brakes)::int AS harsh_brakes
  FROM vehicle_daily WHERE day >= current_date - 7 GROUP BY vin
)
SELECT v.vin, f.tenant_id, m.service_interval_km, v.last_service_odo_km::float8, v.model_year, m.powertrain,
       d.odo, d.max_coolant, d.min_batt_v, d.dtc_events, d.harsh_brakes
FROM vehicle v JOIN fleet f USING (fleet_id) JOIN vehicle_model m USING (model_id) JOIN d USING (vin)
"""


def row_to_features(interval_km, last_service_odo, year, pt, odo, max_cool, min_bv, dtc, brakes, now_year=2026):
    return [
        (odo - last_service_odo) / interval_km,
        now_year - year,
        odo / 10000,
        max_cool if max_cool is not None else 0.0,  # EVs have no coolant -> 0
        min_bv if min_bv is not None else 12.6,
        dtc, brakes, 1.0 if pt == "EV" else 0.0, 1.0 if pt == "HEV" else 0.0,
    ]


def simulate_history(n: int, seed: int = 21):
    """Generate labelled vehicle-weeks from the same hidden-wear model the simulator uses.

    Label = breakdown within the next 7 days. Breakdown hazard depends on wear, which is
    only observable through noisy symptoms (coolant, 12V, DTC counts) -> a learning problem.
    """
    from ..simulator.fleetgen import MODELS, make_fleets, make_vehicles
    rng = np.random.default_rng(seed)
    model = {m[0]: m for m in MODELS}
    X, y, base = [], [], []
    for vin, _fleet, mid, year, last_svc, odo, wear in make_vehicles(n, make_fleets(), seed=seed):
        _, _, _, pt, interval = model[mid]
        w = float(np.clip(wear + rng.normal(0, 0.05), 0, 1))
        cool = None if pt == "EV" else 86 + 28 * w ** 2 + abs(rng.normal(0, 3)) + 4
        bv = 12.7 - 1.3 * w ** 1.5 - abs(rng.normal(0, 0.15))
        dtc = rng.poisson(7 * 4320 * (0.0004 + 0.02 * w ** 4) / 50)
        brakes = rng.poisson(6)
        X.append(row_to_features(interval, last_svc, year, pt, odo, cool, bv, dtc, brakes))
        hazard = 1 / (1 + np.exp(-(12 * (w - 0.72))))
        y.append(int(rng.random() < 0.35 * hazard))
        base.append((odo - last_svc) / interval)
    return np.array(X), np.array(y), np.array(base)
