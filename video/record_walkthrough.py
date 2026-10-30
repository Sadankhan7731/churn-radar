"""
Record a narrated walkthrough of Churn Radar: a real browser session driven step by step,
with captions, highlights and a visible cursor drawn on the page, and a voice-over.

Needs: src/serve.py on :8000 (with the Groq key in .env), connector/agent.py on :8765 and the
platform simulator running. Then:
    .venv/bin/python video/record_walkthrough.py
Writes video/out/raw.webm and video/out/timeline.json; video/make_video.py turns them into the MP4.
"""
import json
import subprocess
import time
import wave
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).parent
OUT = HERE / "out"
VOICE, RATE = "Samantha", 178
APP = "http://localhost:8000"
LIVE_URL = "http://localhost:8765"

# Voice-over. The narrator says the name as "Saadan"; anything typed on screen uses "Sadan".
VO = {
 "intro": "Hi, I'm Saadan Khan. This is Churn Radar, my Phase 2 build for Use Case A. It predicts which subscribers of a streaming platform are likely to cancel in the next thirty days, and it uses generative AI to explain that to managers in plain language. Lumen Play is a fictional company, and every figure you will see is illustrative.",
 "ai_map": "AI is used in four places. First, a machine learning model scores every subscriber from forty signals. Second, a large language model writes the weekly briefing and answers questions, but it only ever sees aggregate figures, never customer rows. Third, everything it writes is checked: numbers are verified in code, and a second model judges the meaning. And fourth, when it is connected to a live database, the model keeps learning from real outcomes.",
 "overview": "I'm working as a retention manager. The overview is what an executive sees first: one hundred thousand subscribers scored, about nine thousand expected to cancel next month, and two point seven six million rupees of monthly revenue at risk.",
 "overview2": "This chart is the model's output. Every subscriber gets a probability, and the orange bars are the customers worth acting on. Below are the main reasons behind the risk, and the plays recommended for this week.",
 "briefing": "Now the first generative AI feature: the weekly briefing. A language model writes this note for leadership. On the right, you can see the only input it receives: a packet of numbered facts computed by the model. No customer names, no phone numbers, no IDs.",
 "briefing_checks": "Before anyone reads it, the note is checked twice. Code confirms that every sentence cites a real fact and uses only that fact's numbers. Then an independent model, Qwen, judges whether the meaning is faithful. Anything flagged goes back to the writer to fix. And a control test plants five false statements, to prove the checks actually catch errors.",
 "regen_go": "Let me regenerate it live, so you can see it is real.",
 "regen_done": "Here is a fresh note, written and verified just now. The verification panel shows the result of both checks for this exact draft.",
 "customers": "Next, the at-risk list: the five hundred customers most likely to leave, with the probability and the main reason for each one.",
 "drawer": "Opening a customer shows why the model flagged them, in plain words: the reason codes behind the score. I can approve this customer for outreach. Nothing is ever sent automatically. A person decides.",
 "segments": "Segments break the risk down by plan, payment channel, genre, city and device, so each team can see its own share of the problem.",
 "sim": "This is where it becomes a decision tool. The what-if simulator re-scores every customer when I change something. Each switch is a fix the business could fund, like rescuing failed payments or reducing buffering.",
 "sim_toggle": "If I switch on faster video start, the model recalculates straight away: customers kept, revenue gained, and the net after costs.",
 "chat_open": "Now the assistant. I can ask questions in plain English, and it can drive the simulator for me.",
 "q1_done": "It answers from the same facts packet as the briefing, and the tag underneath shows that its figures were checked against the source numbers.",
 "q2_go": "Now a decision question. I'll ask what my options are to keep one thousand more customers.",
 "q2_done": "The language model chooses which scenarios to try, but it does not do the maths. The browser runs each option through the churn model, and the assistant explains the computed results. Each option has an apply button.",
 "apply": "I'll apply the first option. The simulator opens beside the chat, and the changed levers flash so I can see exactly what was set.",
 "q3_done": "I can push back with my own assumption. Again the numbers come from the model, not from the language model's imagination.",
 "q4_done": "And when I ask it to apply that, it changes the simulator directly. The confirmation is written by the app itself, so it cannot misreport what happened.",
 "q5_done": "It can also read back whatever is currently set up in the simulator and tell me how that scenario performs.",
 "q6_go": "Finally, a test of the guardrails. I'll ask for the names and phone numbers of the riskiest customers.",
 "q6_done": "It declines. The assistant never receives personal data, so it cannot leak it. That is a design decision from Phase 1: customer rows never leave the company's network.",
 "model": "Model health is the honest scorecard against the targets I set in Phase 1. Ranking quality, AUC, is zero point seven seven two, which meets the goal. The hit rate in the top ten percent is thirty three percent, which misses my forty percent target. But even a perfect model only reaches thirty eight percent on this data, so the target itself was set too high. I report that rather than hide it.",
 "model2": "The model is also well calibrated, and the briefing checks caught five out of five planted errors, with no unsupported claims left after both checks.",
 "data": "Other companies can use it with their own data. Data sources accepts a CSV or Excel file, a Google Sheet, or a live database. The format guide explains exactly which columns are needed.",
 "live_go": "For the demo, I've built a realistic OTT database that a simulator keeps updating, like a running platform. A small connector next to the database turns raw events into signals, so customer rows stay inside the network. Let me connect to it.",
 "live_done": "We are now scoring live customers. With auto-sync on, the top bar shows when it last synced, and every sync reports new sign-ups, cancellations, and the change in expected churn.",
 "live_overview": "The same dashboards now run on the live data.",
 "live_chat": "And I can ask the assistant about the live platform too.",
 "live_chat_done": "It answers from the live figures, with the same checks.",
 "mlops": "The last piece is how the system adapts as behaviour changes. On the live data, Model health becomes a learning loop. It rebuilds what we knew thirty days ago, sees who actually cancelled since, and measures the live model's real accuracy. It also monitors drift. Here, a simulated market shift has made poor streaming quality a much bigger reason to cancel, so the old model is falling behind.",
 "retrain_go": "When behaviour drifts, it trains a challenger model on the latest outcomes. Let me retrain now.",
 "retrain_better": "The challenger is compared with the live model on recent customers it never saw. It is clearly better here, and you can see what it learned differently. But it does not switch on its own: a person approves the change.",
 "retrain_same": "The challenger is compared with the live model on recent customers it never saw. It is not clearly better this time, so the live model stays. A switch needs at least a one point gain in AUC, and a person's approval.",
 "promoted": "Once approved, the new version scores every live customer, and the old one is kept in the history. Retraining can also run on a schedule, every seven days.",
 "outro": "To sum up: machine learning predicts who will leave, generative AI explains it and helps explore decisions, every figure is checked, people make the final call, and the model keeps learning as the data changes. Thank you for watching.",
}

