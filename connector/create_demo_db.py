"""
Create a realistic demo database for an OTT platform (Lumen Play), with 8 weeks of history.

This stands in for the company's SQL Server warehouse. It holds RAW operational data, the way a
streaming platform actually records it - not the ready-made 40 signals. The connector agent
(connector/agent.py) turns these raw tables into signals, exactly as it would on SQL Server.

Tables
  customers          one row per customer: plan, channel, city, device, status ...
  viewing_sessions   every playback session: minutes, genre, live?, completed?, start time, buffering
  billing_events     renewal_success / renewal_failed / low_balance / recharge / method_switch
  app_events         crash / login_failure
  support_tickets    opened_at, sentiment, resolved
  marketing_offers   sent_at, opened
  recommendations    shown_at, clicked
  plan_changes       upgrades and downgrades
  content_releases   the release calendar per genre
  platform_clock     the platform's current time (the simulator moves it forward)
  _sim_traits        hidden behaviour of each customer, used only by the simulator

Run:  .venv/bin/python connector/create_demo_db.py          (creates connector/lumen_play.db)
"""
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

DB = Path(__file__).with_name("lumen_play.db")
N = 10_000
WEEKS = 8
rng = np.random.default_rng(2026)
NOW = datetime.now().replace(minute=0, second=0, microsecond=0)
ts = lambda d: d.strftime("%Y-%m-%d %H:%M:%S")

PLANS = {"Daily": 300, "Weekly": 240, "Monthly": 250, "Sports Premium": 450}
RENEW_EVERY = {"Daily": 1, "Weekly": 7, "Monthly": 30, "Sports Premium": 30}   # days
GENRES = ["Sports", "Drama", "Movies", "Kids", "News"]
CITIES = ["Karachi", "Lahore", "Islamabad", "Faisalabad", "Peshawar", "Other"]


def fail_chance(fragility, plan):
    """Chance a single renewal attempt fails. Frequent renewals (daily packs) fail less per attempt."""
    return fragility * (RENEW_EVERY[plan] / 30) ** 0.6


def make_customers(n, start_id, now, rng):
    ids = [f"LP{start_id + i:07d}" for i in range(n)]
    channel = rng.choice(["Operator 1", "Operator 2", "Operator 3", "Operator 4", "Wallet", "Card"], n, p=[.30, .22, .18, .10, .12, .08])
    plan = rng.choice(list(PLANS), n, p=[.30, .25, .30, .15])
    device = rng.choice(["Android", "iOS", "Smart TV", "Web"], n, p=[.68, .12, .10, .10])
    network = np.where(device == "Smart TV", "WiFi", rng.choice(["4G", "3G", "WiFi"], n, p=[.55, .15, .30]))
    genre = np.where(plan == "Sports Premium", "Sports", rng.choice(GENRES, n, p=[.32, .30, .20, .10, .08]))
    tenure = rng.gamma(2.0, 120, n).astype(int) + 1
    cust = pd.DataFrame({
        "customer_id": ids, "signup_date": [ts(now - timedelta(days=int(t))) for t in tenure],
        "city": rng.choice(CITIES, n, p=[.28, .24, .12, .08, .08, .20]), "device": device, "network": network,
        "signup_source": rng.choice(["Operator bundle", "Social ad", "Referral", "Organic", "TV promo"], n, p=[.30, .25, .10, .25, .10]),
        "favourite_genre": genre, "payment_channel": channel, "plan": plan,
        "monthly_price_pkr": [PLANS[p] for p in plan], "joined_on_discount": (rng.random(n) < .18).astype(int),
        "past_cancellations": rng.poisson(np.where(tenure > 180, .4, .15)), "status": "active", "cancelled_at": None,
    })
    carrier = ~np.isin(channel, ["Wallet", "Card"])
    traits = pd.DataFrame({
        "customer_id": ids,
        "base_minutes": rng.gamma(2.2, 140, n),                                  # weekly minutes when engaged
        "trend": np.clip(rng.normal(0, .18, n), -.7, .5),                         # change over 8 weeks
        "fragility": np.clip(np.where(carrier, rng.beta(2, 9, n), rng.beta(1.2, 18, n)), 0, .8),   # renewal failure chance
        "quality_issue": rng.beta(1.5, 8, n) + np.where(network == "3G", .25, 0) + np.where(device == "Android", .05, 0),
        "completion": rng.beta(4, 3, n), "live_pref": np.where(np.isin(genre, ["Sports", "News"]), rng.beta(5, 2, n), rng.beta(1.2, 6, n)),
        "concentration": rng.beta(5, 2.5, n), "open_prob": rng.beta(2, 3, n), "temper": rng.beta(2, 5, n),
        "next_renewal_at": [ts(now + timedelta(hours=int(rng.integers(1, 24 * RENEW_EVERY[p])))) for p in plan],
        "failed_streak": 0,
    })
    return cust, traits


