"""
STEP 4 - Turn scores into something the retention team can act on.

A score like 0.31 means nothing to a business user. This step adds:
  1. Reason codes  - the top 3 reasons behind each subscriber's score,
                     in plain English with the real number behind it.
  2. Personas      - simple, rule-based customer groups (e.g. "Seasonal live fans")
                     so campaigns can be planned per group.
  3. Content view  - the release calendar joined with risk: who is waiting for what.
  4. Segments      - churn risk and revenue at risk by plan, channel, genre, etc.
  5. Deciles       - the 10 risk bands the campaign simulator uses.
  6. A "did the model learn the true rules?" check against Step 1.

How reason codes work (logistic regression makes this easy):
  every signal adds  coefficient x (how far this person is from average)
  to the score. The signals adding the most push the score up the most,
  so those are this person's reasons.

Run:  .venv/bin/python src/step4_explain_and_segment.py
"""
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

df = pd.read_csv("outputs/scored_subscribers.csv.gz")
calendar = pd.read_csv("data/content_calendar.csv")
metrics = json.load(open("outputs/model_metrics.json"))
model = joblib.load("outputs/churn_model.joblib")
prep, lr = model["prep"], model["model"]
NUMERIC, CATEGORICAL = metrics["features"]["numeric"], metrics["features"]["categorical"]