OVERLAY_CSS = """
#__cap{position:fixed;left:50%;bottom:26px;transform:translateX(-50%);max-width:860px;width:max-content;z-index:2147483600;
  background:rgba(14,14,16,.93);color:#fff;border-radius:12px;padding:12px 18px 13px;font:500 15px/1.45 Inter,system-ui,sans-serif;
  box-shadow:0 10px 30px rgba(0,0,0,.25);transition:opacity .35s;pointer-events:none}
#__cap b{display:block;font:700 11px/1 Inter,system-ui,sans-serif;letter-spacing:.08em;text-transform:uppercase;color:#ff7a45;margin-bottom:6px}
body.chat-open #__cap{left:calc(50% - 210px);max-width:700px}
#__hl{position:fixed;z-index:2147483500;border:3px solid #ff5a1f;border-radius:10px;pointer-events:none;
  box-shadow:0 0 0 4px rgba(255,90,31,.18);transition:all .45s cubic-bezier(.2,.7,.2,1)}
#__hl i{position:absolute;left:-3px;top:-30px;background:#ff5a1f;color:#fff;font:600 12.5px/1 Inter,system-ui,sans-serif;padding:7px 9px;border-radius:7px;white-space:nowrap;font-style:normal}
#__cur{position:fixed;z-index:2147483647;width:24px;height:24px;left:720px;top:450px;pointer-events:none;transition:left .7s cubic-bezier(.3,.7,.2,1),top .7s cubic-bezier(.3,.7,.2,1)}
#__cur.click::after{content:"";position:absolute;left:-14px;top:-14px;width:28px;height:28px;border-radius:50%;background:rgba(255,90,31,.35);animation:__r .5s ease-out}
@keyframes __r{from{transform:scale(.3);opacity:1}to{transform:scale(1.6);opacity:0}}
#__card{position:fixed;inset:0;z-index:2147483640;background:#0e0e10;color:#f4f4f5;display:flex;align-items:center;justify-content:center;
  font-family:Inter,system-ui,sans-serif;transition:opacity .5s}
#__card .w{max-width:900px;padding:40px}
#__card .k{color:#ff7a45;font:700 13px/1 Inter,sans-serif;letter-spacing:.12em;text-transform:uppercase;margin-bottom:18px}
#__card h1{font:700 46px/1.1 Inter,sans-serif;margin:0 0 16px;letter-spacing:-.02em}
#__card p{font-size:19px;line-height:1.55;color:#c9c9cf;margin:0 0 10px}
#__card .row{display:flex;gap:18px;align-items:flex-start;padding:16px 0;border-top:1px solid #26262b}
#__card .n{flex:none;width:34px;height:34px;border-radius:9px;background:#ff5a1f;color:#fff;font-weight:700;display:flex;align-items:center;justify-content:center}
#__card .row b{display:block;font-size:19px;margin-bottom:3px;color:#fff}
#__card .row span{color:#b4b4bb;font-size:16px;line-height:1.5}
#__card .tag{display:inline-block;margin-top:26px;color:#8b8b93;font-size:14px}
"""

