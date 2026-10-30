"""
The learning loop: keep the churn model accurate as customer behaviour changes.

  1. outcomes   rebuild what we knew 30 days ago, and see who actually cancelled since
  2. monitor    how accurate was the live model on those customers? has behaviour drifted?
  3. retrain    train a challenger on the latest outcomes
  4. compare    challenger vs live model, on the same held-out recent customers
  5. promote    switch only if the challenger is clearly better - after a person approves,
                or automatically if auto-promote is switched on
Everything runs here, inside the company network, next to the database.
"""
import json
import shutil
import time
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

DIR = Path(__file__).with_name("models")
REGISTRY = DIR / "registry.json"
ACTIVE = DIR / "active.json"
BASELINE = Path(__file__).resolve().parent.parent / "public" / "model" / "churn_model.json"
FMT = "%Y-%m-%d %H:%M:%S"
HORIZON = 30                       # days: "will this customer cancel within 30 days?"
GATE_AUC = 0.01                    # a challenger must beat the live model's AUC by at least this much
DRIFT_FEATURES = ["watch_min_last_7d", "days_since_active", "failed_renewals_30d", "buffering_errors_7d",
                  "video_start_sec", "support_tickets_30d", "completion_rate", "monthly_revenue_pkr"]
NICE = {"video_start_sec": "Video start time", "buffering_errors_7d": "Buffering errors", "app_crashes_7d": "App crashes",
        "failed_renewals_30d": "Failed renewals", "low_balance_renewals_30d": "Low-balance renewals", "watch_change_pct": "Change in viewing",
        "watch_trend_8w_pct": "8-week viewing trend", "days_since_active": "Days inactive", "ticket_negative": "Negative ticket",
        "support_tickets_30d": "Support tickets", "completion_rate": "Completion rate", "tenure_days": "Tenure",
        "watch_min_last_7d": "Minutes watched (7d)", "monthly_revenue_pkr": "Monthly revenue"}


def derive(df):
    d = df.copy()
    d["watch_change_pct"] = ((d.watch_min_last_7d - d.watch_min_prev_7d) / (d.watch_min_prev_7d + 30) * 100).round(1)
    d["offer_open_rate"] = (d.offers_opened_90d / d.offers_received_90d.clip(lower=1)).round(2)
    d["ticket_negative"] = (d.ticket_sentiment == "negative").astype(int)
    return d


def score_json(model, df):
    """Score customers with a model in the browser's JSON format (identical maths to the website)."""
    d = derive(df)
    z = np.full(len(d), model["intercept"])
    for f in model["numeric"]:
        z += f["weight"] * (d[f["name"]].astype(float).values - f["mean"]) / f["scale"]
    for c in model["categorical"]:
        z += d[c["name"]].astype(str).map(c["weights"]).fillna(0).values
    return 1 / (1 + np.exp(-z))


