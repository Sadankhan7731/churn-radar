"""
STEP 4 - Turn scores into something the retention team can act on.

A score like 0.31 means nothing to a business user. This step adds:
  1. Reason codes  - the top 3 reasons behind each subscriber's score,
                     written in plain English with the real number behind it.
  2. Segments      - churn risk and revenue at risk by operator, plan, city, genre.
  3. Deciles       - the 10 risk bands the what-if simulator in the dashboard uses.
  4. A "did the model learn the true rules?" check against Step 1.

How reason codes work (logistic regression makes this easy):
  every feature adds  coefficient x (how far this person is from average)
  to the score. The features adding the most push the score up the most,
  so those are this person's reasons.

Run:  .venv/bin/python src/step4_explain_and_segment.py
"""
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

df = pd.read_csv("outputs/scored_subscribers.csv")
metrics = json.load(open("outputs/model_metrics.json"))
model = joblib.load("outputs/churn_model.joblib")
prep, lr = model["prep"], model["model"]
NUMERIC = metrics["features"]["numeric"]

# ---------------------------------------------------------------------------
# 1. Reason codes
# ---------------------------------------------------------------------------
# Only behaviour the business can understand or act on becomes a reason.
# (City or device effects are left out: the model picks some up, but Step 1
#  never made city matter, so those are noise - see the check in section 4.)
REASONS = {
    "watch_change_pct":    lambda r: f"Watch time {'down' if r.watch_change_pct < 0 else 'up'} {abs(r.watch_change_pct):.0f}% vs last week",
    "days_since_active":   lambda r: f"Inactive for {r.days_since_active} days",
    "failed_renewals_30d": lambda r: f"{r.failed_renewals_30d} failed renewal(s) in 30 days",
    "support_tickets_30d": lambda r: f"{r.support_tickets_30d} support ticket(s) in 30 days",
    "buffering_errors_7d": lambda r: f"{r.buffering_errors_7d} buffering errors this week",
    "tenure_days":         lambda r: f"New subscriber ({r.tenure_days} days)",
    "sports_season_over":  lambda r: "Sports fan and the series just ended",
    "used_discount":       lambda r: "Joined or stayed on a discount before",
    "sessions_7d":         lambda r: f"Only {r.sessions_7d} sessions this week",
    "plan_Daily":          lambda r: "On a Daily pack (easiest to drop)",
}
# A reason only counts if the person is actually on the risky side of it.
# This rule is also what the hallucination check uses later: a reason must be TRUE in the data.
IS_TRUE = {
    "watch_change_pct":    lambda r: r.watch_change_pct <= -20,
    "days_since_active":   lambda r: r.days_since_active >= 5,
    "failed_renewals_30d": lambda r: r.failed_renewals_30d >= 1,
    "support_tickets_30d": lambda r: r.support_tickets_30d >= 1,
    "buffering_errors_7d": lambda r: r.buffering_errors_7d >= 4,
    "tenure_days":         lambda r: r.tenure_days <= 60,
    "sports_season_over":  lambda r: r.sports_season_over == 1,
    "used_discount":       lambda r: r.used_discount == 1,
    "sessions_7d":         lambda r: r.sessions_7d <= 1,
    "plan_Daily":          lambda r: r.plan == "Daily",
}

names = list(prep.get_feature_names_out())
coef = dict(zip(names, lr.coef_[0]))
scaled = pd.DataFrame(prep.transform(df[NUMERIC + metrics["features"]["categorical"]]), columns=names)

contrib = pd.DataFrame(index=df.index)
for f in NUMERIC:
    if f in REASONS:
        contrib[f] = coef[f"num__{f}"] * scaled[f"num__{f}"]
# Plan: how much more risky Daily is than the average plan
plan_cols = [c for c in names if c.startswith("cat__plan_")]
avg_plan = sum(coef[c] * scaled[c].mean() for c in plan_cols)
contrib["plan_Daily"] = (coef["cat__plan_Daily"] - avg_plan) * scaled["cat__plan_Daily"]


