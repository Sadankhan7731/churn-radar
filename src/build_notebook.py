"""
Builds Churn_Radar_Notebook.ipynb from the cells below.
Writing the notebook as code keeps it reproducible: change a cell here, rebuild, re-run.

  .venv/bin/python src/build_notebook.py
  .venv/bin/jupyter nbconvert --to notebook --execute --inplace Churn_Radar_Notebook.ipynb
"""
import nbformat as nbf

cells = []
md = lambda s: cells.append(nbf.v4.new_markdown_cell(s.strip()))
code = lambda s: cells.append(nbf.v4.new_code_cell(s.strip()))

# ---------------------------------------------------------------------------
md("""
# Churn Radar: Phase 2 Notebook
**Sadan Khan · KSBL DATA722 Generative AI & Strategic Forecasting**

Live application: **https://churn-radar-rosy.vercel.app** · Code: **https://github.com/Sadankhan7731/churn-radar**

This notebook is the working record of Phase 2. It builds **Use Case A** from my Phase 1 assessment (churn prediction with a plain-English weekly summary for the retention team, verdict *Go, build as scoped*) and tests it against the targets I fixed in Phase 1, before building.

| Section | What it covers | Brief requirement |
|---|---|---|
| 1 | Synthetic data | Phase 1 rule: no real customer data |
| 2 | Churn model and its evaluation | Evaluation against Phase 1 targets |
| 3 | The LLM core: facts packet, prompts, judge, repair loop | Prompts, context design, agent loop |
| 4 | Evaluating the AI memorandum | Evaluation with scores |
| 5 | Development log: what failed and what I changed | At least one failure |
| 6 | Tokens and cost | Cost of a representative run |
| 7 | Honesty section | What it gets wrong, what I would not ship, what it costs |

> All subscriber data in this notebook is **synthetic**. No real customer record is used anywhere.
""")

code("""
import json, sys, time, warnings, runpy, io, contextlib
import pandas as pd, numpy as np
import matplotlib.pyplot as plt
from IPython.display import Image, display, Markdown
warnings.filterwarnings("ignore")
pd.set_option("display.max_colwidth", 120)
sys.path.insert(0, "api")
import _note_engine as engine
print("Writer model:", engine.MODEL, "| Judge model:", engine.JUDGE_MODEL,
      "| API key configured:", bool(engine.load_key()))
""")

# ---------------------------------------------------------------------------
md("""
## 1. Synthetic data

**Why synthetic?** In Phase 1 (row 6b) I wrote that raw subscriber data must stay inside the company. A public demo must therefore run on fake data, but data that *behaves* like the real thing.

**How:** I generate 20,000 subscribers with the same kinds of columns we hold at work (plan, payment channel, watch time, failed renewals, support tickets, buffering). Then I decide the **true rules** of who cancels, for example watching less, failed renewals and short tenure, and add random noise because real behaviour is messy.

Because I know the true rules, I can later check whether the model **rediscovers** them. With real data that check is impossible.
""")
code("""
with contextlib.redirect_stdout(io.StringIO()) as out:
    runpy.run_path("src/step1_generate_data.py", run_name="__main__")
print(out.getvalue().split("First 3 rows")[0])
df = pd.read_csv("data/subscribers.csv")
df.head()
""")
md("""
**Reading the output.** The synthetic base matches the Phase 1 assumptions: about 9% monthly churn and average revenue near PKR 290. The churn rate rises steeply with failed renewals, as it does in carrier billing, where a low prepaid balance makes renewals fail.
""")

