"""
The weekly-note engine, shared by the local script (src/step5_weekly_note.py)
and the live website (api/weekly_note.py), so both behave exactly the same.

Three parts:
  1. build_facts()  - turn dashboard numbers into a short list of numbered facts.
                      ONLY totals and shares: no subscriber IDs, names or numbers.
                      (Phase 1, row 6b: only aggregated signals leave our systems.)
  2. ask_llm()      - send the facts to Groq and ask for a plain-English note
                      that cites a fact number for every sentence.
  3. verify_note()  - our hallucination check (Phase 1, row 7a): every sentence
                      must cite real facts, and every number in it must appear
                      in those facts. Anything else is flagged as unsupported.
"""
import json
import os
import re
import time
import urllib.error
import urllib.request

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
# The model name can be changed without touching code: set GROQ_MODEL in .env or Vercel.
# (We first used llama-3.3-70b-versatile; Groq had retired it, so we switched.)
MODEL = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")
# USD per 1 million tokens (input, output). Estimates - check groq.com/pricing.
PRICES = {"openai/gpt-oss-120b": (0.15, 0.60), "openai/gpt-oss-20b": (0.075, 0.30)}
DEFAULT_PRICE = (0.15, 0.60)   # used when a model is not in the table (marked as an estimate)


def pct(x):
    return round(x * 100)


def build_facts(d):
    """Numbered facts the LLM is allowed to use. Each fact lists the numbers it contains.
    Each fact also has a short 'key', so tests can find it even if the numbering changes."""
    k, facts = d["kpis"], []

    def add(key, text, *numbers):
        # Allowed numbers = every number written in the fact, plus any extras passed in.
        # (Bug found by our own checker: "30 days" was flagged until we read numbers from the text.)
        in_text = [float(x.replace(",", "").rstrip(".")) for x in NUM.findall(text)]
        facts.append({"id": f"F{len(facts) + 1}", "key": key, "text": text, "numbers": in_text + list(numbers)})

    add("base", f"{k['subscribers']:,} paying subscribers were scored this week.")
    add("expected", f"About {k['expected_churners']:,} subscribers are expected to cancel in the next 30 days "
        f"({pct(k['expected_churn_rate'])}% of the base).")
    add("revenue", f"Total monthly revenue at risk is PKR {k['revenue_at_risk_pkr']:,}.")
    add("high_risk", f"The high-risk group is the top {k['high_risk_subscribers']:,} subscribers (top 10%), "
        f"with PKR {k['high_risk_revenue_at_risk_pkr']:,} of revenue at risk.")
    for i, r in enumerate(d["reason_summary"][:5]):
        add(f"reason{i + 1}", f"'{r['label']}' ({r['group'].lower()}) is a top reason for "
            f"{pct(r['share'])}% of the high-risk group.")
    # Content calendar: who is waiting for what (only genres where a title actually ended)
    waiting = sorted([c for c in d.get("content", []) if c["fans_whose_title_ended"] > 0],
                     key=lambda c: -c["high_risk_waiting"])
    for i, c in enumerate(waiting[:3]):
        add(f"content{i + 1}", f"{c['genre']}: {c['fans_whose_title_ended']:,} fans followed '{c['ended_title']}', "
            f"which ended {c['ended_days_ago']} days ago; the next release, '{c['next_title']}', arrives in "
            f"{c['next_release_in_days']} days. {c['high_risk_waiting']:,} of these fans are high-risk.")
    # Personas: the two groups with the most revenue at risk
    for i, p in enumerate(sorted(d.get("personas", []), key=lambda p: -p["revenue_at_risk_pkr"])[:2]):
        add(f"persona{i + 1}", f"The '{p['persona']}' group ({p['description'].lower()}) has "
            f"{p['subscribers']:,} subscribers, {p['high_risk']:,} of them high-risk, "
            f"with PKR {p['revenue_at_risk_pkr']:,} of monthly revenue at risk.")
    for col, label in [("plan", "plan"), ("payment_channel", "payment channel")]:
        s = d["segments"][col][0]
        add(f"riskiest_{col}", f"The riskiest {label} is {s['segment']}: average churn risk {pct(s['avg_risk'])}%, "
            f"PKR {int(s['revenue_at_risk_pkr']):,} at risk.")
    m = d["model"]
    add("lift", f"If the team contacts the top 10% by score, about {pct(m['precision_top10'])}% of them are real "
        f"leavers, {m['lift_top10']} times better than contacting people at random.")
    return facts


def fact_id(facts, key):
    return next(f["id"] for f in facts if f["key"] == key)


