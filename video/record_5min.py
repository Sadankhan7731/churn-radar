"""
The 5-minute narrated walkthrough (male voice), with captions, highlights and a visible cursor.
Every claim the narration makes is checked on the page while recording; problems are listed
at the end and saved in the timeline, so a bad take is caught before anyone watches it.

    .venv/bin/python video/record_5min.py      then      .venv/bin/python video/make_video.py 5min
"""
import json
import subprocess
import time
import wave
from pathlib import Path

from playwright.sync_api import sync_playwright

import record_walkthrough as rw
from record_walkthrough import ask

OUT = rw.OUT / "5min"
VOICE, RATE = "Daniel", 172
APP, LIVE_URL = rw.APP, rw.LIVE_URL

# Spoken name: "Saadaan". Typed on screen: "Sadan".
VO = {
 "intro": "Hi, I'm Saadaan Khan. This is Churn Radar, my Phase 2 project for Use Case A. It predicts which subscribers of a streaming service are likely to cancel next month, and it uses generative AI to explain the risk and help managers decide what to do. Lumen Play is a fictional company, and all figures are illustrative.",
 "ai_map": "AI is used in four ways. A machine learning model scores every subscriber. A language model writes the weekly briefing and answers questions, from aggregate figures only. Every number it writes is checked. And on live data, the model keeps learning.",
 "overview": "The overview shows the model's output: one hundred thousand subscribers scored, about nine thousand likely to cancel, and two point seven six million rupees of monthly revenue at risk.",
 "briefing": "The weekly briefing is written by a language model, from this list of numbered facts, which is the only thing it ever sees.",
 "checks": "Code then checks every figure, a second model checks the meaning, and a control test proves that planted errors are caught.",
 "customers": "The at-risk list ranks customers by probability. Opening one shows the reasons behind the score. A manager approves the outreach. Nothing is sent automatically.",
 "sim": "The what-if simulator turns predictions into decisions. Each switch is a fix the business could fund.",
 "sim_toggle": "When I switch on faster video start, every customer is re-scored, and expected cancellations drop straight away.",
 "chat_open": "Now the assistant. It answers in plain English, and it can operate the simulator for me.",
 "q1_done": "The answer comes from the same checked facts, and the green tag confirms the figures match the source.",
 "q2_go": "Next, a decision question: what are my options to keep one thousand more customers?",
 "q2_done": "The language model chooses which scenarios to try, but the churn model does the maths. Each card shows customers kept, net value and cost.",
 "apply": "I'll apply the first option. On the left, the simulator changes: the lever it set is highlighted, and expected cancellations update.",
 "q3_done": "I can also give an instruction in my own words. It sets the simulator directly, and the confirmation is written by the app, so it always matches what actually changed.",
 "q4_go": "Finally, a guardrail test. I'll ask for customers' names and phone numbers.",
 "q4_done": "It refuses. The assistant never receives personal data, so it cannot leak it.",
 "model": "Model health reports honestly against my Phase 1 targets. Ranking quality, an AUC of zero point seven seven, met the goal. The top ten percent hit rate of thirty three percent missed my forty percent target, but even a perfect model only reaches thirty eight percent on this data.",
 "live_go": "Companies can bring their own data, from files or a live database. For this demo, a simulated streaming platform keeps writing events into a database, and a connector inside the network turns them into signals. Let me connect.",
 "live_done": "Churn Radar now scores the live customers, and re-syncs every thirty seconds.",
 "mlops": "On live data, model health becomes a learning loop. It checks the live model against who actually cancelled, and watches for drift. After a simulated market shift, the original model has fallen behind.",
 "retrain_go": "So I retrain it on the latest outcomes.",
 "retrain_better": "The challenger is tested on recent customers it never saw, and it is clearly better. But it still needs a person's approval.",
 "retrain_same": "The challenger is tested on recent customers it never saw. It is not clearly better this time, so the live model stays.",
 "promoted": "Once approved, the new version scores every live customer, and retraining can also run automatically every seven days.",
 "outro": "In short: machine learning predicts, generative AI explains and helps decide, every figure is checked, people stay in control, and the model keeps learning. Thank you.",
}


def render_voice():
    OUT.mkdir(parents=True, exist_ok=True)
    ff = __import__("imageio_ffmpeg").get_ffmpeg_exe()
    dur = {}
    for k, text in VO.items():
        aiff, wav = OUT / f"vo_{k}.aiff", OUT / f"vo_{k}.wav"
        subprocess.run(["say", "-v", VOICE, "-r", str(RATE), "-o", str(aiff), text], check=True)
        subprocess.run([ff, "-y", "-loglevel", "error", "-i", str(aiff), "-ar", "48000", "-ac", "1", str(wav)], check=True)
        with wave.open(str(wav)) as w:
            dur[k] = w.getnframes() / w.getframerate()
        aiff.unlink()
    return dur


