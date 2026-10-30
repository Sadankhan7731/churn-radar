# Churn Radar

A weekly churn early-warning tool for the retention team of a subscription streaming business.
Built for **KSBL DATA722 – Generative AI & Strategic Forecasting, Phase 2**. This is Use Case A from the Phase 1 assessment (verdict: *Go, build as scoped*).

> **All subscriber data in this project is synthetic.** No real customer data is used anywhere, as required by the Phase 1 data finding (row 6b).

## What it does

1. **Scores** 100,000 synthetic subscribers on their chance of cancelling in the next 30 days, from 39 signals: viewing, content timing (a release calendar), payment, app experience, plan history, marketing response and support sentiment.
2. **Explains** each score with its top 3 reasons, each tied to a real number, and groups subscribers into six rule-based personas.
3. **Writes** a plain-English weekly memo for the retention team with an LLM (Groq, `gpt-oss-120b`), using only 17 aggregated facts, including who is waiting for which release.
4. **Checks** the note twice: a code check (every sentence cites a real fact, every number is in that fact) and an AI judge from a different model family (`qwen3.8-27b`) that checks meaning.
5. **Repairs** the note once if anything is flagged.
6. **Simulates** retention campaigns: who to contact, at what discount, and whether it pays off.

The model **recommends**; a person decides who gets an offer. Nothing is sent to subscribers.

## Bring your own data (SaaS mode)

Churn Radar also works on other companies' data, without breaking the Phase 1 data rule:

* **Data sources:** upload CSV or Excel, paste a Google Sheets/CSV link, load the sample, or export from SQL Server with the provided query (`public/samples/sqlserver_query.sql`). Columns are matched to the 40 signals automatically and can be corrected.
* **Scored in the browser:** Step 6 exports the logistic-regression formula to `public/model/churn_model.json`; `public/engine.js` scores every customer on the user's device (verified to match Python to 6 decimals). Customer rows are never uploaded.
* **Ask Churn Radar:** an AI assistant (`api/chat.py`) answers questions from aggregate facts only; every answer goes through the same number check and AI judge as the weekly briefing.
* **What-if simulator:** switch on operational fixes (payments, video start, buffering, support, release timing, re-engagement, plan migration), size a campaign (with +/-500 steps), and set a goal ("keep 500 more customers"); the model re-scores every customer (a representative 20,000-customer sample for the demo base, or all uploaded rows) and reports cancellations avoided, revenue gained, cost, ROI and the audience needed. Scenarios can be saved and compared.
* **Live database:** `connector/` contains a realistic OTT database (customers, viewing sessions, billing events, app events, tickets, offers, recommendations, release calendar), a simulator that keeps writing events, and the Churn Radar Connector agent that turns raw tables into signals inside the company network. The app connects to it, syncs on demand or every 30 s / 1 min / 5 min, and shows what changed. See `connector/README.md`.
* **Learning loop:** with the live database connected, Model health shows the live model's accuracy on real outcomes, drift per signal, and a retrained challenger compared with the live model on recent customers. A person approves the switch (or auto-promote is turned on), and the browser then scores with the promoted model.
* **Data format guide:** the Data sources page lists every column (type, example, required/recommended) and the database tables the connector reads.
* **Plans:** illustrative Starter / Growth / Enterprise tiers. Direct database connectors are on the Enterprise roadmap because a public website should never hold database credentials.

## Results (held-out test set, 30,000 subscribers)

| Metric | Phase 1 target | Result |
|---|---|---|
| AUC | ≥ 0.75 | 0.772 (met) |
| Precision in top 10% | ≥ 40% | 32.8% (missed) |
| Calibration in top band | within 5 pts | 32% predicted vs 33% actual (met) |
| Unsupported claims in AI memo | < 2% | measured over 5 live runs in the notebook |
| Planted errors caught (control test) | — | 5 of 5 with both checks |

A perfect model that knows the true rules only reaches 38.2% top-10% precision on this data, so the 40% target was not reachable. Version 1 of this project (20,000 subscribers, 18 signals; tag `v1-backup`) reached AUC 0.743; the notebook compares the two.

## Project layout

```
src/step1_generate_data.py       100k synthetic subscribers, release calendar, hidden true rules
src/step2_train_and_evaluate.py  two models, held-out test, Phase 1 targets, ceiling
src/step4_explain_and_segment.py reason codes, personas, content view, segments, simulator data
src/step5_weekly_note.py         AI note, number check, AI judge, trap test
src/serve.py                     run the dashboard locally
src/build_notebook.py            builds Churn_Radar_Notebook.ipynb (the working record)
src/step6_export_for_browser.py  exports the model formula and sample files for in-browser scoring
api/chat.py                      Vercel function behind the AI assistant
public/engine.js                 in-browser parsing, column mapping, scoring and summaries
public/sim.js                    what-if scenarios: levers, campaign, goal seek
api/_note_engine.py              shared note engine (local + live site)
api/weekly_note.py               Vercel function behind "Regenerate live"
public/                          the dashboard (HTML, CSS, JS, data)
```

## Run it yourself

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
cp .env.example .env            # then paste your Groq key into .env
.venv/bin/python src/step1_generate_data.py
.venv/bin/python src/step2_train_and_evaluate.py
.venv/bin/python src/step4_explain_and_segment.py
.venv/bin/python src/step5_weekly_note.py
.venv/bin/python src/step6_export_for_browser.py
.venv/bin/python src/serve.py   # open http://localhost:8000
```

On Vercel, set `GROQ_API_KEY` under Project → Settings → Environment Variables. The key is never stored in the code.