# ---------------------------------------------------------------------------
md("""
## 2. The churn model and its evaluation

**Method.** I hide 30% of subscribers (6,000) as a test set the model never sees, train on the other 70%, then compare predictions with what really happened.

I train **two** models:
* **Logistic regression:** simple, explainable, the baseline.
* **Gradient boosting:** more powerful, can find non-linear patterns.

**Decision rule, set before seeing results:** use gradient boosting only if it improves AUC by at least 0.01. Otherwise keep the simpler model, because the retention team needs to understand *why* someone is flagged.

**Phase 1 targets (rows 7 and 7a):** AUC ≥ 0.75; precision in the top 10% ≥ 40%; and in the high-risk band, predicted churn within 5 points of actual churn (the "confidently wrong" check).
""")
code("""
with contextlib.redirect_stdout(io.StringIO()) as out:
    runpy.run_path("src/step2_train_and_evaluate.py", run_name="__main__")
print(out.getvalue())
""")
code("""
m = json.load(open("outputs/model_metrics.json"))
rows = {name: {k: r[k] for k in ["auc", "precision_top10", "recall_top10", "lift_top10", "brier"]}
        for name, r in m["results"].items()}
rows["Perfect model (knows the true rules)"] = m["ceiling"]
table = pd.DataFrame(rows).T
table.columns = ["AUC", "Precision top 10%", "Recall top 10%", "Lift top 10%", "Brier score"]
table.style.format({"AUC": "{:.3f}", "Precision top 10%": "{:.1%}", "Recall top 10%": "{:.1%}",
                    "Lift top 10%": "{:.2f}x", "Brier score": "{:.4f}"})
""")
code("""
display(Image("outputs/calibration.png", width=480))
""")
md("""
**What the results mean.**
* Gradient boosting was **not** better (AUC 0.734 vs 0.743), so the simpler logistic regression is used.
* **Two of three Phase 1 targets were missed:** AUC 0.743 (target 0.75) and top-10% precision 27.7% (target 40%).
* **Calibration passed.** In the highest-risk band the model predicts about 31% churn and 28% actually churn, and every point sits close to the diagonal. The model is **not confidently wrong**, which was my main safety concern in Phase 1.
* **The ceiling check.** A *perfect* model that knows the exact true rules reaches only AUC 0.783 and 34.8% precision. So **the 40% target was not reachable on this data by any model**, and ours reaches about **95% of the attainable AUC**. The target was too ambitious for a 9% base rate with noisy behaviour. I kept the honest result rather than making the synthetic data cleaner to pass the target.
* **Business value anyway:** contacting the top 10% reaches **3 times** more real leavers than contacting people at random.
""")
md("""
### Did the model learn the real rules?
""")
code("""
with contextlib.redirect_stdout(io.StringIO()) as out:
    runpy.run_path("src/step4_explain_and_segment.py", run_name="__main__")
d = json.load(open("public/data/dashboard.json"))
pd.DataFrame(d["rule_check"])
""")
md("""
All eight true rules were recovered with the correct direction. The model was never told them. This is the strongest evidence that it learns real patterns rather than noise.

Step 4 also turns each score into **three plain-English reasons** (for example "Inactive for 23 days") by multiplying each coefficient by how far the subscriber is from average. A reason is only shown if it is actually true for that person. That rule is reused later by the hallucination check.
""")
code("""
w = d["watchlist"][0]
print(f"Riskiest subscriber {w['id']}: {w['score']:.0%} chance of cancelling, {w['plan']} via {w['channel']}")
for r in w["reasons"]:
    print("  -", r["text"])
""")

# ---------------------------------------------------------------------------
md("""
## 3. The LLM core: context design, prompts, judge and repair loop

This is the centre of the system. A single run does the following:

```
dashboard numbers ──► 13 numbered FACTS (aggregates only) ──► privacy check
        ──► WRITER (gpt-oss-120b) drafts memo, must cite a fact per sentence
        ──► NUMBER CHECK (code): citation exists? every number in the cited fact?
        ──► JUDGE (qwen3.8-27b, different model family): is the MEANING faithful?
        ──► if anything flagged: REPAIR once, with the exact problems and which facts to cite
        ──► memo + audit trail shown to the retention team, who decide
```

### 3.1 Context design: the facts packet
The model never sees subscriber rows. It sees only these numbered facts, which are totals and shares. This enforces Phase 1 row 6b in code: Groq's servers are outside Pakistan, which is acceptable only because nothing identifying is sent.
""")
code("""
facts = engine.build_facts(d)
for f in facts:
    print(f"{f['id']:>4}  {f['text']}")
assert not engine.PRIVATE.search(json.dumps(facts)), "privacy check failed"
print("\\nPrivacy check: PASS, no subscriber IDs or phone numbers in the prompt")
""")
md("""
### 3.2 The writer prompt
Two design choices matter most:
1. **"Use only the numbered facts"** narrows what the model can talk about.
2. **"End every sentence with the fact ids"** makes every claim *checkable*. Without citations, verification would be guesswork.
""")
code("""
print(engine.SYSTEM)
""")
md("""
### 3.3 The judge prompt (second AI pass)
The number check can't see meaning. During development the writer produced *"39% of the high-risk group **missed** the sports series"*. The fact says the series **ended**. The number is right but the meaning is wrong, so a second model reads each sentence next to its facts. I use a **different model family** so the two models are less likely to share blind spots.
""")
code("""
print(engine.JUDGE_SYSTEM)
""")
md("""
### 3.4 The repair loop
If either check flags a sentence, the writer is shown its draft and the list of problems, and gets **one** chance to rewrite. When a citation is missing, the checker works out which facts the numbers came from and tells the writer exactly which ids to add (see failure 5 in Section 5). One retry keeps cost and latency bounded. If problems remain, the memo is shown **with the flag**, not hidden.
""")
code("""
import inspect
print(inspect.getsource(engine.run_pipeline))
""")