# ---------------------------------------------------------------------------
# 1. Reason codes
# ---------------------------------------------------------------------------
# Each reason: plain-English text, and a rule saying when it is actually TRUE.
# A reason is only shown if it is true for that person. The hallucination check
# in Step 5 relies on the same idea: a claim must be true in the data.
R = {
    "watch_change_pct":       ("Watch time down {v:.0f}% vs last week",          lambda r: r.watch_change_pct <= -20, lambda r: abs(r.watch_change_pct)),
    "watch_trend_8w_pct":     ("Viewing falling {v:.0f}% a month for 8 weeks",   lambda r: r.watch_trend_8w_pct <= -15, lambda r: abs(r.watch_trend_8w_pct)),
    "days_since_active":      ("Inactive for {v:.0f} days",                      lambda r: r.days_since_active >= 5, lambda r: r.days_since_active),
    "completion_rate":        ("Finishes only {v:.0f}% of what they start",      lambda r: r.completion_rate <= 0.4, lambda r: r.completion_rate * 100),
    "category_concentration": ("Watches almost only one category ({v:.0f}%)",    lambda r: r.category_concentration > 0.85, lambda r: r.category_concentration * 100),
    "fav_content_ended":      ("The {g} title they followed has just ended",     lambda r: r.fav_content_ended == 1, lambda r: 1),
    "days_to_next_release":   ("Next {g} release is {v:.0f} days away",          lambda r: r.fav_content_ended == 1 and r.days_to_next_release >= 14, lambda r: r.days_to_next_release),
    "recs_ignored_30d":       ("Ignored {v:.0f} recommendations this month",     lambda r: r.recs_ignored_30d >= 7, lambda r: r.recs_ignored_30d),
    "failed_renewals_30d":    ("{v:.0f} failed renewal(s) in 30 days",           lambda r: r.failed_renewals_30d >= 1, lambda r: r.failed_renewals_30d),
    "low_balance_renewals_30d": ("Low balance at {v:.0f} renewal(s)",            lambda r: r.low_balance_renewals_30d >= 1, lambda r: r.low_balance_renewals_30d),
    "payment_switches_90d":   ("Switched payment method {v:.0f} time(s)",        lambda r: r.payment_switches_90d >= 1, lambda r: r.payment_switches_90d),
    "buffering_errors_7d":    ("{v:.0f} buffering errors this week",             lambda r: r.buffering_errors_7d >= 4, lambda r: r.buffering_errors_7d),
    "app_crashes_7d":         ("App crashed {v:.0f} time(s) this week",          lambda r: r.app_crashes_7d >= 2, lambda r: r.app_crashes_7d),
    "video_start_sec":        ("Videos take {v:.1f}s to start",                  lambda r: r.video_start_sec > 4, lambda r: r.video_start_sec),
    "plan_downgrades_90d":    ("Downgraded their plan recently",                 lambda r: r.plan_downgrades_90d >= 1, lambda r: 1),
    "past_cancellations":     ("Has cancelled {v:.0f} time(s) before",           lambda r: r.past_cancellations >= 1, lambda r: r.past_cancellations),
    "offer_open_rate":        ("Opens only {v:.0f}% of our offers",              lambda r: r.offers_received_90d >= 3 and r.offer_open_rate < 0.15, lambda r: r.offer_open_rate * 100),
    "used_discount":          ("Joined or stayed on a discount",                 lambda r: r.used_discount == 1, lambda r: 1),
    "support_tickets_30d":    ("{v:.0f} support ticket(s) in 30 days",           lambda r: r.support_tickets_30d >= 1, lambda r: r.support_tickets_30d),
    "ticket_negative":        ("Last support ticket was angry or negative",      lambda r: r.ticket_negative == 1, lambda r: 1),
    "tenure_days":            ("New subscriber ({v:.0f} days)",                  lambda r: r.tenure_days <= 60, lambda r: r.tenure_days),
    "sessions_7d":            ("Only {v:.0f} session(s) this week",              lambda r: r.sessions_7d <= 1, lambda r: r.sessions_7d),
    "plan_Daily":             ("On a Daily pack (easiest to drop)",              lambda r: r.plan == "Daily", lambda r: 1),
}
GROUP = {
    "watch_change_pct": "Viewing", "watch_trend_8w_pct": "Viewing", "days_since_active": "Viewing",
    "completion_rate": "Viewing", "category_concentration": "Viewing", "sessions_7d": "Viewing",
    "fav_content_ended": "Content", "days_to_next_release": "Content", "recs_ignored_30d": "Content",
    "failed_renewals_30d": "Payment", "low_balance_renewals_30d": "Payment", "payment_switches_90d": "Payment",
    "buffering_errors_7d": "Experience", "app_crashes_7d": "Experience", "video_start_sec": "Experience",
    "plan_downgrades_90d": "Plan history", "past_cancellations": "Plan history",
    "offer_open_rate": "Marketing", "used_discount": "Marketing",
    "support_tickets_30d": "Support", "ticket_negative": "Support",
    "tenure_days": "Profile", "plan_Daily": "Profile",
}
LABEL = {
    "watch_change_pct": "Watching much less than last week", "watch_trend_8w_pct": "Slow decline over 8 weeks",
    "days_since_active": "Inactive 5+ days", "completion_rate": "Not finishing what they start",
    "category_concentration": "Watches only one category", "fav_content_ended": "Followed title just ended",
    "days_to_next_release": "Long wait for next release", "recs_ignored_30d": "Ignoring recommendations",
    "failed_renewals_30d": "Failed renewals", "low_balance_renewals_30d": "Low balance at renewal",
    "payment_switches_90d": "Switching payment method", "buffering_errors_7d": "Heavy buffering",
    "app_crashes_7d": "App crashes", "video_start_sec": "Slow video start", "plan_downgrades_90d": "Recent downgrade",
    "past_cancellations": "Cancelled before", "offer_open_rate": "Ignoring our offers",
    "used_discount": "Discount history", "support_tickets_30d": "Raised a support ticket",
    "ticket_negative": "Negative support ticket", "tenure_days": "New (under 60 days)",
    "sessions_7d": "Barely opening the app", "plan_Daily": "On a Daily pack",
}

names = list(prep.get_feature_names_out())
coef = dict(zip(names, lr.coef_[0]))
scaled = pd.DataFrame(prep.transform(df[NUMERIC + CATEGORICAL]), columns=names)
contrib = pd.DataFrame(index=df.index)
for f in R:
    if f"num__{f}" in coef:
        contrib[f] = coef[f"num__{f}"] * scaled[f"num__{f}"]
