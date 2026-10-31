"""
Builds Churn_Radar_Notebook.ipynb from the cells below.
Writing the notebook as code keeps it reproducible: change a cell here, rebuild, re-run.
Numbers quoted in the text are read from the outputs of Steps 1-5 at build time,
so the prose can never drift away from the results.

  .venv/bin/python src/build_notebook.py
  .venv/bin/jupyter nbconvert --to notebook --execute --inplace Churn_Radar_Notebook.ipynb
"""
import phase2_additions as A
import json

import nbformat as nbf

# ---- Results to quote in the text -------------------------------------------
M = json.load(open("outputs/model_metrics.json"))
D = json.load(open("public/data/dashboard.json"))
chosen = M["chosen_model"]
R = M["results"][chosen]
GB = M["results"]["Gradient boosting"]
C = M["ceiling"]
K = D["kpis"]
rules_ok = sum(r["matches"] for r in D["rule_check"])
missed_rules = [r["feature"] for r in D["rule_check"] if not r["matches"]]
top_reason = D["reason_summary"][0]
sports = next(c for c in D["content"] if c["genre"] == "Sports")
drama = next(c for c in D["content"] if c["genre"] == "Drama")
top_persona = max(D["personas"], key=lambda p: p["revenue_at_risk_pkr"])
w0 = D["watchlist"][0]


def sim(k=1, save=0.30, disc=0.15, take=0.50):
    ds = D["deciles"][:k]
    contacted = sum(x["subscribers"] for x in ds)
    leavers = sum(x["expected_churners"] for x in ds)
    rev = sum(x["avg_revenue"] * x["subscribers"] for x in ds) / contacted
    saved = leavers * save
    return saved * rev - (contacted - leavers + saved) * take * rev * disc


SIM_NET = sim()
pct = lambda x, d=1: f"{x * 100:.{d}f}%"
N_TEST = int(K["subscribers"] * 0.30)

cells = []
md = lambda s: cells.append(nbf.v4.new_markdown_cell(s.strip()))
code = lambda s: cells.append(nbf.v4.new_code_cell(s.strip()))

# ---------------------------------------------------------------------------
md(f"""
# Churn Radar: Phase 2 Notebook
**Sadan Khan · KSBL DATA722 Generative AI & Strategic Forecasting**

Live application: **https://churn-radar-rosy.vercel.app** · Code: **https://github.com/Sadankhan7731/churn-radar**

This notebook is the working record of Phase 2. It builds **Use Case A** from my Phase 1 assessment (churn prediction with a plain-English weekly summary for the retention team, verdict *Go, build as scoped*) and tests it against the targets I fixed in Phase 1, before building.

| Section | What it covers | Brief requirement |
|---|---|---|
| 1 | Synthetic data: {K['subscribers']:,} subscribers, {K['signals']} signals, a content release calendar | Phase 1 rule: no real customer data |
| 2 | Churn model and its evaluation, version 1 vs version 2 | Evaluation against Phase 1 targets |
| 3 | The LLM core: facts packet, prompts, judge, repair loop | Prompts, context design, agent loop |
| 4 | Evaluating the AI memorandum | Evaluation with scores |
| 5 | Development log: what failed and what I changed | At least one failure |
| 6 | Tokens and cost | Cost of a representative run |
{A.OUTLINE_ROWS}

> All subscriber data in this notebook is **synthetic**. No real customer record is used anywhere.
""")

code("""
import json, sys, time, warnings, runpy, io, contextlib
import pandas as pd, numpy as np
from IPython.display import Image, display, Markdown
warnings.filterwarnings("ignore")
pd.set_option("display.max_colwidth", 120)
pd.set_option("display.max_columns", 50)
sys.path.insert(0, "api")
import _note_engine as engine
print("Writer model:", engine.MODEL, "| Judge model:", engine.JUDGE_MODEL,
      "| API key configured:", bool(engine.load_key()))
""")