SYSTEM = """You write a short weekly churn note for a retention team at a Pakistani streaming subscription company.
Rules:
- Use ONLY the numbered facts given. Never invent numbers, segments, reasons or causes.
- End EVERY sentence with the fact ids it relies on, like [F2] or [F3, F7] - including long sentences
  that list several items (cite all of their facts, e.g. [F10, F11, F12]).
- Keep every label exactly as given: each reason keeps its own category in brackets (content, viewing,
  payment, ...). Never describe several reasons as one category, and never call people who are
  'at risk' or 'waiting' people who 'have cancelled'.
- Plain English, no jargon, friendly but direct. Currency is PKR.
- Return JSON: {"headline": str, "paragraphs": [str, str, str], "actions": [str, str, str]}
  Each action is one concrete thing the team can do this week, also ending with fact ids."""


class JSONReplyError(RuntimeError):
    """The model's reply was not valid JSON. Carries whatever text it did produce."""
    def __init__(self, msg, partial=""):
        super().__init__(msg)
        self.partial = partial


def _salvage(text):
    """Best-effort rescue of a JSON object from a broken reply (cut off, or with text around it)."""
    text = (text or "").strip()
    start = text.find("{")
    if start == -1:
        return None
    for end in range(len(text), start, -1):               # longest valid {...} first
        if text[end - 1] == "}":
            try:
                return json.loads(text[start:end])
            except ValueError:
                continue
    m = re.search(r'"answer"\s*:\s*"((?:[^"\\]|\\.)*)', text)  # cut-off JSON: keep the answer text
    if m:
        return {"answer": json.loads('"' + m.group(1).rstrip("\\") + '"')}
    return None


