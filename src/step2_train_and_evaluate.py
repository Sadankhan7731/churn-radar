"""
STEP 2 + 3 - Train two churn models and test them against the Phase 1 targets.

The idea in plain words:
  * We hide 30% of subscribers (the "test set"), like a month the model has never seen.
  * We train on the other 70%.
  * We score the hidden 30% and compare predictions with what really happened.

Two models, on purpose:
  1. Logistic regression - simple, explainable, our BASELINE.
  2. Gradient boosting  - more powerful, finds non-linear patterns.
  If the fancy model is not clearly better, we keep the simple one.

Phase 1 targets (rows 7 and 7a), fixed BEFORE building:
  * AUC >= 0.75
  * Precision in the top 10% of scores >= 40%
  * Calibration: in the high-risk band, predicted churn ~ actual churn

Run:  .venv/bin/python src/step2_train_and_evaluate.py
"""
import json
import joblib
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score, brier_score_loss
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

df = pd.read_csv("data/subscribers.csv.gz")

# --- Feature engineering: turn raw columns into clearer signals --------------
df["watch_change_pct"] = ((df.watch_min_last_7d - df.watch_min_prev_7d)
                          / (df.watch_min_prev_7d + 30) * 100).round(1)
df["offer_open_rate"] = (df.offers_opened_90d / df.offers_received_90d.clip(lower=1)).round(2)
df["ticket_negative"] = (df.ticket_sentiment == "negative").astype(int)

NUMERIC = [
    # viewing
    "tenure_days", "watch_min_last_7d", "watch_change_pct", "watch_trend_8w_pct", "sessions_7d",
    "days_since_active", "completion_rate", "distinct_titles_30d", "category_concentration",
    "live_share", "binge_sessions_30d",
    # content
    "fav_content_ended", "days_to_next_release", "catalogue_match_titles", "recs_ignored_30d",
    # payment
    "failed_renewals_30d", "low_balance_renewals_30d", "recharges_30d", "payment_switches_90d",
    # experience
    "buffering_errors_7d", "app_crashes_7d", "video_start_sec", "login_failures_30d",
    # plan history, marketing, support
    "plan_downgrades_90d", "past_cancellations", "offers_received_90d", "offer_open_rate",
    "used_discount", "support_tickets_30d", "ticket_negative", "ticket_resolved",
    "monthly_revenue_pkr",
]
CATEGORICAL = ["payment_channel", "plan", "city", "device", "network", "signup_source", "favourite_genre"]
TARGET = "churned_next_30d"

X, y = df[NUMERIC + CATEGORICAL], df[TARGET]
X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.30, stratify=y, random_state=42)

prep = ColumnTransformer([
    ("num", StandardScaler(), NUMERIC),
    ("cat", OneHotEncoder(handle_unknown="ignore"), CATEGORICAL),
])

models = {
    "Logistic regression (baseline)": Pipeline([
        ("prep", prep), ("model", LogisticRegression(max_iter=2000))]),
    "Gradient boosting": Pipeline([
        ("prep", prep), ("model", HistGradientBoostingClassifier(
            max_iter=400, learning_rate=0.05, max_leaf_nodes=20, random_state=42))]),
}


def evaluate(y_true, p):
    """All the Phase 1 metrics for one set of predicted probabilities."""
    y_true = np.asarray(y_true)
    order = np.argsort(-p)
    top10 = order[: int(len(p) * 0.10)]
    base = y_true.mean()
    prec10 = y_true[top10].mean()
    # Calibration: split into 10 bands by score, compare predicted vs actual
    bands = pd.qcut(p, 10, labels=False, duplicates="drop")
    calib = (pd.DataFrame({"band": bands, "pred": p, "actual": y_true})
             .groupby("band").agg(predicted=("pred", "mean"), actual=("actual", "mean"),
                                  n=("pred", "size")).reset_index())
    top_band = calib.iloc[-1]
    return {
        "auc": round(roc_auc_score(y_true, p), 3),
        "precision_top10": round(prec10, 3),
        "recall_top10": round(y_true[top10].sum() / y_true.sum(), 3),
        "lift_top10": round(prec10 / base, 2),
        "brier": round(brier_score_loss(y_true, p), 4),
        "base_rate": round(base, 3),
        "top_band_predicted": round(top_band.predicted, 3),
        "top_band_actual": round(top_band.actual, 3),
        "calibration": calib.round(4).to_dict(orient="records"),
    }


