"""
STEP 6 - Export the model so the website can score uploaded data in the browser.

Why: Phase 1 says real customer data must not leave the company. If people could
upload files to our server, we would be breaking our own rule. Instead the website
downloads the model's formula and scores the file on the user's own device.
Logistic regression makes this possible: the whole model is one formula,
    probability = 1 / (1 + e^-(intercept + sum of weight x standardised value)).

Writes:
  public/model/churn_model.json        the formula (weights, averages, spreads, categories)
  public/samples/lumen_play_sample.csv 2,000 sample customers to try the upload flow
  public/samples/template.csv          empty template with every supported column
  public/samples/sqlserver_query.sql   a query to export the same columns from SQL Server
And checks that the browser formula gives the same scores as Python.

Run:  .venv/bin/python src/step6_export_for_browser.py
"""
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

metrics = json.load(open("outputs/model_metrics.json"))
pipe = joblib.load("outputs/churn_model.joblib")
prep, lr = pipe["prep"], pipe["model"]
NUMERIC, CATEGORICAL = metrics["features"]["numeric"], metrics["features"]["categorical"]

scaler = prep.named_transformers_["num"]
onehot = prep.named_transformers_["cat"]
coef = lr.coef_[0]
n_num = len(NUMERIC)

model = {
    "name": "Churn Radar v2 (logistic regression)",
    "intercept": float(lr.intercept_[0]),
    "numeric": [{"name": f, "mean": float(m), "scale": float(s), "weight": float(w)}
                for f, m, s, w in zip(NUMERIC, scaler.mean_, scaler.scale_, coef[:n_num])],
    "categorical": [],
    # Columns the browser derives from raw columns (same formulas as Step 2)
    "derived": {
        "watch_change_pct": "(watch_min_last_7d - watch_min_prev_7d) / (watch_min_prev_7d + 30) * 100",
        "offer_open_rate": "offers_opened_90d / max(offers_received_90d, 1)",
        "ticket_negative": "ticket_sentiment == 'negative'",
    },
}
i = n_num
for f, cats in zip(CATEGORICAL, onehot.categories_):
    weights = coef[i:i + len(cats)]
    model["categorical"].append({"name": f, "weights": {str(c): float(w) for c, w in zip(cats, weights)}})
    i += len(cats)

Path("public/model").mkdir(parents=True, exist_ok=True)
json.dump(model, open("public/model/churn_model.json", "w"), indent=1)

# ---- sample + template files -----------------------------------------------------------
df = pd.read_csv("data/subscribers.csv.gz")
RAW = ["subscriber_id", "payment_channel", "plan", "monthly_revenue_pkr", "city", "device", "network", "signup_source",
       "favourite_genre", "tenure_days", "failed_renewals_30d", "low_balance_renewals_30d", "recharges_30d",
       "payment_switches_90d", "watch_min_prev_7d", "watch_min_last_7d", "watch_trend_8w_pct", "sessions_7d",
       "days_since_active", "completion_rate", "distinct_titles_30d", "category_concentration", "live_share",
       "binge_sessions_30d", "fav_content_ended", "days_to_next_release", "catalogue_match_titles", "recs_ignored_30d",
       "buffering_errors_7d", "app_crashes_7d", "video_start_sec", "login_failures_30d", "plan_downgrades_90d",
       "past_cancellations", "offers_received_90d", "offers_opened_90d", "used_discount", "support_tickets_30d",
       "ticket_sentiment", "ticket_resolved"]
Path("public/samples").mkdir(parents=True, exist_ok=True)
sample = df.sample(2000, random_state=7)[RAW]                     # no churn label: that's what we predict
sample.to_csv("public/samples/lumen_play_sample.csv", index=False)
pd.DataFrame(columns=RAW).to_csv("public/samples/template.csv", index=False)
# The what-if simulator re-scores customers under scenarios. A 20% random sample (20,000 customers)
# is enough to be stable; results are scaled up by 5 to the full base.
df.sample(20000, random_state=11)[RAW].to_csv("public/samples/simulator_base.csv", index=False)