# ---------------------------------------------------------------------------
md("""
## 4. Evaluating the AI memorandum

Phase 1 metric (row 7a): **unsupported-claim rate below 2%.** I measure it in two ways:
* **A. Five live runs** of the full pipeline. Every sentence is counted after both checks.
* **B. A control test:** five planted false statements, each a different kind of error. A checker that catches nothing proves nothing.
""")
code("""
key = engine.load_key()
runs = []
for i in range(5):
    note, _ = engine.run_pipeline(d, key)
    v = note["verification"]
    runs.append({"run": i + 1, "drafts": len(note.get("attempts", [1])),
                 "statements": v["total"],
                 "flagged_after_draft_1": note["attempts"][0]["flagged"] if note.get("attempts") else None,
                 "flagged_final": v.get("flagged_final", v["flagged"]),
                 "judge": v.get("judge_meta", {}).get("model", "unavailable"),
                 "cost_usd": note["meta"]["total_cost_usd"], "_note": note})
    time.sleep(25)          # stay inside Groq's free-tier tokens-per-minute limit
runs_df = pd.DataFrame(runs).drop(columns="_note")
total = runs_df.statements.sum()
print(f"Statements checked: {total}")
first = runs_df.flagged_after_draft_1.sum()
print(f"Flagged on first draft: {first}" + (" -> sent back to the writer by the repair loop" if first else " (no repair needed in these runs)"))
print(f"Unsupported after both checks and repair: {runs_df.flagged_final.sum()} "
      f"= {runs_df.flagged_final.sum() / total:.1%}  (target < 2%)")
runs_df
""")
code("""
example = runs[-1]["_note"]
display(Markdown("**Example memo (last run):** *" + example["headline"] + "*\\n\\n" +
                 "\\n\\n".join(example["paragraphs"]) + "\\n\\n**Actions:**\\n" +
                 "\\n".join("- " + a for a in example["actions"])))
""")
md("""
### B. Control test: planted errors
""")
code("""
trap = engine.judge_note(engine.verify_note(engine.TRAPS, facts), facts, key)
trap_df = pd.DataFrame([{"planted statement": s["sentence"],
                         "number check": "caught" if not s["ok"] else "missed",
                         "AI judge": s["judge"]["verdict"],
                         "caught overall": "yes" if not s["ok_final"] else "NO"} for s in trap["sentences"]])
trap_df
""")
md("""
**What this shows.** The number check alone catches **3 of 5**: the invented number, the leaked subscriber ID and the uncited claim. It cannot catch the two errors where the numbers are real but the **meaning** is wrong ("missed the sports series", and Operator 4 described as the *least* likely to cancel). The judge catches those. **Together they catch 5 of 5.** This is the evidence that the second AI pass earns its cost.
""")

# ---------------------------------------------------------------------------
md("""
## 5. Development log: what failed and what I did about it

These are real problems found while building, in the order they happened.

| # | What went wrong | How I found it | What I changed |
|---|---|---|---|
| 1 | **Missed two Phase 1 model targets.** | Evaluation on the held-out set (Section 2). | Measured the ceiling with a perfect model and showed the 40% target was unreachable. Kept the honest result instead of cleaning the data to pass. |
| 2 | **The verifier flagged my own demo memo.** It cited a fact (F15) that did not exist and "30 days" was not in the allowed numbers. | The verifier itself. | Fixed the citation, and changed the checker to read the allowed numbers directly from each fact's text. |
| 3 | **The planned model had been retired by Groq** (`llama-3.3-70b-versatile`, error 404). | First live call. | Listed the models available to the key and switched to `gpt-oss-120b`. The model name is now a setting, not hard-coded. |
| 4 | **Right number, wrong meaning:** "39% *missed* the sports series". | Reading the live output myself; the number check had passed it. | Added the second AI pass (judge). Tested two judges on planted errors: `gpt-oss-20b` caught 4/5, `qwen3.8-27b` caught 5/5, so I chose qwen. |
| 5 | **Free-tier limit:** the judge request was rejected (HTTP 429, max 1,000 output tokens per minute). | Live run crashed. | Capped judge output, added a retry with back-off, and a "judge unavailable" fallback so the page never breaks. |
| 6 | **The judge sometimes stopped early**, and unreached sentences were counted as unsupported. | Inspecting a run with 4 flags that all said "judge gave no verdict". | Labelled them "not reached" instead of "unsupported", shortened the judge's explanations, and raised its token budget. |
| 7 | **The writer kept omitting citations on long list sentences**, even after the repair step. | A live redraft on the deployed site stayed flagged after two drafts. | The repair message now names the exact facts to cite ("end the sentence with [F10, F11, F12]"). The next live runs were all repaired. |

Failure 2 can be reproduced directly:
""")
code("""
old_demo = {"paragraphs": ["About 1,835 subscribers are expected to cancel in the next 30 days (9% of the base). [F2]"],
            "actions": ["Call the high-risk group first. [F4, F15]"]}
for s in engine.verify_note(old_demo, facts)["sentences"]:
    print("OK     " if s["ok"] else "FLAGGED", s["sentence"], "->", s["problems"] or "")
""")
md("""
With today's checker the "30 days" sentence passes, because allowed numbers are now read from the fact text. The citation to the non-existent F15 is still caught, as it should be.
""")