results = {}
for name, pipe in models.items():
    pipe.fit(X_train, y_train)
    results[name] = evaluate(y_test, pipe.predict_proba(X_test)[:, 1])

# --- Print a comparison the way a business reader would want it --------------
print(f"Test set: {len(y_test):,} subscribers never seen in training, "
      f"real churn rate {y_test.mean():.1%}\n")
rows = [("AUC (target >= 0.75)", "auc"), ("Precision in top 10% (target >= 40%)", "precision_top10"),
        ("Recall in top 10%", "recall_top10"), ("Lift in top 10% (x better than random)", "lift_top10"),
        ("Brier score (lower = better)", "brier"),
        ("Top band: predicted churn", "top_band_predicted"), ("Top band: actual churn", "top_band_actual")]
names = list(results)
print(f"{'Metric':42s}" + "".join(f"{n[:30]:>32s}" for n in names))
for label, key in rows:
    print(f"{label:42s}" + "".join(f"{results[n][key]:>32}" for n in names))

# --- Choose the model: the simpler one wins unless the complex one is clearly better
lr, gb = results[names[0]], results[names[1]]
chosen = names[1] if gb["auc"] - lr["auc"] >= 0.01 else names[0]
print(f"\nChosen model: {chosen}  "
      f"(rule: use gradient boosting only if AUC improves by >= 0.01)")

final = models[chosen]
r = results[chosen]
checks = {
    "AUC >= 0.75": r["auc"] >= 0.75,
    "Precision top 10% >= 40%": r["precision_top10"] >= 0.40,
    "Top band calibrated (within 5 pts)": abs(r["top_band_predicted"] - r["top_band_actual"]) <= 0.05,
}
# --- The ceiling: how good could a PERFECT model be on this data? ----------
# Score the same test set with the true probabilities from Step 1.
truth = pd.read_csv("data/true_probability.csv.gz").set_index("subscriber_id").true_probability
ceiling = evaluate(y_test, truth.loc[df.loc[X_test.index, "subscriber_id"]].values)
ceiling = {k: ceiling[k] for k in ["auc", "precision_top10", "recall_top10", "lift_top10", "brier"]}
print(f"\nPerfect-model ceiling on the same test set: AUC {ceiling['auc']}, "
      f"top-10% precision {ceiling['precision_top10']:.1%}")
print(f"Our model reaches {r['auc'] / ceiling['auc']:.0%} of the best possible AUC.")

print("\nPhase 1 targets:")
for k, ok in checks.items():
    print(f"  {'PASS' if ok else 'MISS'}  {k}")

# --- Calibration chart (catches 'confidently wrong') -------------------------
fig, ax = plt.subplots(figsize=(6, 5))
for n in names:
    c = pd.DataFrame(results[n]["calibration"])
    ax.plot(c.predicted, c.actual, marker="o", label=n)
lim = max(pd.DataFrame(results[n]["calibration"]).actual.max() for n in names) * 1.1
ax.plot([0, lim], [0, lim], "--", color="grey", label="Perfect calibration")
ax.set_xlabel("Predicted churn (average in band)")
ax.set_ylabel("Actual churn (in band)")
ax.set_title("Calibration on the held-out test set")
ax.legend()
fig.tight_layout()
fig.savefig("outputs/calibration.png", dpi=150)

# --- Save everything the next steps and the dashboard need -------------------
joblib.dump(final, "outputs/churn_model.joblib")
df["churn_score"] = final.predict_proba(df[NUMERIC + CATEGORICAL])[:, 1].round(4)
df.to_csv("outputs/scored_subscribers.csv.gz", index=False)
json.dump({"chosen_model": chosen, "results": results,
           "targets": {k: bool(v) for k, v in checks.items()}, "ceiling": ceiling,
           "features": {"numeric": NUMERIC, "categorical": CATEGORICAL}},
          open("outputs/model_metrics.json", "w"), indent=2)
print("\nSaved: outputs/churn_model.joblib, outputs/scored_subscribers.csv.gz, "
      "outputs/model_metrics.json, outputs/calibration.png")
