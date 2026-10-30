"""
Simulate a live OTT platform writing events into the database, non-stop.

Every tick (default 2 seconds of real time) the platform clock moves forward 30 minutes, and:
  * customers watch (sessions with minutes, genre, live/on-demand, start time, buffering)
  * renewals fall due; some fail (low balance), and 3 failures in a row cancel the subscription
  * some customers cancel on their own; new customers sign up
  * the app crashes now and then, tickets are raised, offers and recommendations go out
  * a few customers start drifting away (their viewing trend turns down) - so risk keeps changing

Run:   .venv/bin/python connector/simulate_platform.py            (Ctrl+C to stop)
       .venv/bin/python connector/simulate_platform.py --tick 1 --step 60   (faster)
"""
import argparse
import sqlite3
import time
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

from create_demo_db import GENRES, PLANS, RENEW_EVERY, fail_chance, make_customers

DB = Path(__file__).with_name("lumen_play.db")
FMT = "%Y-%m-%d %H:%M:%S"
rng = np.random.default_rng()


def main(tick, step):
    con = sqlite3.connect(DB, timeout=30)
    con.execute("PRAGMA journal_mode=WAL")            # lets the connector read while we write
    next_id = con.execute("SELECT COUNT(*) FROM customers").fetchone()[0] + 1
    print(f"Lumen Play platform simulator: +{step} platform minutes every {tick}s. Ctrl+C to stop.\n")
    n_tick = 0
    while True:
        t0 = time.time()
        now = datetime.strptime(con.execute("SELECT now FROM platform_clock").fetchone()[0], FMT) + timedelta(minutes=step)
        stamp = lambda: (now - timedelta(minutes=int(rng.integers(0, step)))).strftime(FMT)
        con.execute("UPDATE platform_clock SET now = ?", (now.strftime(FMT),))
        rows = con.execute("""SELECT c.customer_id, c.plan, c.payment_channel, c.network, c.favourite_genre, c.monthly_price_pkr,
                                     t.base_minutes, t.trend, t.fragility, t.quality_issue, t.completion, t.live_pref, t.concentration,
                                     t.open_prob, t.temper, t.next_renewal_at, t.failed_streak
                              FROM customers c JOIN _sim_traits t USING (customer_id) WHERE c.status = 'active'""").fetchall()
        ids = np.array([r[0] for r in rows]); n = len(rows)
        base = np.array([r[6] for r in rows]); trend = np.array([r[7] for r in rows])
        weekly = np.clip(base * (1 + trend * .2), 0, None)
        counts = {"sessions": 0, "renewals": 0, "failed": 0, "signups": 0, "cancelled": 0, "tickets": 0, "crashes": 0}

        # --- viewing: each customer's chance of a session in this window
        p = np.clip(weekly / 45 / (7 * 24 * 60 / step), 0, .9)
        watchers = np.nonzero(rng.random(n) < p)[0]
        sess = []
        for i in watchers:
            r = rows[i]
            g = r[4] if rng.random() < r[12] else str(rng.choice(GENRES))
            sess.append((r[0], stamp(), round(float(rng.gamma(2, 22)), 1), g, int(rng.random() < r[11]), int(rng.random() < r[10]),
                         round(float(np.clip(rng.gamma(2, 1.0) + 2 * (r[3] == "3G"), .3, 15)), 1), int(rng.poisson(r[9] * .2))))
        con.executemany("INSERT INTO viewing_sessions(customer_id,started_at,minutes,genre,is_live,completed,start_time_sec,buffering_events) VALUES (?,?,?,?,?,?,?,?)", sess)
        counts["sessions"] = len(sess)

        # --- renewals that fall due
        due = [r for r in rows if r[15] <= now.strftime(FMT)]
        for r in due:
            counts["renewals"] += 1
            if rng.random() < fail_chance(r[8], r[1]):
                counts["failed"] += 1
                con.execute("INSERT INTO billing_events(customer_id,ts,event,amount_pkr) VALUES (?,?,?,?)", (r[0], stamp(), "renewal_failed", r[5]))
                if r[2].startswith("Operator"):
                    con.execute("INSERT INTO billing_events(customer_id,ts,event,amount_pkr) VALUES (?,?,?,0)", (r[0], stamp(), "low_balance"))
                streak = r[16] + 1
                if streak >= 3:                                             # involuntary churn
                    con.execute("UPDATE customers SET status='cancelled', cancelled_at=? WHERE customer_id=?", (now.strftime(FMT), r[0]))
                    counts["cancelled"] += 1
                con.execute("UPDATE _sim_traits SET failed_streak=?, next_renewal_at=? WHERE customer_id=?",
                            (streak, (now + timedelta(days=1)).strftime(FMT), r[0]))
            else:
                con.execute("INSERT INTO billing_events(customer_id,ts,event,amount_pkr) VALUES (?,?,?,?)",
                            (r[0], stamp(), "renewal_success", round(r[5] * RENEW_EVERY[r[1]] / 30)))
                con.execute("UPDATE _sim_traits SET failed_streak=0, next_renewal_at=? WHERE customer_id=?",
                            ((now + timedelta(days=RENEW_EVERY[r[1]])).strftime(FMT), r[0]))

        # --- voluntary cancellations: low engagement, falling trend, fragile and quick-tempered customers leave more
        hazard = .09 / (30 * 24 * 60 / step) * np.exp(-1.2 * (weekly / 300 - 1) - 2.0 * trend)
        for i in np.nonzero(rng.random(n) < hazard)[0]:
            con.execute("UPDATE customers SET status='cancelled', cancelled_at=? WHERE customer_id=? AND status='active'", (now.strftime(FMT), ids[i]))
            counts["cancelled"] += 1

        # --- new sign-ups (roughly replacing churn)
        k = rng.poisson(.11 * step / 30 * n / 10_000 * 3)
        if k:
            cust, traits = make_customers(k, next_id, now, rng)
            cust["signup_date"] = now.strftime(FMT); cust["past_cancellations"] = 0
            cust.to_sql("customers", con, if_exists="append", index=False)
            traits.to_sql("_sim_traits", con, if_exists="append", index=False)
            next_id += k; counts["signups"] = k

        # --- app events, tickets, offers, recommendations
        q = np.array([r[9] for r in rows]); temper = np.array([r[14] for r in rows])
        for i in np.nonzero(rng.random(n) < q * .006 * step / 30)[0]:
            con.execute("INSERT INTO app_events(customer_id,ts,event) VALUES (?,?,'crash')", (ids[i], stamp())); counts["crashes"] += 1
        for i in np.nonzero(rng.random(n) < (.0004 + q * .0006) * step / 30)[0]:
            sentiment = "negative" if rng.random() < .25 + temper[i] * .8 else ("neutral" if rng.random() < .75 else "positive")
            con.execute("INSERT INTO support_tickets(customer_id,opened_at,sentiment,resolved) VALUES (?,?,?,?)", (ids[i], stamp(), sentiment, int(rng.random() < .65)))
            counts["tickets"] += 1
        for i in np.nonzero(rng.random(n) < .0012 * step / 30)[0]:
            con.execute("INSERT INTO recommendations(customer_id,shown_at,clicked) VALUES (?,?,?)", (ids[i], stamp(), int(rng.random() < .4)))
        if now.hour == 10 and now.minute < step:                                        # daily marketing send at 10:00
            for i in rng.choice(n, size=max(1, n // 40), replace=False):
                con.execute("INSERT INTO marketing_offers(customer_id,sent_at,opened) VALUES (?,?,?)", (ids[i], stamp(), int(rng.random() < rows[i][13])))

        # --- behaviour drifts: a few customers start fading, a few recover
        for i in rng.choice(n, size=max(1, n // 2000), replace=False):
            con.execute("UPDATE _sim_traits SET trend = ? WHERE customer_id = ?", (float(np.clip(trend[i] + rng.normal(-.1, .15), -.8, .5)), ids[i]))

        n_tick += 1
        if n_tick % 50 == 0:                                                            # keep 100 days of history
            cutoff = (now - timedelta(days=100)).strftime(FMT)
            for tbl, col in [("viewing_sessions", "started_at"), ("billing_events", "ts"), ("app_events", "ts")]:
                con.execute(f"DELETE FROM {tbl} WHERE {col} < ?", (cutoff,))
        con.commit()
        print(f"{now:%a %d %b %H:%M}  active {n:,}  sessions +{counts['sessions']}  renewals {counts['renewals']} "
              f"(failed {counts['failed']})  sign-ups +{counts['signups']}  cancellations +{counts['cancelled']}  "
              f"tickets +{counts['tickets']}  crashes +{counts['crashes']}", flush=True)
        time.sleep(max(0, tick - (time.time() - t0)))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--tick", type=float, default=2, help="real seconds between writes")
    ap.add_argument("--step", type=int, default=30, help="platform minutes per tick")
    a = ap.parse_args()
    try:
        main(a.tick, a.step)
    except KeyboardInterrupt:
        print("\nSimulator stopped.")