def metrics(y, p):
    y, p = np.asarray(y), np.asarray(p)
    top = np.argsort(-p)[: max(1, len(p) // 10)]
    band = p >= np.quantile(p, .9)
    return {"auc": round(float(roc_auc_score(y, p)), 3) if 0 < y.sum() < len(y) else None,
            "precision_top10": round(float(y[top].mean()), 3), "lift_top10": round(float(y[top].mean() / max(y.mean(), 1e-9)), 2),
            "predicted_top": round(float(p[band].mean()), 3), "actual_top": round(float(y[band].mean()), 3),
            "predicted_rate": round(float(p.mean()), 3), "actual_rate": round(float(y.mean()), 3), "n": int(len(y))}


def train(df, model_like):
    """Fit a challenger with the same signals as the live model, export it in the browser's format."""
    num = [f["name"] for f in model_like["numeric"]]
    cat = [c["name"] for c in model_like["categorical"]]
    d = derive(df)
    prep = ColumnTransformer([("num", StandardScaler(), num), ("cat", OneHotEncoder(handle_unknown="ignore"), cat)])
    pipe = Pipeline([("prep", prep), ("model", LogisticRegression(max_iter=3000, C=1.0))])
    pipe.fit(d[num + cat].assign(**{c: d[c].astype(str) for c in cat}), d.churned)
    sc, oh, lr = prep.named_transformers_["num"], prep.named_transformers_["cat"], pipe["model"]
    w = lr.coef_[0]
    out = {"name": "", "intercept": float(lr.intercept_[0]),
           "numeric": [{"name": f, "mean": float(m), "scale": float(s or 1), "weight": float(x)} for f, m, s, x in zip(num, sc.mean_, sc.scale_, w[:len(num)])],
           "categorical": [], "derived": model_like.get("derived", {})}
    i = len(num)
    for f, cats in zip(cat, oh.categories_):
        out["categorical"].append({"name": f, "weights": {str(c): float(x) for c, x in zip(cats, w[i:i + len(cats)])}})
        i += len(cats)
    return out


def weight_changes(old, new, k=5):
    o = {f["name"]: f["weight"] for f in old["numeric"]}
    ch = [{"feature": f["name"], "label": NICE.get(f["name"], f["name"].replace("_", " ")), "before": round(o.get(f["name"], 0), 3),
           "after": round(f["weight"], 3)} for f in new["numeric"]]
    return sorted(ch, key=lambda c: -abs(c["after"] - c["before"]))[:k]


def psi(ref_edges, ref_share, values):
    """Population stability index: how far today's distribution has moved from the reference."""
    cnt = np.histogram(np.clip(values, ref_edges[0], ref_edges[-1]), bins=ref_edges)[0]
    cur = cnt / max(cnt.sum(), 1)
    a, b = np.clip(np.asarray(ref_share), 1e-4, None), np.clip(cur, 1e-4, None)
    return float(np.sum((b - a) * np.log(b / a)))


def reference(df):
    ref = {}
    for f in DRIFT_FEATURES:
        v = derive(df)[f].astype(float).values
        edges = np.unique(np.quantile(v, np.linspace(0, 1, 11)))
        if len(edges) < 3:
            edges = np.array([v.min() - 1, v.mean(), v.max() + 1])
        share = np.histogram(v, bins=edges)[0] / len(v)
        ref[f] = {"edges": edges.tolist(), "share": share.tolist()}
    return ref


class Registry:
    def __init__(self):
        DIR.mkdir(exist_ok=True)
        self.r = json.loads(REGISTRY.read_text()) if REGISTRY.exists() else None

    def save(self):
        REGISTRY.write_text(json.dumps(self.r, indent=1))

    def bootstrap(self, live_df, platform_time):
        if self.r:
            return
        shutil.copy(BASELINE, ACTIVE)
        self.r = {"versions": [{"version": 1, "label": "Initial model (trained offline)", "status": "live", "trained_at": None,
                                "activated_at": platform_time, "metrics": None}],
                  "candidate": None, "reference": reference(live_df), "reference_at": platform_time,
                  "settings": {"auto_retrain_days": 7, "auto_promote": False}, "last_retrain_at": platform_time, "realized": None}
        self.save()

    def active_model(self):
        return json.loads(ACTIVE.read_text())

    def drift(self, live_df):
        out = []
        for f, ref in self.r["reference"].items():
            v = psi(np.array(ref["edges"]), ref["share"], derive(live_df)[f].astype(float).values)
            out.append({"feature": f, "label": NICE.get(f, f), "psi": round(v, 3),
                        "status": "major" if v >= .25 else "moderate" if v >= .1 else "stable"})
        return sorted(out, key=lambda x: -x["psi"])

    def realized(self, past_df):
        """How the LIVE model actually did on the customers it would have scored 30 days ago."""
        p = score_json(self.active_model(), past_df)
        self.r["realized"] = metrics(past_df.churned, p)
        self.save()
        return self.r["realized"]

    def retrain(self, past_df, platform_time, live_df, auto_promote=None):
        """Train a challenger on the latest outcomes and compare it with the live model on held-out customers."""
        champ = self.active_model()
        train_df, test_df = train_test_split(past_df, test_size=.3, stratify=past_df.churned, random_state=int(time.time()) % 10_000)
        chall = train(train_df, champ)
        m_new, m_old = metrics(test_df.churned, score_json(chall, test_df)), metrics(test_df.churned, score_json(champ, test_df))
        better = (m_new["auc"] or 0) >= (m_old["auc"] or 0) + GATE_AUC
        version = max(v["version"] for v in self.r["versions"]) + 1
        chall["name"] = f"Churn Radar v{version} (retrained {platform_time[:10]})"
        (DIR / f"v{version}.json").write_text(json.dumps(chall))
        self.r["candidate"] = {"version": version, "trained_at": platform_time, "train_customers": len(train_df), "test_customers": len(test_df),
                               "outcomes": int(past_df.churned.sum()), "challenger": m_new, "live": m_old, "better": better,
                               "changes": weight_changes(champ, chall), "reference": reference(live_df)}
        self.r["last_retrain_at"] = platform_time
        self.save()
        if better and (self.r["settings"]["auto_promote"] if auto_promote is None else auto_promote):
            self.promote(platform_time, by="auto-promote")
        return self.r["candidate"]

    def promote(self, platform_time, by="approved"):
        c = self.r.get("candidate")
        if not c:
            raise ValueError("there is no candidate model to promote")
        shutil.copy(DIR / f"v{c['version']}.json", ACTIVE)
        for v in self.r["versions"]:
            if v["status"] == "live":
                v["status"] = "retired"
        self.r["versions"].append({"version": c["version"], "label": f"Retrained on {c['outcomes']:,} recent outcomes", "status": "live",
                                   "trained_at": c["trained_at"], "activated_at": platform_time, "metrics": c["challenger"], "promoted_by": by})
        self.r["reference"], self.r["reference_at"] = c["reference"], platform_time
        self.r["candidate"] = None
        self.save()