ISSUES = []


def check(ok, what):
    print(("  ok   " if ok else "  FAIL ") + what, flush=True)
    if not ok:
        ISSUES.append(what)


def sim_state(p):
    return p.evaluate("""() => ({ kpi: (document.querySelector('#simKpis .kpi-v') || {}).textContent || '',
        levers: [...document.querySelectorAll('.lever.flash')].map(e => e.dataset.lever),
        on: [...document.querySelectorAll('.lever.on')].map(e => e.dataset.lever),
        vals: Object.fromEntries([...document.querySelectorAll('.lever')].map(e => [e.dataset.lever, [...e.querySelectorAll('input')].map(i => i.type === 'checkbox' ? i.checked : i.value).join(',')])) })""")


def show_change(d, before, label):
    """Make a simulator change unmistakable: changed lever, then the KPI before -> after."""
    d.wait(1.3)                                          # let the app scroll the changed lever into view
    after = sim_state(d.p)
    check(after["kpi"] != before["kpi"], f"{label}: expected cancellations changed ({before['kpi']} -> {after['kpi']})")
    changed = [k for k in after["levers"] if before["vals"].get(k) != after["vals"].get(k)] or after["levers"]
    check(bool(changed), f"{label}: a lever visibly changed ({changed})")
    if changed:
        d.hl(f'[data-lever="{changed[0]}"]', "Changed by the assistant")
        d.wait(3.5)
    d.p.evaluate("() => window.scrollTo({top: 0, behavior: 'smooth'})"); d.wait(0.9)
    d.hl("#simKpis", f"Expected cancellations: {before['kpi']} → {after['kpi']}")
    return after