# ---------------------------------------------------------------------------
md("""
## 6. Tokens and cost of a representative run
""")
code("""
rep = runs[0]["_note"]
meta, jm = rep["meta"], rep["verification"].get("judge_meta", {})
record = pd.DataFrame([
    {"step": "Writer (" + meta["model"] + ")", "input tokens": meta["input_tokens"],
     "output tokens": meta["output_tokens"], "cost USD": meta["cost_usd"], "seconds": meta["seconds"]},
    {"step": "Judge (" + jm.get("model", "-") + ")", "input tokens": jm.get("input_tokens", 0),
     "output tokens": jm.get("output_tokens", 0), "cost USD": jm.get("cost_usd", 0), "seconds": jm.get("seconds", 0)},
])
display(record)
avg = runs_df.cost_usd.mean()
print(f"Average cost per memo over 5 runs, including repairs: ${avg:.6f}  (about PKR {avg * 280:.2f})")
print(f"One memo a week for a year: ${avg * 52:.4f}")
print(f"Even regenerating 100 times a day for a month: ${avg * 100 * 30:.2f}")
""")
md("""
**Notes on cost.**
* Prices are Groq's published rates for `gpt-oss-120b` (USD 0.15 per million input tokens and 0.60 per million output tokens). I had no published rate for `qwen3.8-27b`, so I assumed the same rate; the dashboard marks it as an estimate.
* The LLM cost is negligible. The real costs of this system are **people's time** to act on the list and **the discounts** offered, which is why the dashboard includes the campaign simulator.
* A repaired memo costs about twice as much as a first-time pass, because both models run twice.
""")

# ---------------------------------------------------------------------------
md("""
## 7. Honesty section

### What the system gets wrong
* **It misses two of my own Phase 1 targets.** AUC is 0.743 (target 0.75) and top-10% precision is 27.7% (target 40%). About **seven in ten** people on the call list will *not* actually leave. A retention team using it must expect that, and offers must be cheap enough that contacting non-leavers is affordable.
* **The 40% target was a Phase 1 mistake.** I set it before checking what is achievable at a 9% base rate. Even a perfect model reaches 34.8% here.
* **Reasons are associations, not causes.** "Watch time down 41%" is a signal that travels with churn. It does not prove that more content would keep that person.
* **City and device effects are noise the model partly picked up.** The synthetic data never made city matter, yet some city coefficients are non-zero. I excluded them from the reasons shown, but they still slightly affect scores.
* **The checks are good but not perfect.** The number check cannot judge meaning. The judge is itself a language model and can be wrong or unavailable. Headlines are not cited, so they are not verified. In 5 live runs and 5 planted errors nothing slipped through, but that is a small sample.

### What I would not yet put in front of a customer
* **Nothing here goes to customers directly, by design.** The tool recommends; a person decides (Phase 1, row 9a).
* **I would not use the scores on real subscribers** until the model has been retrained and re-evaluated on real company data, inside the company, with the same held-out test and ceiling check.
* **I would not let the memo drive spending on its own.** The suggested actions are generic templates, and the simulator's save rate and uptake are assumptions, not measurements. A small A/B test with a holdout group is needed to measure them.

### What it cost to run
* **LLM:** under **USD 0.001 per memo** (about PKR 0.20) including the judge, about double when a repair is needed, so roughly **USD 0.04 a year** at one memo a week.
* **Hosting:** Vercel's free (Hobby) tier. **Groq:** free tier, with real rate limits (failure 5 above).
* **The real cost is the retention campaign itself.** With the default assumptions (top 10%, 30% save rate, 15% discount, 50% uptake), the simulator shows a net benefit of about PKR 20,000 a month, versus a loss if the same people were chosen at random.
""")

nb = nbf.v4.new_notebook()
nb["cells"] = cells
nb["metadata"]["kernelspec"] = {"name": "python3", "display_name": "Python 3", "language": "python"}
nbf.write(nb, "Churn_Radar_Notebook.ipynb")
print(f"Wrote Churn_Radar_Notebook.ipynb with {len(cells)} cells")