def top_reasons(i, k=3):
    row = df.loc[i]
    ranked = contrib.loc[i].sort_values(ascending=False)
    out = [{"code": f, "text": REASONS[f](row), "weight": round(float(w), 3)}
           for f, w in ranked.items() if w > 0 and IS_TRUE[f](row)]
    return out[:k]


df["risk_rank"] = df.churn_score.rank(ascending=False, method="first").astype(int)
df["risk_band"] = pd.cut(df.risk_rank, [0, len(df) * 0.10, len(df) * 0.30, len(df)],
                         labels=["High", "Medium", "Low"])
top_n = df.nsmallest(500, "risk_rank")
watchlist = []
for i, r in top_n.iterrows():
    watchlist.append({
        "id": r.subscriber_id, "score": round(r.churn_score, 3), "rank": int(r.risk_rank),
        "plan": r.plan, "channel": r.payment_channel, "city": r.city,
        "genre": r.favourite_genre, "revenue": int(r.monthly_revenue_pkr),
        "tenure": int(r.tenure_days),
        "reasons": top_reasons(i),
        "facts": {f: (r[f] if f != "plan_Daily" else r.plan) for f in
                  ["watch_change_pct", "days_since_active", "failed_renewals_30d",
                   "support_tickets_30d", "buffering_errors_7d", "tenure_days",
                   "sessions_7d", "sports_season_over", "used_discount"]},
    })
for w in watchlist:                       # numpy -> plain Python for JSON
    w["facts"] = {k: (float(v) if isinstance(v, (np.floating, float)) else int(v)) for k, v in w["facts"].items()}

# How often each reason appears among the high-risk group (the top 10%)
high = df[df.risk_band == "High"]
reason_counts = {}
for i in high.index:
    for r in top_reasons(i):
        reason_counts[r["code"]] = reason_counts.get(r["code"], 0) + 1
REASON_LABEL = {
    "watch_change_pct": "Watching much less than last week", "days_since_active": "Inactive 5+ days",
    "failed_renewals_30d": "Failed renewals", "support_tickets_30d": "Raised a support ticket",
    "buffering_errors_7d": "Heavy buffering", "tenure_days": "New (under 60 days)",
    "sports_season_over": "Sports series ended", "used_discount": "Discount history",
    "sessions_7d": "Barely opening the app", "plan_Daily": "On a Daily pack",
}
reason_summary = sorted(
    [{"code": c, "label": REASON_LABEL[c], "count": n, "share": round(n / len(high), 3)}
     for c, n in reason_counts.items()], key=lambda d: -d["count"])

# ---------------------------------------------------------------------------
# 2. Segments and revenue at risk
# ---------------------------------------------------------------------------
# Expected churners = sum of probabilities. Revenue at risk = sum(prob x monthly revenue).
df["revenue_at_risk"] = df.churn_score * df.monthly_revenue_pkr


def segment(col):
    g = df.groupby(col).agg(subscribers=("subscriber_id", "size"),
                            avg_risk=("churn_score", "mean"),
                            expected_churners=("churn_score", "sum"),
                            revenue_at_risk_pkr=("revenue_at_risk", "sum"),
                            high_risk=("risk_band", lambda s: (s == "High").sum()))
    g = g.reset_index().rename(columns={col: "segment"}).sort_values("avg_risk", ascending=False)
    return g.round({"avg_risk": 3, "expected_churners": 0, "revenue_at_risk_pkr": 0}).to_dict(orient="records")


segments = {c: segment(c) for c in ["payment_channel", "plan", "city", "favourite_genre", "device"]}

