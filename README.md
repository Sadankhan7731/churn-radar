# Churn Radar

A weekly churn early-warning tool for the retention team of a subscription streaming business.
Built for **KSBL DATA722 – Generative AI & Strategic Forecasting, Phase 2**. This is Use Case A from the Phase 1 assessment (verdict: *Go, build as scoped*).

> **All subscriber data in this project is synthetic.** No real customer data is used anywhere, as required by the Phase 1 data finding (row 6b).

## What it does

1. **Scores** 20,000 subscribers on their chance of cancelling in the next 30 days.
2. **Explains** each score with its top 3 reasons, each tied to a real number.
3. **Writes** a plain-English weekly note for the retention team with an LLM (Groq, `gpt-oss-120b`), using only 13 aggregated facts.
4. **Checks** the note twice: a code check (every sentence cites a real fact, every number is in that fact) and an AI judge from a different model family (`qwen3.8-27b`) that checks meaning.
5. **Repairs** the note once if anything is flagged.
6. **Simulates** retention campaigns: who to contact, at what discount, and whether it pays off.

The model **recommends**; a person decides who gets an offer. Nothing is sent to subscribers.

## Results (held-out test set, 6,000 subscribers)

| Metric | Phase 1 target | Result |
|---|---|---|
| AUC | ≥ 0.75 | 0.743 (miss) |
| Precision in top 10% | ≥ 40% | 27.7% (miss) |
| Calibration in top band | within 5 pts | 31% predicted vs 28% actual (pass) |
| Unsupported claims in AI note | < 2% | 0% after both checks (pass) |
| Planted errors caught (trap test) | — | 5 of 5 |

A perfect model that knows the true rules only reaches AUC 0.783 and 34.8% top-10% precision on this data, so the model is at 95% of the best possible and the 40% target was not reachable.

## Project layout

```
src/step1_generate_data.py       synthetic subscribers + the hidden true rules
src/step2_train_and_evaluate.py  two models, held-out test, Phase 1 targets, ceiling
src/step4_explain_and_segment.py reason codes, segments, revenue at risk, simulator data
src/step5_weekly_note.py         AI note, number check, AI judge, trap test
src/serve.py                     run the dashboard locally
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
.venv/bin/python src/serve.py   # open http://localhost:8000
```

On Vercel, set `GROQ_API_KEY` under Project → Settings → Environment Variables. The key is never stored in the code.