plan_cols = [c for c in names if c.startswith("cat__plan_")]
avg_plan = sum(coef[c] * scaled[c].mean() for c in plan_cols)
contrib["plan_Daily"] = (coef["cat__plan_Daily"] - avg_plan) * scaled["cat__plan_Daily"]
# "Next release is far away" only matters for people whose title ended; give it the content weight.
contrib["days_to_next_release"] = contrib["days_to_next_release"].clip(lower=0) * df.fav_content_ended


def top_reasons(i, k=3):
    row = df.loc[i]
    ranked = contrib.loc[i].sort_values(ascending=False)
    out = []
    for f, w in ranked.items():
        text, is_true, value = R[f]
        if w > 0 and is_true(row):
            out.append({"code": f, "group": GROUP[f], "weight": round(float(w), 3),
                        "text": text.format(v=value(row), g=row.favourite_genre.lower())})
        if len(out) == k:
            break
    return out


df["risk_rank"] = df.churn_score.rank(ascending=False, method="first").astype(int)
df["risk_band"] = pd.cut(df.risk_rank, [0, len(df) * 0.10, len(df) * 0.30, len(df)], labels=["High", "Medium", "Low"])

# ---------------------------------------------------------------------------
# 2. Personas: simple rules, checked in order, so anyone can see why a person is in a group
# ---------------------------------------------------------------------------
# Checked in ORDER OF URGENCY: problems we can fix (payment, quality) come before
# content and habits, so each person lands in the group that suggests the first action to take.
PERSONAS = [
    ("Payment-troubled", "Want to stay but billing keeps failing",
     lambda d: (d.failed_renewals_30d + d.low_balance_renewals_30d) >= 2),
    ("Frustrated by quality", "Buffering, crashes, slow starts or an angry ticket",
     lambda d: (d.video_start_sec > 4) | (d.app_crashes_7d >= 2) | (d.ticket_negative == 1)),
    ("Seasonal live fans", "Came for a live event that has just ended",
     lambda d: (d.fav_content_ended == 1) & (d.live_share >= 0.6)),
    ("Fading viewers", "Watching steadily less for weeks",
     lambda d: (d.watch_trend_8w_pct <= -15) | (d.watch_change_pct <= -40)),
    ("Discount hunters", "Joined on an offer and ignore other messages",
     lambda d: (d.used_discount == 1) & (d.offer_open_rate < 0.3)),
    ("Engaged regulars", "Everyone else: watching and paying normally",
     lambda d: pd.Series(True, index=d.index)),
]
df["persona"] = None
for name, _, rule in PERSONAS:
    df.loc[df.persona.isna() & rule(df), "persona"] = name
df["revenue_at_risk"] = df.churn_score * df.monthly_revenue_pkr

personas = []
for name, desc, _ in PERSONAS:
    g = df[df.persona == name]
    personas.append({"persona": name, "description": desc, "subscribers": int(len(g)),
                     "avg_risk": round(float(g.churn_score.mean()), 3),
                     "high_risk": int((g.risk_band == "High").sum()),
                     "revenue_at_risk_pkr": int(g.revenue_at_risk.sum())})

# ---------------------------------------------------------------------------
# 3. Content view: the release calendar joined with risk
# ---------------------------------------------------------------------------
content = []
for _, c in calendar.iterrows():
    g = df[(df.favourite_genre == c.genre)]
    ended = g[g.fav_content_ended == 1]
    content.append({
        "genre": c.genre, "ended_title": c.ended_title, "ended_days_ago": int(c.ended_days_ago),
        "next_title": c.next_title, "next_release_in_days": int(c.next_release_in_days),
        "fans": int(len(g)), "fans_whose_title_ended": int(len(ended)),
        "high_risk_waiting": int((ended.risk_band == "High").sum()),
        "avg_risk_waiting": round(float(ended.churn_score.mean()), 3) if len(ended) else 0.0,
        "revenue_at_risk_waiting_pkr": int(ended.revenue_at_risk.sum()),
    })