# ---------------------------------------------------------------------------
md(f"""
## 1. Synthetic data

**Why synthetic?** In Phase 1 (row 6b) I wrote that raw subscriber data must stay inside the company. A public demo must therefore run on fake data, but data that *behaves* like the real thing.

**How:** I generate **{K['subscribers']:,} subscribers** (a sample of the ~400,000 base described in Phase 1) with **{K['signals']} signals** in eight groups that a streaming company normally holds:

| Group | Examples |
|---|---|
| Profile | plan, payment channel, city, device, network, how they joined |
| Payment | failed renewals, low balance at renewal, recharges, payment-method switches |
| Viewing | this week vs last, 8-week trend, completion rate, variety, one-category viewing, live vs on-demand |
| Content | did the title they followed just end? days to the next release in their genre; catalogue match; ignored recommendations |
| Experience | buffering, app crashes, video start time, login failures |
| Plan history | downgrades, past cancellations |
| Marketing | offers received and opened, joined on a discount |
| Support | tickets, sentiment of the ticket, resolved or not |

A small **content release calendar** links the genres to real-world timing: for example, the T20 series has just ended and the next sports event is {sports['next_release_in_days']} days away, while a new drama arrives in {drama['next_release_in_days']} days.

Then I decide the **true rules** of who cancels (with some thresholds and interactions, as in real life) and add random noise. Because I know the true rules, I can later check whether the model **rediscovers** them. With real data that check is impossible.
""")
code("""
with contextlib.redirect_stdout(io.StringIO()) as out:
    runpy.run_path("src/step1_generate_data.py", run_name="__main__")
print(out.getvalue())
df = pd.read_csv("data/subscribers.csv.gz")
df.head(3).T
""")
md("""
**Reading the output.** The base matches the Phase 1 assumptions: about 9% monthly churn and average revenue near PKR 290. The sanity checks show the rules behaving as intended: fans whose title ended and who must wait 18+ days churn at roughly twice the rate of those whose next release is within a week.
""")