sql = """-- Churn Radar: export one row per active paying customer, then save the result as CSV
-- and upload it on the Data sources page. Rename the tables/columns to match your schema.
-- Only include the columns you have; missing ones are filled with typical values.
SELECT
    c.customer_id                              AS subscriber_id,
    c.payment_channel,                         -- e.g. 'Operator 1', 'Wallet', 'Card'
    c.plan_name                                AS plan,
    c.monthly_price_pkr                        AS monthly_revenue_pkr,
    c.city, c.device_type AS device, c.network_type AS network, c.acquisition_source AS signup_source,
    v.favourite_genre,
    DATEDIFF(day, c.signup_date, GETDATE())    AS tenure_days,
    b.failed_renewals_30d, b.low_balance_renewals_30d, b.recharges_30d, b.payment_switches_90d,
    v.watch_min_prev_7d, v.watch_min_last_7d, v.watch_trend_8w_pct, v.sessions_7d,
    DATEDIFF(day, v.last_active_date, GETDATE()) AS days_since_active,
    v.completion_rate, v.distinct_titles_30d, v.category_concentration, v.live_share, v.binge_sessions_30d,
    v.fav_content_ended, v.days_to_next_release, v.catalogue_match_titles, v.recs_ignored_30d,
    q.buffering_errors_7d, q.app_crashes_7d, q.video_start_sec, q.login_failures_30d,
    h.plan_downgrades_90d, h.past_cancellations,
    m.offers_received_90d, m.offers_opened_90d, m.used_discount,
    s.support_tickets_30d, s.last_ticket_sentiment   AS ticket_sentiment, s.last_ticket_resolved AS ticket_resolved
FROM customers c
LEFT JOIN viewing_weekly   v ON v.customer_id = c.customer_id
LEFT JOIN billing_monthly  b ON b.customer_id = c.customer_id
LEFT JOIN app_quality      q ON q.customer_id = c.customer_id
LEFT JOIN plan_history     h ON h.customer_id = c.customer_id
LEFT JOIN marketing        m ON m.customer_id = c.customer_id
LEFT JOIN support_summary  s ON s.customer_id = c.customer_id
WHERE c.status = 'active';
"""
open("public/samples/sqlserver_query.sql", "w").write(sql)

# ---- check: the browser formula must reproduce Python's scores ------------------------
s = sample.copy()
s["watch_change_pct"] = ((s.watch_min_last_7d - s.watch_min_prev_7d) / (s.watch_min_prev_7d + 30) * 100).round(1)
s["offer_open_rate"] = (s.offers_opened_90d / s.offers_received_90d.clip(lower=1)).round(2)
s["ticket_negative"] = (s.ticket_sentiment == "negative").astype(int)
z = np.full(len(s), model["intercept"])
for f in model["numeric"]:
    z += f["weight"] * (s[f["name"]].values - f["mean"]) / f["scale"]
for c in model["categorical"]:
    z += s[c["name"]].astype(str).map(c["weights"]).fillna(0).values
manual = 1 / (1 + np.exp(-z))
python = pipe.predict_proba(s[NUMERIC + CATEGORICAL])[:, 1]
diff = np.abs(manual - python).max()
print(f"Model formula exported: {len(model['numeric'])} numeric + {len(model['categorical'])} categorical signals")
print(f"Largest difference between the browser formula and Python on 2,000 customers: {diff:.2e}")
assert diff < 1e-6, "formula does not match the model"
json.dump({"ids": s.subscriber_id.head(5).tolist(), "scores": [round(float(x), 6) for x in python[:5]]},
          open("public/model/check.json", "w"))
print("Saved public/model/churn_model.json, public/samples/{lumen_play_sample.csv, template.csv, sqlserver_query.sql}")
