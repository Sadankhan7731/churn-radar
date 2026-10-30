"""
/api/chat - the "Ask Churn Radar" assistant.

The browser sends the question plus aggregate facts it computed from the loaded data
(never customer rows). The server re-checks the facts, asks the writer model, then runs
the same two checks as the weekly briefing before returning the answer.
"""
import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _note_engine import answer_question, clean_facts, load_key   # noqa: E402

_last = [0.0]


def handle(body):
    if time.time() - _last[0] < 2:
        return 429, {"error": "One moment - please wait a couple of seconds between questions."}
    _last[0] = time.time()
    key = load_key()
    if not key:
        return 503, {"error": "The AI assistant is not configured on this server."}
    try:
        data = json.loads(body or b"{}")
        facts = clean_facts(data.get("facts"))
        return 200, {**answer_question(facts, data.get("question", ""), data.get("history"), key), "facts": facts}
    except ValueError as e:
        return 400, {"error": str(e)}
    except Exception as e:
        return 502, {"error": str(e)[:300]}


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > 200_000:
            status, out = 413, {"error": "Request too large"}
        else:
            status, out = handle(self.rfile.read(n))
        data = json.dumps(out).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)
