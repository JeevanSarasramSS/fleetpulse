"""Train the 7-day breakdown risk model and evaluate it against a mileage-since-service baseline."""
import json
import pathlib
import time

import joblib
import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.model_selection import train_test_split

from .features import FEATURES, simulate_history

OUT = pathlib.Path(__file__).parent


def precision_at_k(y_true, scores, frac=0.02):
    k = max(1, int(len(scores) * frac))
    top = np.argsort(-scores)[:k]
    return float(y_true[top].mean())


def main(n: int = 100_000):
    t0 = time.time()
    X, y, base = simulate_history(n)
    Xtr, Xte, ytr, yte, _, bte = train_test_split(X, y, base, test_size=0.25, random_state=0, stratify=y)
    clf = HistGradientBoostingClassifier(max_iter=200, learning_rate=0.08, max_leaf_nodes=31, random_state=0)
    clf.fit(Xtr, ytr)
    p = clf.predict_proba(Xte)[:, 1]
    metrics = {
        "n_vehicles": n, "positive_rate": round(float(y.mean()), 4), "train_seconds": round(time.time() - t0, 1),
        "model": {"roc_auc": round(roc_auc_score(yte, p), 4), "pr_auc": round(average_precision_score(yte, p), 4),
                  "precision_at_2pct": round(precision_at_k(yte, p), 4)},
        "baseline_service_overdue": {"roc_auc": round(roc_auc_score(yte, bte), 4),
                                     "pr_auc": round(average_precision_score(yte, bte), 4),
                                     "precision_at_2pct": round(precision_at_k(yte, bte), 4)},
        "features": FEATURES,
    }
    # permutation-free global importance proxy: mean |score delta| when zeroing each feature's variation
    imp = {}
    for j, f in enumerate(FEATURES):
        Xp = Xte.copy()
        Xp[:, j] = np.median(Xte[:, j])
        imp[f] = round(float(np.abs(clf.predict_proba(Xp)[:, 1] - p).mean()), 5)
    metrics["feature_importance"] = dict(sorted(imp.items(), key=lambda kv: -kv[1]))
    joblib.dump({"model": clf, "features": FEATURES, "medians": np.median(Xtr, axis=0).tolist(),
                 "importance": metrics["feature_importance"]}, OUT / "model.joblib")
    (OUT / "metrics.json").write_text(json.dumps(metrics, indent=2))
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