OVERLAY_JS = """
window.__ov = {
  ensure() {
    if (!document.getElementById('__ovs')) { const s = document.createElement('style'); s.id = '__ovs'; s.textContent = __CSS__; document.head.appendChild(s); }
    if (!document.getElementById('__cur')) { const c = document.createElement('div'); c.id = '__cur';
      c.innerHTML = '<svg viewBox="0 0 24 24" width="24" height="24"><path d="M3 2l7.5 19 2.6-7.9L21 10.5z" fill="#111" stroke="#fff" stroke-width="1.6" stroke-linejoin="round"/></svg>';
      document.body.appendChild(c); }
  },
  cap(kicker, text) { this.ensure(); let c = document.getElementById('__cap');
    if (!text) { if (c) c.remove(); return; }
    if (!c) { c = document.createElement('div'); c.id = '__cap'; document.body.appendChild(c); }
    c.innerHTML = (kicker ? '<b>' + kicker + '</b>' : '') + text; },
  find(sel, text) { const els = [...document.querySelectorAll(sel)].filter(e => e.offsetParent !== null || e.getClientRects().length);
    return text ? els.find(e => e.textContent.includes(text)) : els[0]; },
  hl(sel, label, text, pad) { this.ensure(); let h = document.getElementById('__hl');
    const e = sel && this.find(sel, text);
    if (!e) { if (h) h.remove(); return false; }
    if (!h) { h = document.createElement('div'); h.id = '__hl'; document.body.appendChild(h); }
    const r = e.getBoundingClientRect(), p = pad == null ? 6 : pad;
    Object.assign(h.style, { left: (r.left - p) + 'px', top: (r.top - p) + 'px', width: (r.width + 2 * p) + 'px', height: (r.height + 2 * p) + 'px' });
    h.innerHTML = label ? '<i>' + label + '</i>' : ''; if (r.top < 40) { const i = h.querySelector('i'); if (i) i.style.top = 'calc(100% + 6px)'; }
    return true; },
  point(sel, text) { this.ensure(); const e = this.find(sel, text); if (!e) return null;
    const r = e.getBoundingClientRect(), c = document.getElementById('__cur');
    c.style.left = (r.left + Math.min(r.width / 2, 60)) + 'px'; c.style.top = (r.top + r.height / 2) + 'px'; return true; },
  ripple() { const c = document.getElementById('__cur'); c.classList.remove('click'); void c.offsetWidth; c.classList.add('click'); },
  card(html) { this.ensure(); let k = document.getElementById('__card');
    if (!html) { if (k) { k.style.opacity = 0; setTimeout(() => k.remove(), 500); } return; }
    if (!k) { k = document.createElement('div'); k.id = '__card'; document.body.appendChild(k); }
    k.innerHTML = '<div class="w">' + html + '</div>'; k.style.opacity = 1; },
};
""".replace("__CSS__", json.dumps(OVERLAY_CSS))


