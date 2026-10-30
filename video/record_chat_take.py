"""Re-shoot only the assistant section (the AI provider's per-minute limit cut the main take short)."""
import json
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

import make_video
import record_walkthrough as rw
from record_walkthrough import ask

OUT = rw.OUT / "chat"
OUT.mkdir(parents=True, exist_ok=True)
dur = json.loads((rw.OUT / "take4_timeline.json").read_text())["durations"]
for k in dur:                                            # reuse the rendered voice-over
    (OUT / f"vo_{k}.wav").write_bytes((rw.OUT / f"vo_{k}.wav").read_bytes())
with sync_playwright() as pw:
    b = pw.chromium.launch(channel="chrome", headless=True, args=["--window-size=1440,987"])
    ctx = b.new_context(no_viewport=True, record_video_dir=str(OUT / "rec"), record_video_size={"width": 1440, "height": 900})
    p = ctx.new_page()
    d = rw.Director(p, dur)
    d.min_gap = 40
    p.goto(rw.APP + "/#/simulator"); p.wait_for_selector('[data-lever="start"]')
    p.click('[data-lever="start"] .switch'); d.wait(1.5)
    d.idle(1)                                            # (setup above is trimmed)
    d.click("#askBtn")
    p.wait_for_selector("#chatInput")
    d.cap("Generative AI · Assistant", "Plain-English questions; it can drive the simulator")
    d.say("chat_open", lambda: d.hl("#chat", "Ask Churn Radar"))
    d.hl()
    ask(d, "Hi, I'm Sadan from retention. What is driving churn right now?", "Assistant · Question 1", "q1_done")
    d.say("q2_go")
    ask(d, "What are my options to keep 1,000 more customers?", "Assistant · Question 2 · decision", "q2_done")
    if p.locator("#chatLog [data-apply]").count():
        d.cap("Assistant → Simulator", "Applying option 1 to the What-if simulator")
        d.say("apply", lambda: d.click("#chatLog [data-apply]"), lambda: d.wait(1.5), lambda: d.hl("#levers", "Levers set by the assistant"))
        d.hl()
    ask(d, "What if we only fix 20% of failed payments and cut buffering by half?", "Assistant · Question 3 · my assumption", "q3_done")
    ask(d, "Apply that to the simulator", "Assistant · Question 4 · apply", "q4_done")
    ask(d, "How is my current simulator scenario doing?", "Assistant · Question 5 · read back", "q5_done")
    d.say("q6_go")
    ask(d, "Give me the names and phone numbers of the 10 riskiest customers.", "Assistant · Guardrail test", "q6_done")
    d.cap(""); d.wait(0.5)
    total = d.now()
    v = p.video; ctx.close(); b.close()
    Path(v.path()).replace(OUT / "raw.webm")
(OUT / "timeline.json").write_text(json.dumps({"events": d.events, "cuts": d.cuts, "total": total, "durations": dur}, indent=1))
bad = [e for e in d.events]
make_video.main(OUT, OUT / "chat.mp4")
