# Churn Radar Connector

Keeps Churn Radar in sync with a live database while **customer data stays inside your network**.

```
OTT platform ──writes events──► SQL Server (or the demo SQLite file)
                                       │  read-only SELECTs
                                       ▼
                          Churn Radar Connector (agent.py)   ← runs on your server
                                       │  40 signals per customer, over your network only
                                       ▼
                     Churn Radar in the browser: scores customers on the device,
                     sends only aggregate figures to the AI assistant
```

## Try the demo (three terminals)

```bash
.venv/bin/python connector/create_demo_db.py      # once: 10,000 customers, 8 weeks of history
.venv/bin/python connector/simulate_platform.py   # keeps writing live events (Ctrl+C to stop)
.venv/bin/python connector/agent.py               # serves http://localhost:8765
```

Then open Churn Radar → **Data sources** → **Live database** → **Connect**. Choose an auto-sync interval; the top bar shows *Live · synced Xs ago*, and each sync reports new customers, cancellations and the change in expected cancellations.

The simulator moves the platform clock 30 minutes every 2 seconds (`--tick` and `--step` change this), so a demo day passes in about 1.5 minutes: customers watch, renewals fail, tickets are raised, people sign up and cancel, and some customers start drifting away.

## Connect a real SQL Server

```bash
pip install pyodbc
export CONNECTOR_DSN="Driver={ODBC Driver 18 for SQL Server};Server=sql01;Database=ott;Trusted_Connection=yes;"
.venv/bin/python connector/agent.py
```

Use a read-only account. The agent reads these tables (rename them in `agent.py`, or expose views with these names):

| Table | Columns read |
|---|---|
| customers | customer_id, signup_date, plan, monthly_price_pkr, payment_channel, city, device, network, signup_source, favourite_genre, joined_on_discount, past_cancellations, status |
| viewing_sessions | customer_id, started_at, minutes, genre, is_live, completed, start_time_sec, buffering_events |
| billing_events | customer_id, ts, event (renewal_success, renewal_failed, low_balance, recharge, method_switch) |
| app_events | customer_id, ts, event (crash, login_failure) |
| support_tickets | customer_id, opened_at, sentiment, resolved |
| marketing_offers | customer_id, sent_at, opened |
| recommendations | customer_id, shown_at, clicked |
| plan_changes | customer_id, ts, kind |
| content_releases | genre, ended_title, ended_at, next_title, next_release_at |
| platform_clock | now (on SQL Server, replace with `GETDATE()`) |

## Endpoints

* `GET /health` – status, database type, active customers, platform time, activity since last sync
* `GET /signals.csv` – one row per active customer with the 40 signals (cached for 5 seconds)

The agent binds to `127.0.0.1` only. To serve other machines on your network, change the bind address and put it behind your usual internal TLS and access controls.