# ---------------------------------------------------------------------------
# 4. Watchlist (top 500) with reasons and facts for the explain panel
# ---------------------------------------------------------------------------
FACT_COLS = ["watch_change_pct", "watch_trend_8w_pct", "days_since_active", "completion_rate",
             "category_concentration", "fav_content_ended", "days_to_next_release", "failed_renewals_30d",
             "low_balance_renewals_30d", "buffering_errors_7d", "app_crashes_7d", "video_start_sec",
             "support_tickets_30d", "ticket_negative", "offer_open_rate", "tenure_days", "sessions_7d"]
watchlist = []
for i, r in df.nsmallest(500, "risk_rank").iterrows():
    watchlist.append({
        "id": r.subscriber_id, "score": round(float(r.churn_score), 3), "rank": int(r.risk_rank),
        "plan": r.plan, "channel": r.payment_channel, "city": r.city, "genre": r.favourite_genre,
        "persona": r.persona, "revenue": int(r.monthly_revenue_pkr), "tenure": int(r.tenure_days),
        "reasons": top_reasons(i),
        "facts": {f: float(r[f]) for f in FACT_COLS},
    })
population_avg = {f: round(float(df[f].mean()), 2) for f in FACT_COLS}

# Reasons among the high-risk 10%
high = df[df.risk_band == "High"]
counts = {}
for i in high.index:
    for r in top_reasons(i):
        counts[r["code"]] = counts.get(r["code"], 0) + 1
reason_summary = sorted([{"code": c, "label": LABEL[c], "group": GROUP[c], "count": n,
                          "share": round(n / len(high), 3)} for c, n in counts.items()], key=lambda d: -d["count"])
group_summary = {}
for r in reason_summary:
    group_summary[r["group"]] = group_summary.get(r["group"], 0) + r["count"]
# Themes for executives: share of high-risk subscribers with at least one reason in each theme
theme_people = {}
for i in high.index:
    for g in {r["group"] for r in top_reasons(i)}:
        theme_people[g] = theme_people.get(g, 0) + 1
theme_summary = sorted([{"theme": g, "share": round(n / len(high), 3), "people": n}
                        for g, n in theme_people.items()], key=lambda t: -t["share"])

# ---------------------------------------------------------------------------
# 5. Segments and 6. deciles
# ---------------------------------------------------------------------------
def segment(col):
    g = df.groupby(col).agg(subscribers=("subscriber_id", "size"), avg_risk=("churn_score", "mean"),
                            expected_churners=("churn_score", "sum"),
                            revenue_at_risk_pkr=("revenue_at_risk", "sum"),
                            high_risk=("risk_band", lambda s: (s == "High").sum()))
    g = g.reset_index().rename(columns={col: "segment"}).sort_values("avg_risk", ascending=False)
    return g.round({"avg_risk": 3, "expected_churners": 0, "revenue_at_risk_pkr": 0}).to_dict(orient="records")


segments = {c: segment(c) for c in ["plan", "payment_channel", "favourite_genre", "signup_source",
                                    "network", "device", "city"]}
df["decile"] = pd.qcut(df.risk_rank, 10, labels=list(range(1, 11))).astype(int)
deciles = (df.groupby("decile").agg(subscribers=("subscriber_id", "size"), avg_score=("churn_score", "mean"),
                                    expected_churners=("churn_score", "sum"), avg_revenue=("monthly_revenue_pkr", "mean"))
           .reset_index().round(3).to_dict(orient="records"))

