"""
Churn Radar Connector - runs INSIDE the company network, next to the database.

It reads the raw platform tables, turns them into the 40 signals the model needs, and serves
them to the Churn Radar web app open in the same network. Database credentials and customer rows
never pass through the public website or any cloud: the browser fetches straight from this agent
and scores the customers itself (Phase 1, row 6b).

Database
  Demo:        the SQLite file made by create_demo_db.py (default)
  SQL Server:  set CONNECTOR_DSN, e.g.
               CONNECTOR_DSN="Driver={ODBC Driver 18 for SQL Server};Server=sql01;Database=ott;Trusted_Connection=yes;"
               and `pip install pyodbc`. The queries below are plain SELECTs that run on both.

Endpoints (http://localhost:8765)
  GET /health        status, database, active customers, platform clock, activity since last sync
  GET /signals.csv   one row per active customer, columns = the 40 Churn Radar signals

Run:   .venv/bin/python connector/agent.py
"""
import io
import json
import os
import sqlite3
import time
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock, Thread

import learn

import numpy as np
import pandas as pd

PORT = int(os.environ.get("CONNECTOR_PORT", 8765))
DSN = os.environ.get("CONNECTOR_DSN")
SQLITE = Path(os.environ.get("CONNECTOR_SQLITE", Path(__file__).with_name("lumen_play.db")))
FMT = "%Y-%m-%d %H:%M:%S"
CACHE_SECONDS = 5


def connect():
    if DSN:
        import pyodbc                                     # only needed for a real SQL Server
        return pyodbc.connect(DSN), "SQL Server"
    con = sqlite3.connect(f"file:{SQLITE}?mode=ro", uri=True, timeout=30)
    return con, "SQLite (demo stand-in for SQL Server)"


def q(con, sql, params=()):
    return pd.read_sql_query(sql, con, params=list(params))


def platform_now(con):
    return datetime.strptime(str(q(con, "SELECT now FROM platform_clock").iloc[0, 0])[:19], FMT)