# ---------------------------------------------------------------------------
md(f"""
## 2. The churn model and its evaluation

**Method.** I hide 30% of subscribers ({N_TEST:,}) as a test set the model never sees, train on the other 70%, then compare predictions with what really happened.

I train **two** models:
* **Logistic regression:** simple, explainable, the baseline.
* **Gradient boosting:** more powerful, can find non-linear patterns such as thresholds.

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
md(f"""
**What the results mean.**
* Gradient boosting improved AUC by only {GB['auc'] - R['auc']:.3f} ({GB['auc']} vs {R['auc']}), below the 0.01 rule, so the simpler logistic regression is used.
* **AUC target met:** {R['auc']} against 0.75.
* **Calibration target met.** In the highest-risk band the model predicts {pct(R['top_band_predicted'], 0)} churn and {pct(R['top_band_actual'], 0)} actually churn; every point sits on the diagonal. The model is **not confidently wrong**, my main safety concern in Phase 1.
* **Top-decile precision target missed:** {pct(R['precision_top10'])} against 40%. The **ceiling check** shows why: a *perfect* model that knows the true rules reaches only {pct(C['precision_top10'])}. **No model could reach 40% on this data**; ours reaches {R['auc'] / C['auc']:.0%} of the attainable AUC. I kept the honest result rather than making the data cleaner to pass.
* **Business value:** contacting the top 10% reaches **{R['lift_top10']:.1f} times** more real leavers than contacting people at random.

### Version 1 vs version 2: what the extra signals bought

My first build used 20,000 subscribers and 18 signals. After discussing what else predicts churn in streaming (content timing, payment behaviour, experience quality, offer response, ticket sentiment), I rebuilt the data with {K['signals']} signals and {K['subscribers']:,} subscribers.

| | Version 1 | Version 2 |
|---|---|---|
| Subscribers / signals | 20,000 / 18 | {K['subscribers']:,} / {K['signals']} |
| AUC (target ≥ 0.75) | 0.743, missed | **{R['auc']}, met** |
| Top-10% precision (target ≥ 40%) | 27.7%, missed | {pct(R['precision_top10'])}, missed |
| Lift in top 10% | 3.0× | {R['lift_top10']:.1f}× |
| Perfect-model ceiling (precision) | 34.8% | {pct(C['precision_top10'])} |

**Caveat:** in synthetic data I also wrote the rules for the new signals, so this table shows that the *method* uses richer signals well, not that these signals predict churn at my company. That must be measured on real data.
""")
md("""
### Did the model learn the real rules? And what does it say about each person?
""")
code("""
with contextlib.redirect_stdout(io.StringIO()) as out:
    runpy.run_path("src/step4_explain_and_segment.py", run_name="__main__")
d = json.load(open("public/data/dashboard.json"))
rc = pd.DataFrame(d["rule_check"])
print(f"True rules recovered: {rc.matches.sum()} of {len(rc)}")
rc
""")
md(f"""
**{rules_ok} of {len(D['rule_check'])} true rules** were recovered with the correct direction, without the model being told them. The one it missed, **{', '.join(missed_rules) or 'none'}**, is a textbook case of **collinearity**: tickets travel together with negative sentiment and failed payments, so the model gives the credit to those. Prediction is unaffected, but it is a warning that a coefficient should not be read as a cause.

Step 4 turns each score into **three plain-English reasons** by multiplying each coefficient by how far the subscriber is from average; a reason is shown only if it is actually true for that person. It also places each subscriber in one of six **rule-based personas**, checked in order of urgency (fixable problems first), and joins the **release calendar** with risk.
""")
code("""
w = d["watchlist"][0]
print(f"Riskiest subscriber {w['id']}: {w['score']:.0%} chance of cancelling, {w['plan']} via {w['channel']}, persona: {w['persona']}")
for r in w["reasons"]:
    print(f"  - {r['text']}  ({r['group']})")
print()
display(pd.DataFrame(d["personas"]))
display(pd.DataFrame(d["content"])[["genre", "ended_title", "next_title", "next_release_in_days",
                                    "fans_whose_title_ended", "high_risk_waiting", "avg_risk_waiting"]])
""")
md(f"""
**Reading this.** The most common reason in the high-risk group is *{top_reason['label'].lower()}* ({pct(top_reason['share'], 0)}). The content view turns that into timing: {sports['high_risk_waiting']:,} high-risk sports fans must wait {sports['next_release_in_days']} days for the {sports['next_title']}, while drama fans, with a new serial in {drama['next_release_in_days']} days, are much safer. The persona with the most revenue at risk is **{top_persona['persona']}** (PKR {top_persona['revenue_at_risk_pkr']:,} a month), a problem that a billing fix, not a discount, would address.
""")

# ---------------------------------------------------------------------------
md("""
## 3. The LLM core: context design, prompts, judge and repair loop

This is the centre of the system. A single run does the following:

```
dashboard numbers ──► numbered FACTS (aggregates only, incl. content calendar and personas) ──► privacy check
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
print(f"\\n{len(facts)} facts. Privacy check: PASS, no subscriber IDs or phone numbers in the prompt")
""")
md("""
### 3.2 The writer prompt
Three design choices matter most:
1. **"Use only the numbered facts"** narrows what the model can talk about.
2. **"End every sentence with the fact ids"** makes every claim *checkable*. Without citations, verification would be guesswork.
3. **"Keep every label exactly as given"** was added after the judge caught the writer calling several unrelated reasons "content-related" (Section 5).
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
If either check flags a sentence, the writer is shown its draft and the list of problems, and gets **one** chance to rewrite. When a citation is missing, the checker works out which facts the numbers came from and tells the writer exactly which ids to add. One retry keeps cost and latency bounded. If problems remain, the memo is shown **with the flag**, not hidden.
""")
code("""
import inspect
print(inspect.getsource(engine.run_pipeline))
""")

# ---------------------------------------------------------------------------
md("""
## 4. Evaluating the AI memorandum

Phase 1 metric (row 7a): **unsupported-claim rate below 2%.** I measure it in two ways:
* **A. Five live runs** of the full pipeline. Every sentence is counted, on the first draft and after repair.
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
first, final = runs_df.flagged_after_draft_1.sum(), runs_df.flagged_final.sum()
print(f"Statements checked: {total}")
print(f"Unsupported on first draft: {first} = {first / total:.1%}"
      + (" -> sent back to the writer by the repair loop" if first else " (no repair needed in these runs)"))
print(f"Unsupported after both checks and repair: {final} = {final / total:.1%}  (target < 2%)")
for r in runs:
    for a in r["_note"].get("attempts", []):
        for p in a["problems"]:
            print(f"  run {r['run']}, draft {a['attempt']}: {p[:200]}")
runs_df
""")
code("""
example = runs[-1]["_note"]
display(Markdown("**Example memo (last run):** *" + example["headline"] + "*\\n\\n" +
                 "\\n\\n".join(example["paragraphs"]) + "\\n\\n**Actions:**\\n" +
                 "\\n".join("- " + a for a in example["actions"])))
""")
md("""
**Reading this.** The first-draft rate is the honest measure of the writer on its own; the final rate is what the retention team actually receives. Flags on the first draft are mostly *meaning* problems that the judge catches (for example, grouping reasons under the wrong category), which the repair loop then fixes. Any statement still flagged after repair is shown to the reader with its flag, not hidden.
""")
md("""
### B. Control test: planted errors
""")
code("""
trap = engine.judge_note(engine.verify_note(engine.make_traps(facts), facts), facts, key)
trap_df = pd.DataFrame([{"planted statement": s["sentence"],
                         "number check": "caught" if not s["ok"] else "missed",
                         "AI judge": s["judge"]["verdict"],
                         "caught overall": "yes" if not s["ok_final"] else "NO"} for s in trap["sentences"]])
trap_df
""")
md("""
**What this shows.** The number check alone catches the invented number, the leaked subscriber ID and the uncited claim. It cannot catch the two errors where the numbers are real but the **meaning** is wrong: fans who are *waiting* described as fans who *have cancelled*, and the riskiest payment channel described as the *least* risky. Only the judge catches those. This is the evidence that the second AI pass earns its cost.
""")

# ---------------------------------------------------------------------------
md(f"""
## 5. Development log: what failed and what I did about it

These are real problems found while building, in the order they happened.

| # | What went wrong | How I found it | What I changed |
|---|---|---|---|
| 1 | **Version 1 missed two Phase 1 model targets** (AUC 0.743, precision 27.7%). | Evaluation on the held-out set. | Measured the ceiling with a perfect model and showed the 40% target was unreachable. Kept the honest result instead of cleaning the data to pass. |
| 2 | **The verifier flagged my own demo memo.** It cited a fact that did not exist and "30 days" was not in the allowed numbers. | The verifier itself. | Fixed the citation, and changed the checker to read the allowed numbers directly from each fact's text. |
| 3 | **The planned model had been retired by Groq** (`llama-3.3-70b-versatile`, error 404). | First live call. | Listed the models available to the key and switched to `gpt-oss-120b`. The model name is now a setting, not hard-coded. |
| 4 | **Right number, wrong meaning:** "39% *missed* the sports series". | Reading the live output myself; the number check had passed it. | Added the second AI pass (judge). Tested two judges on planted errors: `gpt-oss-20b` caught 4/5, `qwen3.8-27b` caught 5/5, so I chose qwen. |
| 5 | **Free-tier limit:** the judge request was rejected (HTTP 429, max 1,000 output tokens per minute). | Live run crashed. | Capped judge output, added a retry with back-off, and a "judge unavailable" fallback so the page never breaks. |
| 6 | **The judge sometimes stopped early**, and unreached sentences were counted as unsupported. | A run with 4 flags that all said "judge gave no verdict". | Labelled them "not reached", shortened the judge's explanations, raised its token budget. |
| 7 | **The writer kept omitting citations on long list sentences**, even after repair. | A live redraft on the deployed site stayed flagged after two drafts. | The repair message now names the exact facts to cite ("end the sentence with [F10, F11, F12]"). |
| 8 | **The data was too thin.** The teacher's question "what else predicts behaviour?" exposed that version 1 ignored content timing, payment behaviour and experience. | Discussion of real streaming churn drivers. | Rebuilt the data: {K['subscribers']:,} subscribers, {K['signals']} signals, a release calendar. AUC rose from 0.743 to {R['auc']} and now meets the target. |
| 9 | **Personas contradicted reasons.** The riskiest subscriber was labelled a "seasonal live fan" although every reason was a payment problem. | Reading the top of the contact list. | Personas are now checked in order of urgency: payment and quality problems first, content and habits after. |
| 10 | **One true rule was not recovered** (support tickets). | The rule-recovery table. | Diagnosed as collinearity with ticket sentiment; documented rather than hidden, and flagged in the honesty section. |
| 11 | **New facts invited new distortions.** With category labels in the facts, the writer described several unrelated reasons as "content-related", and once described waiting fans as having cancelled. | The judge, on live runs. | Added a prompt rule to keep every label as given and never turn "at risk" into "cancelled"; the repair loop fixes the rest. |
| 12 | **The trap test pointed at fact numbers that moved** when new facts were added. | Reviewing the traps after adding facts. | Facts now carry names (keys) and the traps are built from those keys, so the test stays correct whatever the order. |
{A.DEVLOG_ROWS}

Failure 2 can be reproduced directly:
""")
code("""
old_demo = {"paragraphs": ["About 1,835 subscribers are expected to cancel in the next 30 days (9% of the base). [F2]"],
            "actions": ["Call the high-risk group first. [F4, F99]"]}
for s in engine.verify_note(old_demo, facts)["sentences"]:
    print("OK     " if s["ok"] else "FLAGGED", s["sentence"], "->", s["problems"] or "")
""")
md("""
The first sentence is flagged too, correctly: the old figure 1,835 came from version 1 and is not in today's facts. The citation to a non-existent fact (F99) is caught, as it should be.
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
* A repaired memo costs about twice as much as a first-time pass, because both models run twice.
* The LLM cost is negligible. The real costs of this system are **people's time** to act on the list and **the discounts** offered, which is why the dashboard includes the campaign simulator.
""")

# ---------------------------------------------------------------------------
md(A.SECTION_7)
md(f"""
## 8. Honesty section

### What the system gets wrong
* **It misses one of my own Phase 1 targets.** Top-10% precision is {pct(R['precision_top10'])} against 40%: about **two in three** people on the call list will *not* actually leave. Offers must be cheap enough that contacting non-leavers is affordable.
* **The 40% target was a Phase 1 mistake.** I set it before checking what is achievable at a 9% base rate. Even a perfect model reaches {pct(C['precision_top10'])} here.
* **Everything in the data is assumed.** I wrote the effect of every signal, including the release calendar. The model's improvement from version 1 to version 2 proves the method, not that these signals matter at my company.
* **Reasons are associations, not causes.** "Watch time down 41%" travels with churn; it does not prove that more content would keep that person. One true rule (support tickets) was not recovered because of collinearity, a reminder not to read coefficients as causes.
* **City and device effects are noise the model partly picked up.** They are excluded from the reasons shown but still slightly affect scores.
* **The checks are good but not perfect.** The number check cannot judge meaning; the judge is itself a language model and can be wrong or unavailable; headlines are not verified. The writer still produces meaning errors on some first drafts, which the repair loop must fix.

{A.HONESTY_WRONG}

### What I would not yet put in front of a customer
* **Nothing here goes to customers directly, by design.** The tool recommends; a person decides (Phase 1, row 9a).
* **I would not use the scores on real subscribers** until the model has been retrained and re-evaluated on real company data, inside the company, with the same held-out test and ceiling check.
* **I would not let the memo or the suggested actions drive spending on their own.** The actions are templates, and the simulator's save rate and uptake are assumptions. A small A/B test with a holdout group is needed, which would also provide the data for **uplift modelling** (who an offer actually changes) and **survival analysis** (when someone will leave), both future work.

{A.HONESTY_NOT_SHIP}

### What it cost to run
* **LLM:** under **USD 0.001** for a memo that passes first time (about PKR 0.20 to 0.30), roughly double when a repair is needed; a few cents a year at one memo a week.
* **Hosting:** Vercel's free (Hobby) tier. **Groq:** free tier, with real rate limits (failure 5).
* **The real cost is the retention campaign itself.** With the default assumptions (top 10%, 30% save rate, 15% discount, 50% uptake), the simulator shows a net benefit of about **PKR {SIM_NET:,.0f} a month**, versus a loss if the same number of people were chosen at random.
{A.HONESTY_COST}
{A.video_note(A.VIDEO_CHAT_MODEL)}
""")

nb = nbf.v4.new_notebook()
nb["cells"] = cells
nb["metadata"]["kernelspec"] = {"name": "python3", "display_name": "Python 3", "language": "python"}
nbf.write(nb, "Churn_Radar_Notebook.ipynb")
print(f"Wrote Churn_Radar_Notebook.ipynb with {len(cells)} cells")
print(f"Quoted: AUC {R['auc']}, precision {pct(R['precision_top10'])}, ceiling {pct(C['precision_top10'])}, "
      f"rules {rules_ok}/{len(D['rule_check'])}, simulator net PKR {SIM_NET:,.0f}")
