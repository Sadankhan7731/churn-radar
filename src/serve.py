"""
Run the dashboard on your own Mac, exactly as it will work on Vercel.

  .venv/bin/python src/serve.py      then open http://localhost:8000

Serves the public/ folder, and sends /api/weekly_note to the same code Vercel runs.
"""
import json
import os
import sys
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "api"))
os.chdir(ROOT)                                   # so load_key() finds .env
from weekly_note import generate                # noqa: E402
from chat import handle as chat_handle          # noqa: E402

PORT = int(os.environ.get("PORT", 8000))


class Handler(SimpleHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b""
        if self.path.startswith("/api/weekly_note") or self.path.startswith("/api/chat"):
            status, body = generate(raw) if self.path.startswith("/api/weekly_note") else chat_handle(raw)
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        else:
            self.send_error(404)


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", PORT),
                                 partial(Handler, directory=os.path.join(ROOT, "public")))
    print(f"Churn Radar running at http://localhost:{PORT}  (Ctrl+C to stop)")
    server.serve_forever()