def history(cust, traits, now, rng):
    sess, bill, app, tick, offers, recs, changes = [], [], [], [], [], [], []
    for c, t in zip(cust.itertuples(), traits.itertuples()):
        inactive_days = int(min(30, rng.exponential(3.0)))
        start_of_life = datetime.strptime(c.signup_date, "%Y-%m-%d %H:%M:%S")
        for w in range(WEEKS):                                                     # w = 0 oldest week
            week_start = now - timedelta(days=7 * (WEEKS - w))
            if week_start < start_of_life - timedelta(days=7):
                continue
            minutes = max(0.0, t.base_minutes * (1 + t.trend * (w - WEEKS + 1) / WEEKS) * rng.normal(1, .25))
            if w == WEEKS - 1 and rng.random() < .25:
                minutes *= rng.uniform(.2, .7)                                     # a recent drop for some people
            k = rng.poisson(minutes / 45 + .3)
            for _ in range(k):
                when = week_start + timedelta(minutes=int(rng.integers(0, 7 * 24 * 60)))
                last_ok = now - timedelta(days=inactive_days)
                if when > last_ok:                               # inactive lately: this session happened earlier
                    span = (last_ok - max(week_start, last_ok - timedelta(days=7))).total_seconds()
                    when = last_ok - timedelta(seconds=float(rng.uniform(0, max(span, 3600))))
                if when < start_of_life:
                    continue
                g = c.favourite_genre if rng.random() < t.concentration else rng.choice(GENRES)
                sess.append((c.customer_id, ts(when), round(minutes / max(k, 1) * rng.uniform(.5, 1.5), 1), g,
                             int(rng.random() < t.live_pref), int(rng.random() < t.completion),
                             round(float(np.clip(rng.gamma(2, 1.0) + 2 * (c.network == "3G"), .3, 15)), 1), int(rng.poisson(t.quality_issue * 1.4))))
        every = RENEW_EVERY[c.plan]
        d = 1
        while d <= 90:
            when = now - timedelta(days=d)
            if when < start_of_life:
                break
            if rng.random() < fail_chance(t.fragility, c.plan):
                bill.append((c.customer_id, ts(when), "renewal_failed", c.monthly_price_pkr))
                if c.payment_channel.startswith("Operator") and rng.random() < .7:
                    bill.append((c.customer_id, ts(when), "low_balance", 0))
            else:
                bill.append((c.customer_id, ts(when), "renewal_success", round(c.monthly_price_pkr * every / 30)))
            d += every
        if c.payment_channel.startswith("Operator"):
            for _ in range(rng.poisson(9)):
                bill.append((c.customer_id, ts(now - timedelta(minutes=int(rng.integers(0, 90 * 1440)))), "recharge", int(rng.choice([100, 200, 500]))))
        for _ in range(rng.poisson(.15)):
            bill.append((c.customer_id, ts(now - timedelta(minutes=int(rng.integers(0, 90 * 1440)))), "method_switch", 0))
        for _ in range(rng.poisson(t.quality_issue * 1.2)):
            app.append((c.customer_id, ts(now - timedelta(minutes=int(rng.integers(0, 7 * 1440)))), "crash"))
        for _ in range(rng.poisson(.2)):
            app.append((c.customer_id, ts(now - timedelta(minutes=int(rng.integers(0, 30 * 1440)))), "login_failure"))
        for _ in range(rng.poisson(.3 + t.fragility + t.quality_issue * .5)):
            # quick-tempered customers write angrier tickets
            sentiment = "negative" if rng.random() < .25 + t.temper * .8 else ("neutral" if rng.random() < .75 else "positive")
            tick.append((c.customer_id, ts(now - timedelta(minutes=int(rng.integers(0, 30 * 1440)))), sentiment, int(rng.random() < .65)))
        for _ in range(rng.poisson(2.5)):
            offers.append((c.customer_id, ts(now - timedelta(minutes=int(rng.integers(0, 90 * 1440)))), int(rng.random() < t.open_prob)))
        for _ in range(rng.poisson(4)):
            recs.append((c.customer_id, ts(now - timedelta(minutes=int(rng.integers(0, 30 * 1440)))), int(rng.random() < .4)))
        if rng.random() < .07:
            changes.append((c.customer_id, ts(now - timedelta(minutes=int(rng.integers(0, 90 * 1440)))), "downgrade"))
    return sess, bill, app, tick, offers, recs, changes