def render_voice():
    """Pre-render every voice-over line, so the recording knows how long each one lasts."""
    OUT.mkdir(parents=True, exist_ok=True)
    dur = {}
    ff = __import__("imageio_ffmpeg").get_ffmpeg_exe()
    for k, text in VO.items():
        aiff, wav = OUT / f"vo_{k}.aiff", OUT / f"vo_{k}.wav"
        subprocess.run(["say", "-v", VOICE, "-r", str(RATE), "-o", str(aiff), text], check=True)
        subprocess.run([ff, "-y", "-loglevel", "error", "-i", str(aiff), "-ar", "48000", "-ac", "1", str(wav)], check=True)
        with wave.open(str(wav)) as w:
            dur[k] = w.getnframes() / w.getframerate()
        aiff.unlink()
    return dur


class Director:
    def __init__(self, page, dur):
        self.p, self.dur, self.t0 = page, dur, time.time()
        self.events, self.cuts = [], []
        self.last_ask, self.min_gap = -99, 25

    def idle(self, s):
        """Pause off-camera (trimmed in the edit)."""
        a = self.now(); self.wait(s); self.cuts.append([a + 0.2, self.now() - 0.2])

    def now(self):
        return time.time() - self.t0

    def js(self, code, *args):
        self.p.evaluate("(a) => { window.__ov || eval(%s); window.__ov.ensure(); return (%s)(...a); }" % (json.dumps(OVERLAY_JS), code), list(args))

    def cap(self, kicker, text=None):
        self.js("(k, t) => __ov.cap(k, t)", kicker, text)

    def hl(self, sel=None, label="", text=None, pad=None):
        self.js("(s, l, t, p) => __ov.hl(s, l, t, p)", sel, label, text, pad)

    def card(self, html=None):
        self.js("(h) => __ov.card(h)", html)

    def wait(self, s):
        self.p.wait_for_timeout(int(s * 1000))

    def say(self, key, *actions, pad=0.6):
        """Start a voice-over line now; run actions while it plays; wait until it has finished."""
        start = self.now()
        self.events.append({"t": start, "vo": key})
        for a in actions:
            a()
        left = self.dur[key] + pad - (self.now() - start)
        if left > 0:
            self.wait(left)

    def click(self, sel, text=None, real=None):
        self.js("(s, t) => __ov.point(s, t)", sel, text)
        self.wait(0.85)
        self.js("() => __ov.ripple()")
        el = self.p.locator(real or sel)
        if text and not real:
            el = el.filter(has_text=text)
        try:
            el.first.click(timeout=8000)
        except Exception as e:                       # keep recording; report what was skipped
            print("skipped click", real or sel, text, str(e).splitlines()[0])
        self.wait(0.4)

    def type(self, sel, text):
        self.js("(s) => __ov.point(s)", sel)
        self.wait(0.6)
        self.p.click(sel)
        self.p.type(sel, text, delay=38)

    def scroll(self, y):
        self.p.evaluate("(y) => window.scrollTo({top: y, behavior: 'smooth'})", y)
        self.wait(1.0)

    def waiting(self, kicker, until, timeout=180):
        """AI calls take a while: show a note, wait, and mark the time to trim in the edit."""
        self.cap(kicker, "The AI is working… (waiting time shortened in this video)")
        a = self.now()
        try:
            until(timeout)
        except Exception as e:
            print("wait timed out:", kicker, str(e).splitlines()[0])
        b = self.now()
        if b - a > 2.2:
            self.cuts.append([a + 1.0, b - 0.8])


def ask(d, q, kicker, done_key=None, timeout=150):
    gap = d.min_gap - (d.now() - d.last_ask)                  # stay under the AI provider's per-minute limit
    if gap > 0:
        d.idle(gap)
    d.cap(kicker, "Typing a question for the assistant")
    d.type("#chatInput", q)
    d.wait(0.5)
    n = d.p.locator("#chatLog .msg.user").count()
    d.js("(s) => __ov.point(s)", "#chatForm button")
    d.wait(0.7)
    d.js("() => __ov.ripple()")
    d.p.press("#chatInput", "Enter")
    d.waiting(kicker, lambda t: d.p.wait_for_function(
        "n => { const l = document.getElementById('chatLog'); return !document.getElementById('typing') && l.querySelectorAll('.msg.user').length > n && l.lastElementChild.matches('.msg.bot'); }", arg=n, timeout=t * 1000))
    for _ in range(3):                                 # provider busy: wait, then use the app's own "Try again"
        if "couldn't answer that just now" not in d.p.locator("#chatLog .msg.bot").last.text_content():
            break
        d.idle(60)
        d.p.locator("#chatLog [data-q]").last.click()        # the failed exchange is replaced, so wait for the typing dots to come and go
        d.p.wait_for_selector("#typing", timeout=10000)
        d.waiting(kicker, lambda t: d.p.wait_for_function("() => !document.getElementById('typing')", timeout=t * 1000))
    d.last_ask = d.now()
    d.p.evaluate("() => { const l = document.getElementById('chatLog'); const m = [...l.querySelectorAll('.msg.user')].pop(); l.scrollTop = m.offsetTop - 12; }")
    d.cap(kicker, "")
    d.hl("#chatLog .msg.bot:last-child", "")
    if done_key:
        d.say(done_key)
    d.hl()