def build_signals(con, as_of=None, with_label=False, horizon_days=30):
    """Raw tables -> one row of 40 signals per customer who was active at `as_of` (default: now).
    Only events BEFORE as_of are used, so we can rebuild exactly what we knew on a past date.
    with_label adds `churned` = cancelled within `horizon_days` after as_of (the outcome to learn from)."""
    now = as_of or platform_now(con)
    stamp = now.strftime(FMT)
    ago = lambda d: (now - timedelta(days=d)).strftime(FMT)
    cust = q(con, "SELECT * FROM customers WHERE signup_date <= ? AND (cancelled_at IS NULL OR cancelled_at > ?)", (stamp, stamp))
    ids = cust.customer_id
    out = pd.DataFrame({"subscriber_id": ids})
    for c in ["plan", "payment_channel", "city", "device", "network", "signup_source", "favourite_genre", "past_cancellations"]:
        out[c] = cust[c].values
    out["monthly_revenue_pkr"] = cust.monthly_price_pkr.values
    out["used_discount"] = cust.joined_on_discount.values
    out["tenure_days"] = (now - pd.to_datetime(cust.signup_date)).dt.days.clip(lower=0).values

    # --- viewing (last 8 weeks)
    s = q(con, "SELECT customer_id, started_at, minutes, genre, is_live, completed, start_time_sec, buffering_events FROM viewing_sessions WHERE started_at >= ? AND started_at < ?", (ago(56), stamp))
    s["age"] = (now - pd.to_datetime(s.started_at)).dt.total_seconds() / 86400
    s["week"] = (s.age // 7).astype(int).clip(0, 7)                       # 0 = this week
    wk = s.pivot_table(index="customer_id", columns="week", values="minutes", aggfunc="sum", fill_value=0).reindex(ids, fill_value=0)
    for w in range(8):
        if w not in wk:
            wk[w] = 0
    out["watch_min_last_7d"] = wk[0].values.round(0)
    out["watch_min_prev_7d"] = wk[1].values.round(0)
    x = np.arange(8)[::-1]                                                # oldest week first -> slope per week
    W = wk[[7, 6, 5, 4, 3, 2, 1, 0]].values
    slope = ((x[::-1] - x.mean()) * (W - W.mean(axis=1, keepdims=True))).sum(axis=1) / ((x - x.mean()) ** 2).sum()
    out["watch_trend_8w_pct"] = np.clip(slope * 4 / np.maximum(W.mean(axis=1), 30) * 100, -80, 80).round(1)
    last7, last30 = s[s.age <= 7], s[s.age <= 30]
    g7, g30 = last7.groupby("customer_id"), last30.groupby("customer_id")
    out["sessions_7d"] = g7.size().reindex(ids, fill_value=0).values
    last_seen = s.groupby("customer_id").age.min().reindex(ids)
    out["days_since_active"] = last_seen.fillna(56).clip(upper=30).astype(int).values
    out["completion_rate"] = g30.completed.mean().reindex(ids).fillna(0.55).round(2).values
    out["distinct_titles_30d"] = np.ceil(g30.size().reindex(ids, fill_value=0) * 0.35).clip(lower=1).astype(int).values   # ~3 sessions per title
    top = last30.groupby(["customer_id", "genre"]).minutes.sum().groupby(level=0)
    out["category_concentration"] = (top.max() / top.sum()).reindex(ids).fillna(0.7).round(2).values
    out["live_share"] = (last30.minutes * last30.is_live).groupby(last30.customer_id).sum().div(g30.minutes.sum()).reindex(ids).fillna(0.2).round(2).values
    out["binge_sessions_30d"] = last30[last30.minutes >= 120].groupby("customer_id").size().reindex(ids, fill_value=0).values
    out["video_start_sec"] = g7.start_time_sec.mean().reindex(ids).fillna(2.0).round(1).values
    out["buffering_errors_7d"] = g7.buffering_events.sum().reindex(ids, fill_value=0).values

    # --- content timing (release calendar)
    rel = q(con, "SELECT * FROM content_releases").set_index("genre")
    ended = {g: (now - pd.to_datetime(r.ended_at)).days for g, r in rel.iterrows()}
    nxt = {g: max(0, (pd.to_datetime(r.next_release_at) - now).days) for g, r in rel.iterrows()}
    fav = cust.favourite_genre.values
    # A follower = most of their viewing was in that genre, and for live genres mostly live
    gmin = last30.groupby(["customer_id", "genre"]).minutes.sum()
    share = (gmin / gmin.groupby(level=0).transform("sum"))
    live = out.set_index("subscriber_id").live_share
    out["fav_content_ended"] = [int(0 <= ended.get(g, 99) <= 14 and g != "News" and share.get((i, g), 0) >= 0.75
                                    and (g != "Sports" or live.get(i, 0) >= 0.5)) for i, g in zip(ids, fav)]
    out["days_to_next_release"] = [nxt.get(g, 7) for g in fav]
    out["catalogue_match_titles"] = [18 if g == "Kids" else 35 for g in fav]
    r = q(con, "SELECT customer_id, clicked FROM recommendations WHERE shown_at >= ? AND shown_at < ?", (ago(30), stamp))
    out["recs_ignored_30d"] = r[r.clicked == 0].groupby("customer_id").size().reindex(ids, fill_value=0).values

    # --- payment
    b = q(con, "SELECT customer_id, ts, event FROM billing_events WHERE ts >= ? AND ts < ?", (ago(90), stamp))
    b30 = b[b.ts >= ago(30)]
    cnt = lambda d, e: d[d.event == e].groupby("customer_id").size().reindex(ids, fill_value=0).values
    out["failed_renewals_30d"] = cnt(b30, "renewal_failed")
    out["low_balance_renewals_30d"] = cnt(b30, "low_balance")
    out["recharges_30d"] = cnt(b30, "recharge")
    out["payment_switches_90d"] = cnt(b, "method_switch")

    # --- experience
    a = q(con, "SELECT customer_id, ts, event FROM app_events WHERE ts >= ? AND ts < ?", (ago(30), stamp))
    out["app_crashes_7d"] = cnt(a[a.ts >= ago(7)], "crash")
    out["login_failures_30d"] = cnt(a, "login_failure")

    # --- plan history, marketing
    pc = q(con, "SELECT customer_id FROM plan_changes WHERE kind = 'downgrade' AND ts >= ? AND ts < ?", (ago(90), stamp))
    out["plan_downgrades_90d"] = pc.groupby("customer_id").size().reindex(ids, fill_value=0).values
    m = q(con, "SELECT customer_id, opened FROM marketing_offers WHERE sent_at >= ? AND sent_at < ?", (ago(90), stamp))
    out["offers_received_90d"] = m.groupby("customer_id").size().reindex(ids, fill_value=0).values
    out["offers_opened_90d"] = m.groupby("customer_id").opened.sum().reindex(ids, fill_value=0).values

    # --- support (latest ticket in the last 30 days)
    t = q(con, "SELECT customer_id, opened_at, sentiment, resolved FROM support_tickets WHERE opened_at >= ? AND opened_at < ? ORDER BY opened_at", (ago(30), stamp))
    out["support_tickets_30d"] = t.groupby("customer_id").size().reindex(ids, fill_value=0).values
    latest = t.groupby("customer_id").last()
    out["ticket_sentiment"] = latest.sentiment.reindex(ids).fillna("none").values
    out["ticket_resolved"] = latest.resolved.reindex(ids).fillna(1).astype(int).values

    if with_label:
        end = (now + timedelta(days=horizon_days)).strftime(FMT)
        out["churned"] = [int(c is not None and stamp < str(c) <= end) for c in cust.cancelled_at.values]
    stats = {
        "platform_time": now.strftime(FMT),
        "active_customers": int(len(cust)),
        "cancelled_total": int(q(con, "SELECT COUNT(*) AS n FROM customers WHERE status = 'cancelled'").n[0]),
        "sessions_last_hour": int((s.age <= 1 / 24).sum()),
        "events_last_day": int((s.age <= 1).sum() + (b.ts >= ago(1)).sum() + (a.ts >= ago(1)).sum()),
        "tables": ["customers", "viewing_sessions", "billing_events", "app_events", "support_tickets",
                   "marketing_offers", "recommendations", "plan_changes", "content_releases"],
    }
    return out, stats


_lock, _cache = Lock(), {"t": 0, "csv": b"", "stats": {}, "prev": None}
_ml_lock = Lock()
REG = learn.Registry()


def _live_and_past():
    con, _ = connect()
    try:
        now = platform_now(con)
        live, _ = build_signals(con)
        past, _ = build_signals(con, as_of=now - timedelta(days=learn.HORIZON), with_label=True)
    finally:
        con.close()
    return now.strftime(FMT), live, past


def model_status(refresh=True):
    """Everything the Model health page shows about the live learning loop."""
    with _ml_lock:
        t, live, past = _live_and_past()
        REG.bootstrap(live, t)
        if refresh:
            REG.realized(past)
        days_since = (datetime.strptime(t, FMT) - datetime.strptime(REG.r["last_retrain_at"], FMT)).total_seconds() / 86400
        cand = dict(REG.r["candidate"]) if REG.r.get("candidate") else None
        if cand:
            cand.pop("reference", None)
        return {"platform_time": t, "live_version": next(v for v in REG.r["versions"] if v["status"] == "live"),
                "versions": REG.r["versions"], "candidate": cand, "realized": REG.r["realized"], "drift": REG.drift(live),
                "reference_at": REG.r["reference_at"], "settings": REG.r["settings"], "days_since_retrain": round(days_since, 1),
                "outcomes_available": int(past.churned.sum()), "horizon_days": learn.HORIZON}


def retrain_now(auto_promote=None):
    with _ml_lock:
        t, live, past = _live_and_past()
        REG.bootstrap(live, t)
        REG.realized(past)
        REG.retrain(past, t, live, auto_promote)
    return model_status(refresh=False)


def scheduler():
    """Automatic retraining every N platform days (and promotion, only if auto-promote is on)."""
    while True:
        time.sleep(20)
        try:
            if REG.r is None:
                continue
            con, _ = connect(); now = platform_now(con); con.close()
            last = datetime.strptime(REG.r["last_retrain_at"], FMT)
            every = REG.r["settings"]["auto_retrain_days"]
            if every and (now - last).total_seconds() / 86400 >= every:
                print(f"{datetime.now():%H:%M:%S}  scheduled retrain (every {every} platform days)")
                retrain_now()
        except Exception as e:
            print("scheduler:", e)


def snapshot():
    with _lock:
        if time.time() - _cache["t"] > CACHE_SECONDS:
            con, kind = connect()
            try:
                t0 = time.time()
                df, stats = build_signals(con)
            finally:
                con.close()
            buf = io.StringIO(); df.to_csv(buf, index=False)
            prev = _cache["prev"]
            ids = set(df.subscriber_id)
            stats.update({"database": kind, "build_seconds": round(time.time() - t0, 2), "synced_at": datetime.now().strftime(FMT),
                          "new_since_last": len(ids - prev) if prev is not None else 0,
                          "gone_since_last": len(prev - ids) if prev is not None else 0})
            _cache.update(t=time.time(), csv=buf.getvalue().encode(), stats=stats, prev=ids)
        return _cache["csv"], _cache["stats"]


class Handler(BaseHTTPRequestHandler):
    def _headers(self, status, ctype, length=None):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Access-Control-Allow-Origin", "*")                 # the web app runs on another origin
        self.send_header("Access-Control-Allow-Private-Network", "true")     # Chrome: public site -> local agent
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Cache-Control", "no-store")
        if length is not None:
            self.send_header("Content-Length", str(length))
        self.end_headers()

    def do_OPTIONS(self):
        self._headers(204, "text/plain", 0)

    def do_GET(self):
        try:
            if self.path.startswith("/health"):
                _, stats = snapshot()
                body = json.dumps({"status": "ok", "agent": "Churn Radar Connector 1.0", **stats}).encode()
                self._headers(200, "application/json", len(body)); self.wfile.write(body)
            elif self.path.startswith("/model/status"):
                body = json.dumps(model_status()).encode()
                self._headers(200, "application/json", len(body)); self.wfile.write(body)
            elif self.path.startswith("/model"):
                if REG.r is None:
                    model_status()
                body = learn.ACTIVE.read_bytes()
                self._headers(200, "application/json", len(body)); self.wfile.write(body)
            elif self.path.startswith("/signals.csv"):
                body, _ = snapshot()
                self._headers(200, "text/csv", len(body)); self.wfile.write(body)
            else:
                self._headers(404, "text/plain", 0)
        except Exception as e:
            body = json.dumps({"status": "error", "error": str(e)[:300]}).encode()
            self._headers(500, "application/json", len(body)); self.wfile.write(body)

    def do_POST(self):
        """Model operations, only from the network the agent serves: retrain, promote, settings."""
        try:
            n = int(self.headers.get("Content-Length") or 0)
            data = json.loads(self.rfile.read(n) or b"{}") if n else {}
            if self.path.startswith("/model/retrain"):
                out = retrain_now()
            elif self.path.startswith("/model/promote"):
                with _ml_lock:
                    con, _ = connect(); t = platform_now(con).strftime(FMT); con.close()
                    REG.promote(t, by="approved")
                out = model_status(refresh=True)
            elif self.path.startswith("/model/settings"):
                st = REG.r["settings"]
                if "auto_promote" in data: st["auto_promote"] = bool(data["auto_promote"])
                if "auto_retrain_days" in data: st["auto_retrain_days"] = max(0, min(90, int(data["auto_retrain_days"])))
                REG.save(); out = model_status(refresh=False)
            else:
                self._headers(404, "text/plain", 0); return
            body = json.dumps(out).encode()
            self._headers(200, "application/json", len(body)); self.wfile.write(body)
        except Exception as e:
            body = json.dumps({"status": "error", "error": str(e)[:300]}).encode()
            self._headers(400, "application/json", len(body)); self.wfile.write(body)

    def log_message(self, fmt, *args):
        print(f"{datetime.now():%H:%M:%S}  {self.address_string()}  {fmt % args}")


if __name__ == "__main__":
    con, kind = connect(); con.close()
    print(f"Churn Radar Connector on http://localhost:{PORT}  ({kind})")
    print("Open Churn Radar -> Data sources -> Live database, and connect to this address. Ctrl+C to stop.")
    _, st = snapshot()
    print(f"First snapshot: {st['active_customers']:,} active customers, platform time {st['platform_time']}, built in {st['build_seconds']}s")
    st = model_status()
    print(f"Live model v{st['live_version']['version']}: realised AUC {st['realized']['auc']} on last month's customers; "
          f"auto-retrain every {st['settings']['auto_retrain_days']} platform days, auto-promote {'on' if st['settings']['auto_promote'] else 'off'}")
    Thread(target=scheduler, daemon=True).start()
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
