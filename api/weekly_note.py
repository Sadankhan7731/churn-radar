"""
Live endpoint behind the dashboard's "Regenerate live" button.

On Vercel, every .py file in api/ becomes a URL: this one is /api/weekly_note.
Files starting with "_" (like _note_engine.py) are helpers, not URLs.
The Groq key comes from Vercel's Environment Variables, never from the code.
"""
import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _note_engine import load_key, run_pipeline   # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_last_call = [0.0]
MIN_SECONDS_BETWEEN_CALLS = 10   # simple guard so nobody can burn the API key by clicking fast


def generate():
    if time.time() - _last_call[0] < MIN_SECONDS_BETWEEN_CALLS:
        return 429, {"error": "Please wait a few seconds before regenerating again."}
    _last_call[0] = time.time()
    dashboard = json.load(open(os.path.join(ROOT, "public", "data", "dashboard.json")))
    try:
        note, facts = run_pipeline(dashboard, load_key())
        return 200, {"note": note, "facts": facts}
    except Exception as e:
        return 502, {"error": str(e)[:300]}


class handler(BaseHTTPRequestHandler):
    def _send(self, status, body):
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        self._send(*generate())

    def do_GET(self):
        self._send(*generate())