# ---------------------------------------------------------------------------
# 7. Did the model learn the true rules from Step 1?
# ---------------------------------------------------------------------------
TRUE_DIRECTION = {
    "watch_change_pct": "-", "watch_trend_8w_pct": "-", "days_since_active": "+", "completion_rate": "-",
    "category_concentration": "+", "fav_content_ended": "+", "catalogue_match_titles": "-",
    "recs_ignored_30d": "+", "failed_renewals_30d": "+", "low_balance_renewals_30d": "+",
    "payment_switches_90d": "+", "buffering_errors_7d": "+", "app_crashes_7d": "+", "video_start_sec": "+",
    "login_failures_30d": "+", "plan_downgrades_90d": "+", "past_cancellations": "+", "used_discount": "+",
    "support_tickets_30d": "+", "ticket_negative": "+", "ticket_resolved": "-", "tenure_days": "-",
}
rule_check = [{"feature": f, "true_effect": "raises churn" if d == "+" else "lowers churn",
               "model_coefficient": round(float(coef[f"num__{f}"]), 3),
               "matches": bool((coef[f"num__{f}"] > 0) == (d == "+"))} for f, d in TRUE_DIRECTION.items()]

kpis = {
    "subscribers": int(len(df)), "expected_churners": int(df.churn_score.sum()),
    "expected_churn_rate": round(float(df.churn_score.mean()), 3),
    "high_risk_subscribers": int((df.risk_band == "High").sum()),
    "revenue_at_risk_pkr": int(df.revenue_at_risk.sum()),
    "high_risk_revenue_at_risk_pkr": int(df.loc[df.risk_band == "High", "revenue_at_risk"].sum()),
    "avg_revenue_pkr": round(float(df.monthly_revenue_pkr.mean()), 0),
    "signals": len(NUMERIC) + len(CATEGORICAL),
}
chosen = metrics["chosen_model"]
out = {"kpis": kpis, "population_avg": population_avg, "reason_summary": reason_summary,
       "group_summary": group_summary, "theme_summary": theme_summary, "personas": personas, "content": content, "segments": segments,
       "deciles": deciles, "watchlist": watchlist, "rule_check": rule_check,
       "model": {"name": chosen, **metrics["results"][chosen],
                 "comparison": {n: {k: r[k] for k in ["auc", "precision_top10", "recall_top10", "lift_top10", "brier"]}
                                for n, r in metrics["results"].items()},
                 "targets": metrics["targets"], "ceiling": metrics["ceiling"]}}
Path("public/data").mkdir(parents=True, exist_ok=True)
json.dump(out, open("public/data/dashboard.json", "w"), indent=1, default=float)

# --- Print what we found ------------------------------------------------------
print("KPIs:")
for k, v in kpis.items():
    print(f"  {k:32s} {v:,}")
print(f"\nTop reasons among the high-risk 10% ({len(high):,} subscribers):")
for r in reason_summary[:10]:
    print(f"  {r['label']:36s} {r['group']:12s} {r['share']:.0%}")
print("\nPersonas:")
for p in personas:
    print(f"  {p['persona']:22s} {p['subscribers']:>7,} subs  avg risk {p['avg_risk']:.1%}  "
          f"high-risk {p['high_risk']:>6,}  PKR {p['revenue_at_risk_pkr']:>9,} at risk")
print("\nContent calendar x risk:")
for c in content:
    print(f"  {c['genre']:7s} ended: {c['ended_title'][:28]:28s} next in {c['next_release_in_days']:>2}d  "
          f"waiting {c['fans_whose_title_ended']:>6,}  high-risk {c['high_risk_waiting']:>5,}  avg {c['avg_risk_waiting']:.1%}")
learned = sum(r["matches"] for r in rule_check)
print(f"\nTrue rules recovered by the model: {learned} of {len(rule_check)}")
for r in rule_check:
    if not r["matches"]:
        print(f"  NOT recovered: {r['feature']} (truth: {r['true_effect']}, coef {r['model_coefficient']:+.3f})")
w = watchlist[0]
print(f"\nRiskiest subscriber {w['id']} ({w['score']:.0%}, persona: {w['persona']}):")
for r in w["reasons"]:
    print(f"   - {r['text']}")
print("\nSaved public/data/dashboard.json")
