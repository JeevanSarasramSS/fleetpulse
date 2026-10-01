import numpy as np

from fleetpulse.ml.features import FEATURES, row_to_features, simulate_history
from fleetpulse.ml.score import explain
from fleetpulse.ml.train import precision_at_k


def test_feature_vector_shape():
    assert len(row_to_features(15000, 1000, 2020, "EV", 16000, None, None, 2, 1)) == len(FEATURES)


def test_simulated_history_is_learnable():
    X, y, base = simulate_history(3000)
    assert X.shape == (3000, len(FEATURES)) and 0 < y.mean() < 0.2


def test_precision_at_k():
    y = np.array([1, 0, 0, 0, 1, 0, 0, 0, 0, 0])
    s = np.array([.9, .1, .2, .3, .8, .1, .1, .1, .1, .1])
    assert precision_at_k(y, s, 0.2) == 1.0


def test_explain_orders_factors():
    med = [0.5, 4, 8, 95, 12.4, 1, 5, 0, 0]
    imp = {f: 1.0 for f in FEATURES}
    x = [1.5, 4, 8, 120, 11.2, 1, 5, 0, 0]
    labels = [f["feature"] for f in explain(x, med, imp)]
    assert "service_overdue_ratio" in labels and "min_batt_v_7d" in labels and "max_coolant_7d" in labels