SCHEMA = """
CREATE TABLE platform_clock (now TEXT NOT NULL);
CREATE TABLE customers (customer_id TEXT PRIMARY KEY, signup_date TEXT, city TEXT, device TEXT, network TEXT, signup_source TEXT,
  favourite_genre TEXT, payment_channel TEXT, plan TEXT, monthly_price_pkr INTEGER, joined_on_discount INTEGER,
  past_cancellations INTEGER, status TEXT, cancelled_at TEXT);
CREATE TABLE viewing_sessions (id INTEGER PRIMARY KEY, customer_id TEXT, started_at TEXT, minutes REAL, genre TEXT,
  is_live INTEGER, completed INTEGER, start_time_sec REAL, buffering_events INTEGER);
CREATE TABLE billing_events (id INTEGER PRIMARY KEY, customer_id TEXT, ts TEXT, event TEXT, amount_pkr INTEGER);
CREATE TABLE app_events (id INTEGER PRIMARY KEY, customer_id TEXT, ts TEXT, event TEXT);
CREATE TABLE support_tickets (id INTEGER PRIMARY KEY, customer_id TEXT, opened_at TEXT, sentiment TEXT, resolved INTEGER);
CREATE TABLE marketing_offers (id INTEGER PRIMARY KEY, customer_id TEXT, sent_at TEXT, opened INTEGER);
CREATE TABLE recommendations (id INTEGER PRIMARY KEY, customer_id TEXT, shown_at TEXT, clicked INTEGER);
CREATE TABLE plan_changes (id INTEGER PRIMARY KEY, customer_id TEXT, ts TEXT, kind TEXT);
CREATE TABLE content_releases (genre TEXT PRIMARY KEY, ended_title TEXT, ended_at TEXT, next_title TEXT, next_release_at TEXT);
CREATE INDEX ix_vs ON viewing_sessions(started_at); CREATE INDEX ix_be ON billing_events(ts); CREATE INDEX ix_ae ON app_events(ts);
CREATE INDEX ix_st ON support_tickets(opened_at); CREATE INDEX ix_mo ON marketing_offers(sent_at); CREATE INDEX ix_rc ON recommendations(shown_at);
"""

if __name__ == "__main__":
    if DB.exists():
        DB.unlink()
    con = sqlite3.connect(DB)
    con.executescript(SCHEMA)
    print(f"Creating {N:,} customers with {WEEKS} weeks of history (this takes a minute)...")
    cust, traits = make_customers(N, 1, NOW, rng)
    sess, bill, app, tick, offers, recs, changes = history(cust, traits, NOW, rng)
    cust.to_sql("customers", con, if_exists="append", index=False)
    traits.to_sql("_sim_traits", con, if_exists="replace", index=False)
    con.executemany("INSERT INTO viewing_sessions(customer_id,started_at,minutes,genre,is_live,completed,start_time_sec,buffering_events) VALUES (?,?,?,?,?,?,?,?)", sess)
    con.executemany("INSERT INTO billing_events(customer_id,ts,event,amount_pkr) VALUES (?,?,?,?)", bill)
    con.executemany("INSERT INTO app_events(customer_id,ts,event) VALUES (?,?,?)", app)
    con.executemany("INSERT INTO support_tickets(customer_id,opened_at,sentiment,resolved) VALUES (?,?,?,?)", tick)
    con.executemany("INSERT INTO marketing_offers(customer_id,sent_at,opened) VALUES (?,?,?)", offers)
    con.executemany("INSERT INTO recommendations(customer_id,shown_at,clicked) VALUES (?,?,?)", recs)
    con.executemany("INSERT INTO plan_changes(customer_id,ts,kind) VALUES (?,?,?)", changes)
    rel = [("Sports", "T20 International Series", -3, "National Cup", 24), ("Drama", "Prime-time serial: season finale", -6, "New prime-time serial", 5),
           ("Movies", "Eid movie festival", -10, "Weekly new movie", 2), ("Kids", "Animated series season", -12, "New animated season", 18),
           ("News", "Continuous coverage", 0, "Continuous coverage", 0)]
    con.executemany("INSERT INTO content_releases VALUES (?,?,?,?,?)",
                    [(g, e, ts(NOW + timedelta(days=a)), n, ts(NOW + timedelta(days=b))) for g, e, a, n, b in rel])
    con.execute("INSERT INTO platform_clock VALUES (?)", (ts(NOW),))
    con.commit()
    for t in ["customers", "viewing_sessions", "billing_events", "app_events", "support_tickets", "marketing_offers", "recommendations", "plan_changes"]:
        print(f"  {t:18s} {con.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]:>9,} rows")
    con.close()
    print(f"Saved {DB}")