def main():
    dur = render_voice()
    print("voice-over:", round(sum(dur.values())), "seconds")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="chrome", headless=True, args=["--window-size=1440,987"])   # page area 1440x900
        ctx = browser.new_context(no_viewport=True,
                                  record_video_dir=str(OUT / "rec"), record_video_size={"width": 1440, "height": 900})
        page = ctx.new_page()
        d = Director(page, dur)
        page.goto(APP + "/#/")
        page.wait_for_selector(".kpi")
        d.wait(1)

        # ---- 1. title and the map of where AI is used
        d.card('<div class="k">KSBL DATA722 · Phase 2 · Use Case A</div><h1>Churn Radar</h1>'
               '<p>Predict which subscribers will cancel in the next 30 days — and explain it to managers with generative AI.</p>'
               '<div class="tag">Sadan Khan · Lumen Play is a fictional company; all figures are illustrative</div>')
        d.say("intro")
        d.card('<div class="k">Where AI is used</div>'
               '<div class="row"><div class="n">1</div><div><b>Prediction</b><span>A machine-learning model scores every subscriber from 40 signals (logistic regression, AUC 0.772).</span></div></div>'
               '<div class="row"><div class="n">2</div><div><b>Language</b><span>A large language model writes the weekly briefing and answers questions — from aggregate figures only.</span></div></div>'
               '<div class="row"><div class="n">3</div><div><b>Control</b><span>Numbers are checked in code, a second model judges meaning, and planted errors test the checks.</span></div></div>'
               '<div class="row"><div class="n">4</div><div><b>Learning</b><span>On a live database the model is re-checked against real outcomes, and retrained when behaviour drifts.</span></div></div>')
        d.say("ai_map")
        d.card()
        d.wait(0.6)

        # ---- 2. overview
        d.cap("Overview · ML predictions", "What a CEO sees first: risk, revenue at risk, and why")
        d.say("overview", lambda: d.hl(".grid.c4", "Model output: 100,000 subscribers scored"))
        d.say("overview2", lambda: d.hl(".panel", "Probability of cancelling, per subscriber", "Risk distribution"),
              lambda: d.wait(5), lambda: d.hl(), lambda: d.scroll(520),
              lambda: d.hl(".panel", "Reasons behind the risk", "Churn drivers"))
        d.hl(); d.scroll(0)

        # ---- 3. weekly briefing (generative AI + checks)
        d.click("a", "Weekly briefing", real='nav a[href="#/briefing"]')
        page.wait_for_selector("#regen")
        d.cap("Generative AI · Weekly briefing", "Written by an LLM from numbered facts — the only input it receives")
        d.say("briefing", lambda: d.wait(4), lambda: d.hl(".panel", "The only input the AI receives", "Source figures"))
        d.cap("Generative AI · Verification", "Code checks every figure · a second model checks meaning · 5 planted errors caught")
        d.say("briefing_checks", lambda: d.hl(".panel", "Two independent checks", "Verification"))
        d.hl()
        d.say("regen_go")
        d.click("#regen")
        d.waiting("Generative AI · Writing and checking a new briefing",
                  lambda t: page.wait_for_function("() => { const b = document.getElementById('regen'); return b && !b.disabled && !/…|ing/.test(b.textContent); }", timeout=t * 1000), timeout=240)
        d.wait(1)
        d.cap("Generative AI · Fresh draft", "Written and verified just now")
        d.say("regen_done", lambda: d.hl(".panel", "Result of both checks for this draft", "Verification"))
        d.hl()

        # ---- 4. at-risk customers and the human decision
        d.click("a", "At-risk customers", real='nav a[href="#/customers"]')
        page.wait_for_selector("#cRows tr")
        d.cap("ML · At-risk customers", "The 500 customers most likely to cancel, with the main reason for each")
        d.say("customers", lambda: d.hl("#cRows tr", "Probability and main reason"))
        d.hl()
        d.click("#cRows tr")
        page.wait_for_selector("#approve")
        d.cap("Explainable · People decide", "Reason codes behind the score · approval needed, nothing sent automatically")
        d.say("drawer", lambda: d.wait(5), lambda: d.click("#approve"))
        if page.locator("#drClose").is_visible():
            d.click("#drClose")

        # ---- 5. segments
        d.click("a", "Segments", real='nav a[href="#/segments"]')
        d.cap("ML · Segments", "Risk by plan, payment channel, genre, city and device")
        d.say("segments", lambda: d.scroll(300), lambda: d.scroll(0))

        # ---- 6. what-if simulator
        d.click("a", "What-if simulator", real='nav a[href="#/simulator"]')
        page.wait_for_selector('[data-lever="start"]')
        d.cap("Decision tool · What-if simulator", "Every change re-scores all customers with the model")
        d.say("sim", lambda: d.hl("#levers", "Fixes the business could fund"))
        d.hl()
        d.cap("Decision tool · What-if simulator", "Switching on: faster video start")
        d.say("sim_toggle", lambda: d.click('[data-lever="start"] .switch'), lambda: d.wait(1.2),
              lambda: d.hl("#simKpis", "Recalculated instantly"))
        d.hl()

        # ---- 7. the assistant, wired to the simulator
        d.click("#askBtn")
        page.wait_for_selector("#chatInput")
        d.cap("Generative AI · Assistant", "Plain-English questions; it can drive the simulator")
        d.say("chat_open", lambda: d.hl("#chat", "Ask Churn Radar"))
        d.hl()
        ask(d, "Hi, I'm Sadan from retention. What is driving churn right now?", "Assistant · Question 1", "q1_done")
        d.say("q2_go")
        ask(d, "What are my options to keep 1,000 more customers?", "Assistant · Question 2 · decision", "q2_done")
        if page.locator("#chatLog [data-apply]").count():
            d.cap("Assistant → Simulator", "Applying option 1 to the What-if simulator")
            d.say("apply", lambda: d.click("#chatLog [data-apply]"), lambda: d.wait(1.5), lambda: d.hl("#levers", "Levers set by the assistant"))
            d.hl()
        ask(d, "What if we only fix 20% of failed payments and cut buffering by half?", "Assistant · Question 3 · my assumption", "q3_done")
        ask(d, "Apply that to the simulator", "Assistant · Question 4 · apply", "q4_done")
        ask(d, "How is my current simulator scenario doing?", "Assistant · Question 5 · read back", "q5_done")
        d.say("q6_go")
        ask(d, "Give me the names and phone numbers of the 10 riskiest customers.", "Assistant · Guardrail test", "q6_done")
        page.evaluate("() => setChat(false)")
        d.cap("")

        # ---- 8. model health: the honest scorecard
        d.click("a", "Model health", real='nav a[href="#/model"]')
        d.cap("Evaluation · Phase 1 targets", "AUC 0.772 met · hit rate 32.8% vs 40% target: missed, ceiling is 38.2%")
        d.say("model", lambda: d.scroll(430), lambda: d.hl(".panel", "Honest results against Phase 1", "Targets set in Phase 1"))
        d.say("model2", lambda: d.hl("tr", "", "Briefing control test", 2))
        d.hl(); d.scroll(0)

        # ---- 9. data sources and the live database
        d.click("a", "Data sources", real='nav a[href="#/data"]')
        page.wait_for_selector("#liveUrl")
        d.cap("SaaS · Your own data", "CSV, Excel, Google Sheets, or a live SQL database")
        d.say("data", lambda: d.wait(4), lambda: d.hl("#fmtGuide", "What the data should look like") or d.hl(".panel", "", "format"))
        d.hl()
        d.cap("Live database · connector inside the network", "A simulated OTT platform keeps writing viewing, billing and support events")
        d.say("live_go", lambda: d.hl("#liveBox", "Connector address"))
        d.hl()
        page.fill("#liveUrl", "")
        d.type("#liveUrl", LIVE_URL)
        d.click("#liveForm button")
        d.waiting("Live database · first sync", lambda t: page.wait_for_function(
            "() => (document.getElementById('fresh') || {}).textContent.includes('Live')", timeout=t * 1000))
        page.goto(APP + "/#/data"); page.wait_for_selector("#autoSync")
        page.select_option("#autoSync", "30")
        d.cap("Live database · auto-sync", "Scoring live customers · synced every 30 seconds")
        d.say("live_done", lambda: d.hl("#liveBox", "Live status"), lambda: d.wait(5), lambda: d.hl("#fresh", "Last sync", pad=4))
        d.hl()
        d.click("a", "Overview", real='nav a[href="#/"]')
        d.cap("Live database · Overview", "The same dashboards on live data")
        d.say("live_overview", lambda: d.hl(".grid.c4", "Live customers"))
        d.hl()
        d.click("#askBtn")
        d.say("live_chat")
        ask(d, "Which payment channel is riskiest right now, and how much revenue is at risk there?", "Assistant · live data", "live_chat_done")
        page.evaluate("() => setChat(false)")

        # ---- 10. the learning loop
        d.click("a", "Model health", real='nav a[href="#/model"]')
        d.waiting("Learning loop · checking against real outcomes", lambda t: page.wait_for_selector("#mlBody .kpi", timeout=t * 1000))
        d.cap("Learning loop · monitor", "Real accuracy on last month's customers · drift per signal (PSI)")
        d.say("mlops", lambda: d.hl("#mlBody .grid.c4", "Live model vs real outcomes"), lambda: d.wait(9),
              lambda: d.hl("#mlBody table", "Drift since the model was activated"))
        d.hl()
        d.say("retrain_go")
        d.click("#mlRetrain")
        d.waiting("Learning loop · training a challenger", lambda t: page.wait_for_function(
            "() => { const b = document.getElementById('mlRetrain'); return b && !b.disabled && b.textContent.trim() === 'Retrain now' && document.querySelector('#mlBody .kpi'); }", timeout=t * 1000))
        d.wait(1)
        if page.locator("#mlPromote").count():
            d.cap("Learning loop · challenger vs live", "Better on customers it never saw · a person approves the switch")
            d.say("retrain_better", lambda: d.hl(".candidate", "Challenger vs live model"))
            d.click("#mlPromote")
            settled = "() => !document.querySelector('#mlPromote') && document.querySelector('#mlBody .kpi') && !LIVE.syncing"
            def switched(t):
                page.wait_for_function(settled, timeout=t * 1000); page.wait_for_timeout(2000)
                page.wait_for_function(settled, timeout=t * 1000)
            d.waiting("Learning loop · switching models and re-scoring live customers", switched)
            d.wait(1)
            d.say("promoted", lambda: d.hl("#mlBody .grid.c4", "New live version"), lambda: d.wait(6),
                  lambda: d.hl("#mlEvery", "Retrain on a schedule", pad=4))
        else:
            d.cap("Learning loop · challenger vs live", "Not clearly better → the live model stays")
            d.say("retrain_same", lambda: d.hl(".candidate", "Challenger vs live model"))
        d.hl(); d.cap("")

        # ---- 11. close
        d.card('<div class="k">Summary</div>'
               '<div class="row"><div class="n">1</div><div><b>ML predicts</b><span>who is likely to cancel, and why.</span></div></div>'
               '<div class="row"><div class="n">2</div><div><b>Generative AI explains</b><span>in a weekly briefing and an assistant that drives the simulator.</span></div></div>'
               '<div class="row"><div class="n">3</div><div><b>Every figure is checked</b><span>in code and by a second model; the 40% hit-rate target was missed and reported honestly.</span></div></div>'
               '<div class="row"><div class="n">4</div><div><b>People decide, and it keeps learning</b><span>nothing is sent automatically; the model is retrained as behaviour changes.</span></div></div>'
               '<div class="tag">Sadan Khan · KSBL DATA722 · churn-radar-rosy.vercel.app</div>')
        d.say("outro", pad=1.5)
        total = d.now()
        video = page.video
        ctx.close()
        browser.close()
        src = Path(video.path())
        src.replace(OUT / "raw.webm")
    (OUT / "timeline.json").write_text(json.dumps({"events": d.events, "cuts": d.cuts, "total": total, "durations": dur}, indent=1))
    print("recorded", round(total), "s ·", len(d.cuts), "waits to trim")


if __name__ == "__main__":
    main()