def _chat(messages, api_key, model, temperature=0.2, max_tokens=900, retries=2):
    """One call to Groq. Returns (parsed JSON answer, usage info).

    max_tokens matters on Groq's free tier: some models allow only ~1,000 output
    tokens per minute, and Groq rejects a request that MIGHT exceed that (error 429).

    Robustness (bug found in the live chat): JSON mode sometimes fails with
    'json_validate_failed', usually because the model's hidden reasoning used up the
    token budget and the JSON was cut off. We then retry once with more room, and if
    that fails too, rescue the JSON from the partial reply Groq sends back.
    """
    t0 = time.time()
    partial = ""
    for attempt in range(retries + 1):
        body = {"model": model, "temperature": temperature, "max_completion_tokens": max_tokens,
                "response_format": {"type": "json_object"}, "messages": messages}
        if model.startswith("openai/gpt-oss"):
            body["reasoning_effort"] = "low"   # gpt-oss thinks before answering; low = faster and cheaper
        req = urllib.request.Request(GROQ_URL, data=json.dumps(body).encode(), headers={
            "Authorization": f"Bearer {api_key}", "Content-Type": "application/json",
            "User-Agent": "churn-radar/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read())
            break
        except urllib.error.HTTPError as e:
            raw = e.read().decode()
            if e.code == 429 and attempt < retries:      # rate limit: wait and try again
                time.sleep(8 * (attempt + 1))
                continue
            if e.code == 400 and "json_validate_failed" in raw:
                try:
                    partial = json.loads(raw).get("error", {}).get("failed_generation", "") or partial
                except ValueError:
                    pass
                if attempt < retries:                    # retry with more room for the answer
                    max_tokens = min(int(max_tokens * 1.6), 2000)
                    continue
                rescued = _salvage(partial)
                if rescued:
                    return rescued, {"model": model, "seconds": round(time.time() - t0, 2), "input_tokens": 0,
                                     "output_tokens": 0, "cost_usd": 0.0, "price_is_estimate": True, "rescued": True}
                raise JSONReplyError("the model's reply was not valid JSON", partial) from None
            raise RuntimeError(f"Groq returned {e.code}: {raw[:300]}") from None
    usage = data.get("usage", {})
    tin, tout = usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)
    price_in, price_out = PRICES.get(model, DEFAULT_PRICE)
    meta = {"model": model, "seconds": round(time.time() - t0, 2),
            "input_tokens": tin, "output_tokens": tout,
            "cost_usd": round(tin / 1e6 * price_in + tout / 1e6 * price_out, 6),
            "price_is_estimate": model not in PRICES}
    content = data["choices"][0]["message"]["content"]
    try:
        return json.loads(content), meta
    except ValueError:
        rescued = _salvage(content)
        if rescued:
            return rescued, {**meta, "rescued": True}
        raise JSONReplyError("the model's reply was not valid JSON", content) from None


def facts_block(facts):
    return "\n".join(f"{f['id']}: {f['text']}" for f in facts)


def ask_llm(facts, api_key, temperature=0.3, feedback=None):
    msgs = [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": f"Facts for this week:\n{facts_block(facts)}\n\nWrite the note."}]
    if feedback:   # self-correction: show the writer its previous draft and what was wrong
        msgs += [{"role": "assistant", "content": json.dumps(feedback["draft"])},
                 {"role": "user", "content": "A checker found these problems. Rewrite the whole note, fixing them "
                                             "and keeping every rule:\n- " + "\n- ".join(feedback["problems"])}]
    note, meta = _chat(msgs, api_key, MODEL, temperature)
    note["meta"] = {"mode": "live", **meta}
    return note


def demo_note(facts):
    """Used when no API key is set: a fixed template filled from the same facts."""
    t = {f["id"]: f["text"] for f in facts}
    return {"headline": "Demo mode: template note (no AI key set)",
            "paragraphs": [f"{t['F2']} [F2]", f"{t['F4']} [F4]", f"{t['F5']} [F5]"],
            "actions": ["Call the high-risk group first. [F4, F13]"],
            "meta": {"mode": "demo", "model": "template", "seconds": 0,
                     "input_tokens": 0, "output_tokens": 0, "cost_usd": 0}}


NUM = re.compile(r"\d[\d,]*\.?\d*")
# Split after . ! ? or ] - but not after a list number like "1." at the start of an item
SENT_SPLIT = re.compile(r"(?<=[.!?\]])(?<!^\d\.)(?<!^\d\d\.)\s+(?=[A-Z])")
SCALED = re.compile(r"(\d[\d,]*\.?\d*)\s*(million|mn|m|k|thousand)?\b", re.IGNORECASE)
PRIVATE = re.compile(r"SUB\d{4,}|\b03\d{9}\b|\+92\d{10}")   # subscriber IDs or Pakistani phone numbers


def verify_note(note, facts, allow_plain=False):
    """Check every sentence. Returns per-sentence results and the unsupported-claim rate.
    allow_plain=True (used by the chat): a sentence with no numbers and no citation, such as
    "I can't see that in the data", is allowed; the judge still checks its meaning."""
    by_id = {f["id"]: f for f in facts}
    sentences = []
    for part in note.get("paragraphs", []) + note.get("actions", []):
        sentences += [s.strip() for s in SENT_SPLIT.split(part) if s.strip()]

    checked = []
    for s in sentences:
        cites = " ".join(re.findall(r"\[([^\]]*)\]", s))
        cited = re.findall(r"F\d+", cites)
        for a, b in re.findall(r"F(\d+)\s*[-\u2013\u2011]\s*F(\d+)", cites):   # ranges like F10-F12
            cited += [f"F{i}" for i in range(int(a), int(b) + 1)]
        problems = []
        if not cited and allow_plain and not NUM.findall(re.sub(r"\[[^\]]*\]", "", s)):
            checked.append({"sentence": s, "cited": [], "ok": True, "problems": []})
            continue
        if not cited:
            # Targeted feedback: work out which facts these numbers came from, so the
            # repair step can tell the writer exactly which ids to add.
            nums = [float(x.replace(",", "").rstrip(".")) for x in NUM.findall(s)]
            big = [n for n in nums if n >= 100] or nums      # large numbers are distinctive fingerprints
            likely = [f["id"] for f in facts if any(abs(n - a) <= max(0.5, abs(a) * 0.01)
                                                    for n in big for a in f["numbers"])]
            problems.append("no fact cited" + (f" (these numbers match {', '.join(likely)}; "
                                               f"end the sentence with [{', '.join(likely)}])" if likely else ""))
        bad = [c for c in cited if c not in by_id]
        if bad:
            problems.append(f"cites facts that do not exist: {', '.join(bad)}")
        allowed = [n for c in cited if c in by_id for n in by_id[c]["numbers"]]
        text_wo_cites = re.sub(r"\[[^\]]*\]", "", s)
        text_wo_cites = re.sub(r"^\s*\d{1,2}[.)]\s+", "", text_wo_cites)          # list numbering "1. " is not a claim
        for m in SCALED.finditer(text_wo_cites):
            raw, unit = m.group(1), (m.group(2) or "").lower()
            n = float(raw.replace(",", "").rstrip("."))
            n *= {"million": 1e6, "m": 1e6, "mn": 1e6, "k": 1e3, "thousand": 1e3}.get(unit, 1)
            # Rounded forms ("PKR 2.76 million" for 2,764,263) are fine within 1%
            if not any(abs(n - a) <= max(0.5, abs(a) * 0.01) for a in allowed):
                problems.append(f"number {raw}{(' ' + unit) if unit else ''} is not in the cited facts")
        if PRIVATE.search(s):
            problems.append("contains a subscriber ID or phone number")
        checked.append({"sentence": s, "cited": cited, "ok": not problems, "problems": problems})

    flagged = sum(not c["ok"] for c in checked)
    return {"sentences": checked, "total": len(checked), "flagged": flagged,
            "unsupported_rate": round(flagged / len(checked), 3) if checked else 0.0,
            "passed": flagged == 0}


def load_key():
    """Read GROQ_API_KEY from the environment, or from the local .env file."""
    key = os.environ.get("GROQ_API_KEY", "").strip()
    if not key and os.path.exists(".env"):
        for line in open(".env"):
            if line.startswith("GROQ_API_KEY="):
                key = line.split("=", 1)[1].strip().strip('"').strip("'")
    return key


# ---------------------------------------------------------------------------
# Second AI pass: the "judge"
# ---------------------------------------------------------------------------
# The number check above cannot see MEANING. Example we found: the writer said
# "39% missed the sports series" when the fact says "the series ended".
# The number is right, the meaning is wrong. So a second model reads each
# sentence next to the facts it cites and gives a verdict.
# We use a DIFFERENT model family as judge, so the two are less likely to share
# the same blind spots.
# Tested on 5 planted errors: qwen caught 5/5, gpt-oss-20b caught 4/5 (missed the sports one).
JUDGE_MODEL = os.environ.get("GROQ_JUDGE_MODEL", "qwen/qwen3.8-27b")

JUDGE_SYSTEM = """You are a strict fact-checker. For each numbered sentence, compare it ONLY with the facts provided.
Verdicts:
- "faithful": every factual claim matches the facts in meaning, not just in numbers.
- "distorted": it uses real numbers but changes their meaning (wrong group, wrong cause, wrong direction, wrong label).
- "unsupported": it states something that is not in the facts at all.
Recommendations ("contact", "launch", "offer") are allowed: judge only the factual claims inside them.
Return JSON: {"verdicts": [{"n": int, "verdict": "faithful|distorted|unsupported", "why": "max 12 words"}]}
Give a verdict for EVERY sentence, in order. Keep each "why" very short."""


def judge_note(verification, facts, api_key):
    sents = verification["sentences"]
    listing = "\n".join(f"{i + 1}. {s['sentence']}" for i, s in enumerate(sents))
    out, meta = _chat([{"role": "system", "content": JUDGE_SYSTEM},
                       {"role": "user", "content": f"FACTS:\n{facts_block(facts)}\n\nSENTENCES:\n{listing}"}],
                      api_key, JUDGE_MODEL, temperature=0, max_tokens=900)
    by_n = {v.get("n"): v for v in out.get("verdicts", [])}
    for i, s in enumerate(sents):
        # If the judge ran out of room before reaching a sentence, say "unchecked" - not "unsupported".
        v = by_n.get(i + 1, {"verdict": "unchecked", "why": "the judge did not reach this sentence"})
        s["judge"] = {"verdict": v.get("verdict"), "why": v.get("why", "")}
        s["ok_final"] = s["ok"] and s["judge"]["verdict"] in ("faithful", "unchecked")
    flagged = sum(not s["ok_final"] for s in sents)
    verification.update({"judge_meta": meta, "flagged_final": flagged,
                         "unchecked": sum(s["judge"]["verdict"] == "unchecked" for s in sents),
                         "unsupported_rate_final": round(flagged / len(sents), 3) if sents else 0.0,
                         "passed_final": flagged == 0})
    return verification


def make_traps(facts):
    """Five planted false statements, one per kind of error, pointing at the right facts by key."""
    by_key = {f["key"]: f for f in facts}
    c1 = by_key.get("content1")
    ch = by_key["riskiest_payment_channel"]["text"].split(" is ")[1].split(":")[0]
    waiting = c1["text"].split(":")[1].split(" fans")[0].strip() if c1 else "1,000"
    genre = c1["text"].split(":")[0] if c1 else "Sports"
    return {"headline": "trap", "actions": [], "paragraphs": [
        f"Churn is up 25% because of the new price increase. [{fact_id(facts, 'expected')}]",       # invented number + cause
        f"Subscriber SUB000123 is the most likely to leave. [{fact_id(facts, 'high_risk')}]",       # privacy leak
        "Karachi has the highest churn in the country.",                                             # no citation
        f"{waiting} {genre} fans have already cancelled because their title ended. [{c1['id'] if c1 else 'F1'}]",  # right number, wrong meaning
        f"{ch} customers are the least likely to cancel. [{fact_id(facts, 'riskiest_payment_channel')}]",          # reversed direction
    ]}


def run_pipeline(dashboard, api_key, facts=None):
    """Everything the website's 'Regenerate' button does: write, check numbers, judge.
    `facts` lets the browser supply aggregate facts for a customer's own uploaded data."""
    facts = facts or build_facts(dashboard)
    assert not PRIVATE.search(json.dumps(facts)), "privacy check failed"
    if not api_key:
        note = demo_note(facts)
        note["verification"] = verify_note(note, facts)
        note["meta"]["total_cost_usd"] = 0
        return note, facts

    attempts, spent, feedback = [], 0.0, None
    for attempt in range(2):                         # first draft + at most one repair
        note = ask_llm(facts, api_key, feedback=feedback)
        v = verify_note(note, facts)
        try:
            v = judge_note(v, facts, api_key)
        except Exception as e:                       # judge down or rate-limited: keep the note, say so
            v["judge_error"] = str(e)[:200]
        spent += note["meta"]["cost_usd"] + v.get("judge_meta", {}).get("cost_usd", 0)
        bad = [s for s in v["sentences"] if not s.get("ok_final", s["ok"])]
        problems = [f'"{s["sentence"][:80]}..." -> ' + "; ".join(
                        s["problems"] + ([f'judge: {s["judge"]["verdict"]} ({s["judge"]["why"]})']
                                         if s.get("judge", {}).get("verdict", "faithful") not in ("faithful", "unchecked") else []))
                    for s in bad]
        attempts.append({"attempt": attempt + 1, "flagged": len(bad), "problems": problems})
        if not bad:
            break
        feedback = {"draft": {k: note[k] for k in ("headline", "paragraphs", "actions")}, "problems": problems}
    note["verification"] = v
    note["attempts"] = attempts
    note["meta"]["total_cost_usd"] = round(spent, 6)
    return note, facts


# ---------------------------------------------------------------------------
# Chat: answer a question from the same kind of numbered facts
# ---------------------------------------------------------------------------
CHAT_SYSTEM = """You are Churn Radar, an assistant for the leadership of a subscription streaming company.
Answer the user's question using ONLY the numbered facts provided.
Rules:
- 1 to 4 short sentences, plain English for executives, currency PKR.
- End every sentence that states a number or a finding with the fact ids it relies on, like [F3] or [F2, F9].
- Keep every label exactly as written in the facts. Never invent numbers, causes, segments or trends.
- If the facts do not answer the question, say so in one sentence without a citation, and say what data would be needed.
- Never give individual customer details; you only see totals.
Return JSON: {"answer": str, "followups": [three short follow-up questions the facts can answer]}"""


def clean_facts(raw):
    """Facts arrive from the browser, so never trust them: rebuild numbers here, cap sizes, block identifiers."""
    facts = []
    for i, f in enumerate((raw or [])[:40]):
        text = str(f.get("text", ""))[:400]
        if PRIVATE.search(text):
            raise ValueError("facts must not contain customer IDs or phone numbers")
        nums = [float(x.replace(",", "").rstrip(".")) for x in NUM.findall(text)]
        facts.append({"id": f"F{i + 1}", "key": str(f.get("key", ""))[:40], "text": text, "numbers": nums})
    if not facts:
        raise ValueError("no facts provided")
    return facts


def answer_question(facts, question, history, api_key):
    question = str(question)[:500]
    if PRIVATE.search(question):
        raise ValueError("please don't include customer IDs or phone numbers in questions")
    msgs = [{"role": "system", "content": CHAT_SYSTEM},
            {"role": "user", "content": f"FACTS:\n{facts_block(facts)}"}]
    for h in (history or [])[-6:]:
        if h.get("role") in ("user", "assistant"):
            msgs.append({"role": h["role"], "content": str(h.get("content", ""))[:800]})
    msgs.append({"role": "user", "content": question})
    out, meta = _chat(msgs, api_key, MODEL, temperature=0.2, max_tokens=1200)
    answer = str(out.get("answer", "")).strip()
    v = verify_note({"paragraphs": [answer], "actions": []}, facts, allow_plain=True)
    try:
        v = judge_note(v, facts, api_key)
    except Exception as e:
        v["judge_error"] = str(e)[:200]
    cost = meta["cost_usd"] + v.get("judge_meta", {}).get("cost_usd", 0)
    return {"answer": answer, "followups": [str(x)[:120] for x in out.get("followups", [])][:3],
            "verification": v, "meta": {**meta, "total_cost_usd": round(cost, 6)}}
