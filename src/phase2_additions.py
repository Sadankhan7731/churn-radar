"""
Notebook text for everything built after the first Phase 2 version: bring-your-own-data, the what-if
simulator, the assistant that operates it, the live database connector and the learning loop, plus the
failures found while building them. Used by build_notebook.py and by patch_notebook.py (which updates
the already-executed notebook without re-running the paid LLM evaluation).
"""

OUTLINE_ROWS = """| 7 | Added after the first build: own data, what-if simulator, assistant, live database, learning loop | Beyond the brief; how AI is used in each |
| 8 | Honesty section | What it gets wrong, what I would not ship, what it costs |"""

DEVLOG_ROWS = """| 13 | **The chat failed with "invalid JSON"** on the live site. | A user screenshot. | More room for the answer, one retry, rescue of partial replies, and a friendly error instead of a crash. |
| 14 | **The number check flagged correct figures** written as "2.76 million", and list numbers like "1." | Live chat answers. | The checker now understands scaled numbers (million, M, k) and ignores list numbering, with the same rule in the browser and on the server. |
| 15 | **The assistant did its own maths for what-if questions** ("if we achieve 5% of that?") and answered in prose. | A user test. | Gave it a scenario tool: the language model only chooses the levers; the browser computes the result with the churn model; the language model then explains the computed numbers. |
| 16 | **"Keep 1,000 more customers" was read as a total of 1,000.** | A user test. | Goals now carry a "more" flag. |
| 17 | **The confirmation after "apply it" hit the rate limit** (HTTP 502). | A user test. | The confirmation is now written by the app from what actually changed: no AI call, so it cannot misreport. |
| 18 | **Two copies of the demo platform simulator crashed** with duplicate customer IDs. | The error in my terminal. | IDs are read from the database at sign-up time, and a lock file allows only one simulator. |
| 19 | **The original model's real accuracy fell to AUC about 0.60** after a simulated market shift on the live database. | The learning loop's realised-accuracy check. | Retrain a challenger on the latest 30-day outcomes (AUC about 0.72 to 0.76 on customers it never saw); switch only after a person approves. |
| 20 | **The hosted site could not reach a local connector** in some browsers (public site to localhost is blocked). | Testing in a second browser. | Added an "allow local network" hint, and documented that the connector belongs inside the company network. |
| 21 | **Groq's daily token limit** (200,000 tokens a day for `gpt-oss-120b`) ran out while recording the video; every chat answer failed. | The recorder's own checks, then the server log (HTTP 429, tokens per day). | Paced the questions and retried; documented the limit (see the honesty section). |
| 22 | **`gpt-oss-20b` sometimes returned its JSON as a "tool call"**, which Groq rejects (HTTP 400). | Replaying the exact request the browser sent. | The JSON is recovered from the error itself; otherwise the call is retried. |
| 23 | **An explanation opened with a sentence that contradicted the computed options** ("the facts do not provide a clear answer"). | Frame-by-frame review of the video. | When explaining computed scenarios, sentences that fail verification are dropped; the option cards carry the model's numbers. |
| 24 | **Failed retries piled up error messages in the chat**, and auto-sync reloaded Model health every 30 seconds. | Video review. | "Try again" now replaces the failed exchange, and Model health no longer reloads on sync. |"""