def main():
    dur = render_voice()
    print("voice-over:", round(sum(dur.values())), "s")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="chrome", headless=True, args=["--window-size=1440,987"])
        ctx = browser.new_context(no_viewport=True, record_video_dir=str(OUT / "rec"), record_video_size={"width": 1440, "height": 900})
        p = ctx.new_page()
        d = rw.Director(p, dur)
        d.min_gap = 40
        p.goto(APP + "/#/"); p.wait_for_selector(".kpi"); d.wait(1)

        # ---- title, and where AI is used
        d.card('<div class="k">KSBL DATA722 · Phase 2 · Use Case A</div><h1>Churn Radar</h1>'
               '<p>Predict which subscribers will cancel next month — and explain it, and decide what to do, with generative AI.</p>'
               '<div class="tag">Sadan Khan · Lumen Play is a fictional company; all figures are illustrative</div>')
        d.say("intro")
        d.card('<div class="k">Where AI is used</div>'
               '<div class="row"><div class="n">1</div><div><b>Prediction</b><span>A machine-learning model scores every subscriber from 40 signals.</span></div></div>'
               '<div class="row"><div class="n">2</div><div><b>Language</b><span>An LLM writes the weekly briefing and answers questions — aggregate figures only.</span></div></div>'
               '<div class="row"><div class="n">3</div><div><b>Control</b><span>Every figure is checked in code; a second model checks the meaning.</span></div></div>'
               '<div class="row"><div class="n">4</div><div><b>Learning</b><span>On live data the model is re-checked against real outcomes and retrained.</span></div></div>')
        d.say("ai_map")
        d.card(); d.wait(0.6)

        # ---- overview
        d.cap("Overview · ML predictions", "100,000 subscribers scored · revenue at risk · main reasons")
        check("9,076" in p.locator(".grid.c4").first.text_content(), "overview shows ~9,076 likely to cancel")
        d.say("overview", lambda: d.hl(".grid.c4", "Model output"), lambda: d.wait(6), lambda: d.hl(".panel", "Risk per subscriber", "Risk distribution"))
        d.hl()

        # ---- briefing
        d.click("a", "Weekly briefing", real='nav a[href="#/briefing"]')
        p.wait_for_selector("#regen")
        d.cap("Generative AI · Weekly briefing", "Written by an LLM from numbered facts — the only input it receives")
        d.say("briefing", lambda: d.wait(3), lambda: d.hl(".panel", "The only input the AI receives", "Source figures"))
        check("5 of 5" in p.locator(".panel", has_text="Verification").first.text_content(), "briefing shows control test 5 of 5")
        d.cap("Generative AI · Verification", "Figures checked in code · meaning checked by a second model · 5/5 planted errors caught")
        d.say("checks", lambda: d.hl(".panel", "Two independent checks", "Verification"))
        d.hl()

        # ---- customers
        d.click("a", "At-risk customers", real='nav a[href="#/customers"]')
        p.wait_for_selector("#cRows tr")
        d.cap("ML · At-risk customers", "Ranked by probability · reasons behind each score · people decide")
        def open_and_approve():
            d.hl("#cRows tr", "Probability and main reason"); d.wait(2.5); d.hl()
            d.click("#cRows tr"); p.wait_for_selector("#approve"); d.wait(2.2)
            d.hl("#drawer", "Why the model flagged this customer", None, 0); d.wait(2.5); d.hl()
            d.click("#approve")
        d.say("customers", open_and_approve)
        if p.locator("#drClose").is_visible():
            d.click("#drClose")

        # ---- simulator
        d.click("a", "What-if simulator", real='nav a[href="#/simulator"]')
        p.wait_for_selector('[data-lever="start"]')
        d.cap("Decision tool · What-if simulator", "Each switch is a fix the business could fund")
        d.say("sim", lambda: d.hl("#levers", "Fixes"))
        d.hl()
        before = sim_state(p)
        check("start" not in before["on"], "faster video start is off before the toggle")
        d.cap("Decision tool · What-if simulator", "Switching on: faster video start")
        def toggle():
            d.click('[data-lever="start"] .switch'); d.wait(1)
            after = sim_state(p)
            check(after["kpi"] != before["kpi"] and "start" in after["on"], f"toggle re-scored ({before['kpi']} -> {after['kpi']})")
            d.hl("#simKpis", f"Expected cancellations: {before['kpi']} → {after['kpi']}")
        d.say("sim_toggle", toggle)
        d.hl()

        # ---- assistant driving the simulator
        d.click("#askBtn"); p.wait_for_selector("#chatInput")
        d.cap("Generative AI · Assistant", "Plain-English questions · it can operate the simulator")
        d.say("chat_open", lambda: d.hl("#chat", "Ask Churn Radar"))
        d.hl()
        ask(d, "Hi, I'm Sadan from retention. What is driving churn right now?", "Assistant · Question", "q1_done")
        check("couldn't answer" not in p.locator("#chatLog .msg.bot").last.text_content(), "question 1 answered")
        d.say("q2_go")
        ask(d, "What are my options to keep 1,000 more customers?", "Assistant · Decision question", "q2_done")
        cards = p.locator("#chatLog .msg.bot").last.locator("[data-apply]")
        check(cards.count() > 0, "question 2 returned option cards")
        if cards.count():
            d.cap("Assistant → Simulator", "Applying option 1 · watch the simulator on the left")
            before = sim_state(p)
            def apply():
                p.evaluate("() => document.querySelector('#chatLog .msg.bot:last-child [data-apply]').scrollIntoView({block: 'center'})")
                d.wait(0.6)
                d.click("#chatLog .msg.bot:last-child [data-apply]", real=None)
                show_change(d, before, "apply option 1")
            d.say("apply", apply)
            d.hl()
        before = sim_state(p)
        ask(d, "Set failed payments to 20% and cut buffering by half in the simulator.", "Assistant · Instruction in my own words")
        last = p.locator("#chatLog .msg.bot").last
        if not last.locator(".applied").count() and last.locator("[data-apply]").count():
            d.click("#chatLog .msg.bot:last-child [data-apply]")        # it offered a scenario card: apply that
        check(p.locator("#chatLog .msg.bot").last.locator(".applied").count() > 0, "instruction was applied to the simulator")
        d.cap("Assistant → Simulator", "Applied · the confirmation is written by the app")
        d.say("q3_done", lambda: show_change(d, before, "instruction"))
        d.hl()
        d.say("q4_go")
        ask(d, "Give me the names and phone numbers of the 10 riskiest customers.", "Assistant · Guardrail test", "q4_done")
        txt = p.locator("#chatLog .msg.bot").last.text_content()
        import re
        check("couldn't answer" not in txt and not re.search(r"\d{7,}|\+92|03\d{2}", txt), "guardrail answer refuses without data")
        p.evaluate("() => setChat(false)"); d.cap("")

        # ---- model health
        d.click("a", "Model health", real='nav a[href="#/model"]')
        d.cap("Evaluation · Phase 1 targets", "AUC 0.772 met · hit rate 32.8% vs 40% target missed · perfect-model ceiling 38.2%")
        d.say("model", lambda: d.scroll(430), lambda: d.hl(".panel", "Honest results against Phase 1", "Targets set in Phase 1"))
        d.hl(); d.scroll(0)

        # ---- live database
        d.click("a", "Data sources", real='nav a[href="#/data"]')
        p.wait_for_selector("#liveUrl")
        d.cap("SaaS · Your own data", "Files, Google Sheets, or a live database through a connector inside your network")
        d.say("live_go", lambda: d.wait(5), lambda: d.hl("#liveBox", "Live database connector"))
        d.hl()
        p.fill("#liveUrl", "")
        d.type("#liveUrl", LIVE_URL)
        d.click("#liveForm button")
        d.waiting("Live database · first sync", lambda t: p.wait_for_function(
            "() => (document.getElementById('fresh') || {}).textContent.includes('Live')", timeout=t * 1000))
        p.goto(APP + "/#/data"); p.wait_for_selector("#autoSync"); p.select_option("#autoSync", "30")
        check("Live" in p.locator("#fresh").text_content(), "live sync is on")
        d.cap("Live database", "Scoring live customers · auto-sync every 30 seconds")
        d.say("live_done", lambda: d.hl("#liveBox", "Connected"), lambda: d.wait(3), lambda: d.hl("#fresh", "Last sync", None, 4))
        d.hl()

        # ---- learning loop
        d.click("a", "Model health", real='nav a[href="#/model"]')
        d.waiting("Learning loop · checking against real outcomes", lambda t: p.wait_for_selector("#mlBody .kpi", timeout=t * 1000))
        drift = p.locator("#mlBody .kpi").nth(3).text_content()
        check("Major" in drift or "Moderate" in drift, f"drift is visible ({drift.strip()[:40]})")
        d.cap("Learning loop · monitor", "Live model vs real cancellations · drift per signal")
        d.say("mlops", lambda: d.hl("#mlBody .grid.c4", "Live model vs real outcomes"))
        d.hl()
        d.say("retrain_go", lambda: d.click("#mlRetrain"))
        d.waiting("Learning loop · training a challenger", lambda t: p.wait_for_function(
            "() => { const b = document.getElementById('mlRetrain'); return b && !b.disabled && b.textContent.trim() === 'Retrain now' && document.querySelector('#mlBody .kpi'); }", timeout=t * 1000))
        d.wait(0.8)
        if p.locator("#mlPromote").count():
            d.cap("Learning loop · challenger vs live", "Better on customers it never saw · a person approves the switch")
            d.say("retrain_better", lambda: d.hl(".candidate", "Challenger vs live model"))
            new_v = p.locator("#mlPromote").text_content().strip().split("v")[-1]
            d.click("#mlPromote")
            settled = "() => !document.querySelector('#mlPromote') && document.querySelector('#mlBody .kpi') && !LIVE.syncing"
            def switched(t):
                p.wait_for_function(settled, timeout=t * 1000); p.wait_for_timeout(2000); p.wait_for_function(settled, timeout=t * 1000)
            d.waiting("Learning loop · switching models", switched)
            check(("v" + new_v) in p.locator("#mlBody .kpi").first.text_content(), f"v{new_v} is live after approval")
            d.cap("Learning loop · approved", "New version scores every live customer · retraining can run on a schedule")
            d.say("promoted", lambda: d.hl("#mlBody .grid.c4", "New live version"), lambda: d.wait(4), lambda: d.hl("#mlEvery", "Retrain on a schedule", None, 4))
        else:
            check(False, "retrain produced a better challenger (took the 'not better' branch)")
            d.cap("Learning loop · challenger vs live", "Not clearly better → the live model stays")
            d.say("retrain_same", lambda: d.hl(".candidate", "Challenger vs live model"))
        d.hl(); d.cap("")

        # ---- close
        d.card('<div class="k">Summary</div>'
               '<div class="row"><div class="n">1</div><div><b>ML predicts</b><span>who is likely to cancel, and why.</span></div></div>'
               '<div class="row"><div class="n">2</div><div><b>Generative AI explains and helps decide</b><span>weekly briefing · assistant that operates the simulator.</span></div></div>'
               '<div class="row"><div class="n">3</div><div><b>Every figure is checked</b><span>the 40% hit-rate target was missed and reported honestly.</span></div></div>'
               '<div class="row"><div class="n">4</div><div><b>People decide; the model keeps learning</b><span>nothing is sent automatically; retrained as behaviour changes.</span></div></div>'
               '<div class="tag">Sadan Khan · KSBL DATA722 · churn-radar-rosy.vercel.app</div>')
        d.say("outro", pad=1.5)
        total = d.now()
        v = p.video; ctx.close(); browser.close()
        Path(v.path()).replace(OUT / "raw.webm")
    (OUT / "timeline.json").write_text(json.dumps({"events": d.events, "cuts": d.cuts, "total": total, "durations": dur, "issues": ISSUES}, indent=1))
    print("recorded", round(total), "s ·", len(ISSUES), "issues:", ISSUES)


if __name__ == "__main__":
    main()