# ---------------------------------------------------------------------------
# 3. Deciles for the what-if simulator
# ---------------------------------------------------------------------------
df["decile"] = pd.qcut(df.risk_rank, 10, labels=list(range(1, 11))).astype(int)
deciles = (df.groupby("decile").agg(subscribers=("subscriber_id", "size"),
                                    avg_score=("churn_score", "mean"),
                                    expected_churners=("churn_score", "sum"),
                                    avg_revenue=("monthly_revenue_pkr", "mean"))
           .reset_index().round(3).to_dict(orient="records"))

# ---------------------------------------------------------------------------
# 4. Did the model rediscover the true rules from Step 1?
# ---------------------------------------------------------------------------
TRUE_DIRECTION = {"watch_change_pct": "-", "days_since_active": "+", "failed_renewals_30d": "+",
                  "support_tickets_30d": "+", "buffering_errors_7d": "+", "tenure_days": "-",
                  "sports_season_over": "+", "used_discount": "+"}
rule_check = []
for f, d in TRUE_DIRECTION.items():
    c = coef[f"num__{f}"]
    rule_check.append({"feature": f, "true_effect": "raises churn" if d == "+" else "lowers churn",
                       "model_coefficient": round(float(c), 3),
                       "matches": (c > 0) == (d == "+")})

kpis = {
    "subscribers": int(len(df)),
    "expected_churners": int(df.churn_score.sum()),
    "expected_churn_rate": round(float(df.churn_score.mean()), 3),
    "high_risk_subscribers": int((df.risk_band == "High").sum()),
    "revenue_at_risk_pkr": int(df.revenue_at_risk.sum()),
    "high_risk_revenue_at_risk_pkr": int(df.loc[df.risk_band == "High", "revenue_at_risk"].sum()),
    "avg_revenue_pkr": round(float(df.monthly_revenue_pkr.mean()), 0),
}

population_avg = {f: round(float(df[f].mean()), 2) for f in
                  ["watch_change_pct", "days_since_active", "failed_renewals_30d", "support_tickets_30d",
                   "buffering_errors_7d", "tenure_days", "sessions_7d", "sports_season_over", "used_discount"]}
out = {"kpis": kpis, "population_avg": population_avg, "reason_summary": reason_summary, "segments": segments,
       "deciles": deciles, "watchlist": watchlist, "rule_check": rule_check,
       "model": {"name": metrics["chosen_model"], **{k: v for k, v in metrics["results"][metrics["chosen_model"]].items()},
                 "comparison": {n: {k: r[k] for k in ["auc", "precision_top10", "recall_top10", "lift_top10", "brier"]}
                                for n, r in metrics["results"].items()},
                 "targets": metrics["targets"], "ceiling": metrics["ceiling"]}}
Path("public/data").mkdir(parents=True, exist_ok=True)
json.dump(out, open("public/data/dashboard.json", "w"), indent=1, default=float)

# --- Print what we found ------------------------------------------------------
print("KPIs:")
for k, v in kpis.items():
    print(f"  {k:32s} {v:,}")
print("\nTop reasons among the high-risk 10% (2,000 subscribers):")
for r in reason_summary:
    print(f"  {r['label']:36s} {r['share']:.0%}")
print("\nHighest-risk segments:")
for col in ["payment_channel", "plan", "favourite_genre"]:
    s = segments[col][0]
    print(f"  {col:16s} {s['segment']:15s} avg risk {s['avg_risk']:.1%}, PKR {s['revenue_at_risk_pkr']:,.0f} at risk")
print("\nDid the model learn the true rules from Step 1?")
for r in rule_check:
    print(f"  {'YES' if r['matches'] else 'NO '}  {r['feature']:22s} truth: {r['true_effect']:13s} model coef {r['model_coefficient']:+.3f}")
print("\nExample - the riskiest subscriber:")
w = watchlist[0]
print(f"  {w['id']}  score {w['score']:.0%}  {w['plan']} via {w['channel']}, {w['city']}")
for r in w["reasons"]:
    print(f"   - {r['text']}")
print("\nSaved public/data/dashboard.json")