SECTION_7 = """## 7. Added after the first build

The first version was a dashboard with a weekly memo. After feedback ("make it something people can use, not just read"), I extended it into a small product. The machine-learning model and the checking rules stayed the same; what changed is **where** the AI is used.

| Feature | What it does | Where AI is used | How it is kept honest |
|---|---|---|---|
| **Bring your own data** | Upload a CSV or Excel file, link a Google Sheet, or connect a database. Columns are matched to the 40 signals automatically. | The churn model scores every row **in the browser** (identical maths to Python, checked to 6 decimal places). | Customer rows never leave the device; the AI only receives aggregate figures, as in Phase 1. |
| **What-if simulator** | Switch on fixes (failed payments, video start, buffering, support, content, engagement, plan) or a retention campaign; every customer is re-scored. A goal planner works out what a target would need. | The churn model, re-applied to all customers. | Each lever is a stated assumption (a shift in the model's log-odds); results are labelled estimates. |
| **Assistant that operates the simulator** | Ask in plain English ("what are my options to keep 1,000 more customers?", "set failed payments to 20%"). It proposes options as cards, and applies them to the simulator on request. | The language model chooses which scenarios to try; **the churn model computes them**; the language model explains the computed numbers. | Numbers are verified against the facts; the apply confirmation is written by the app; the assistant never sees personal data. |
| **Live database** | A connector next to the company database (SQL Server, or the SQLite demo) turns raw viewing, billing and support events into the 40 signals. The app syncs every 30 seconds. | The model scores live customers in the browser. | The connector runs inside the company network and binds to the local machine only. The demo database is filled by a platform simulator I wrote. |
| **Learning loop** | Rebuilds what was known 30 days ago, compares it with who actually cancelled, measures drift (PSI), trains a challenger, and compares it with the live model on customers neither has seen. | Retraining the logistic regression on the latest outcomes. | A challenger must beat the live model's AUC by at least 0.01, and **a person approves the switch** (auto-promote is off by default). |

**Evidence from the walkthrough recording.** The video was recorded by a script that also checked, on the page, that each thing the narration claims actually happened: the toggle re-scored customers (6,588 to 6,402 expected cancellations), applying an option changed a lever and the forecast (6,402 to 5,587), a typed instruction changed the simulator, the guardrail question was refused, drift was visible after the market shift, and the approved model went live. A take that failed any check was discarded and re-recorded."""

HONESTY_WRONG = """* **The live demo is simulated too.** I wrote the demo database, the market shift and its effects. The learning loop proves the mechanism (detect drift, retrain, test on unseen customers, ask a person), not real-world accuracy. Real accuracy can only be measured 30 days after scoring; right after retraining, the accuracy shown is measured on the data the model learned from, and the app labels it that way.
* **The simulator's effects are assumptions on an associational model.** "Cut buffering by 50%" assumes risk falls as if the signal had changed. That is not proven cause and effect; it needs an experiment.
* **Other companies' data is scored with a model trained on Lumen Play's patterns.** Column matching makes it run, but the scores are indicative until the model is retrained on that company's own outcomes (which the learning loop does for a live database).
* **The assistant can still word things badly.** Its numbers are computed and checked, but a sentence that cannot be verified is shown with a red flag (or dropped from option explanations). A refusal with no figures is flagged "couldn't be verified": strict, not wrong."""

HONESTY_NOT_SHIP = """* **I would not expose the live connector to the internet.** It binds to the local machine and has no sign-in; a real deployment needs it inside the company network with TLS and access control. This is also why the hosted site cannot show live data to outside visitors.
* **I would not switch on auto-promote** for retrained models without a track record; a person approves each switch."""

HONESTY_COST = """* **Assistant:** about USD 0.0002 to 0.0006 per question (shown under every answer); a what-if question uses two calls (choose scenarios, then explain the computed results).
* **Learning loop:** no LLM cost; retraining the logistic regression takes seconds on a laptop.
* **Free-tier limits are the real constraint:** 8,000 tokens a minute and 200,000 a day per model on Groq. Recording the video used up the daily limit for `gpt-oss-120b` (failure 21). A team using this daily would need a paid tier, at a cost still measured in cents a day."""


def video_note(chat_model):
    if chat_model == "openai/gpt-oss-120b":
        return ("* **The walkthrough video uses the same models as the hosted app** (`gpt-oss-120b` for answers, "
                "`qwen3.8-27b` for the meaning check). Waiting time for AI replies is shortened in the edit and marked on screen.")
    return ("* **The walkthrough video's assistant section ran on `gpt-oss-20b`**, a smaller model from the same family, because the "
            "daily limit for `gpt-oss-120b` had been used up by earlier recording attempts (failure 21). The hosted app uses `gpt-oss-120b`. "
            "Waiting time for AI replies is shortened in the edit and marked on screen.")
VIDEO_CHAT_MODEL = "openai/gpt-oss-120b"   # set to the model the final walkthrough was recorded with
