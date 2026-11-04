"""Local web interface. Run: python -m financial_rag.ui"""

import argparse
import json
import logging
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .config import load_env
from .limits import Limits
from .logging_config import LOGGER, REQUEST_ID, configure_logging, event
from .workspace import AskRequest, Workspace

WEB_ROOT = Path(__file__).parent / "web"
STATIC_FILES = {
    "/": ("index.html", "text/html"),
    "/app.js": ("app.js", "text/javascript"),
    "/style.css": ("style.css", "text/css"),
}
PIPELINE_LOCK = threading.Lock()
PIPELINE = None
LIMITS = Limits()
WORKSPACE = Workspace()


def ask(request):
    global PIPELINE
    with PIPELINE_LOCK:
        if PIPELINE is None:
            from .agent import ResearchAgent

            PIPELINE = ResearchAgent()
        return PIPELINE.answer(
            request.question,
            request.strategy,
            request.rerank,
            mode=request.mode,
            selector=request.selector,
            context=request.context,
            offline=request.offline,
        )


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        """Our response event replaces BaseHTTPRequestHandler's raw URL logging."""

    def respond(self, status, body, content_type="application/json"):
        request_id = REQUEST_ID.get()
        if content_type == "application/json":
            body = {**body, "request_id": request_id}
            data = json.dumps(body, ensure_ascii=False).encode()
        else:
            data = body
        self.send_response(status)
        self.send_header("Content-Type", content_type + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Request-ID", request_id)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
        )
        self.end_headers()
        self.wfile.write(data)
        path = urlparse(self.path).path
        event(
            "http.response",
            method=self.command,
            route=path
            if path in STATIC_FILES
            or path
            in (
                "/api/status",
                "/api/ask",
                "/api/ingest",
                "/api/jobs",
                "/api/chunks",
                "/api/evaluation",
                "/api/market",
            )
            else "unknown",
            status=status,
            elapsed_ms=round((time.perf_counter() - self.started) * 1000, 2),
        )

    def allowed_request(self):
        hosts = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
        origin = self.headers.get("Origin")
        return self.headers.get("Host") in hosts and (
            not origin or origin in {f"http://{h}" for h in hosts}
        )

    def dispatch(self, route):
        token = REQUEST_ID.set(uuid.uuid4().hex)
        self.started = time.perf_counter()
        try:
            if not self.allowed_request():
                return self.respond(403, {"error": "Request origin is not allowed."})
            route()
        except (BrokenPipeError, ConnectionResetError):
            event("http.client_disconnected", level=logging.WARNING)
        except ValueError as error:
            self.respond(400, {"error": str(error)})
        except Exception:
            LOGGER.exception("http.unhandled_error")
            self.respond(
                503,
                {
                    "error": "The service is unavailable. Retry, or use the request ID to check local logs."
                },
            )
        finally:
            REQUEST_ID.reset(token)

    def do_GET(self):
        self.dispatch(self.get)

    def get(self):
        parsed = urlparse(self.path)
        path, query = parsed.path, parse_qs(parsed.query)
        if path == "/api/status":
            return self.respond(200, WORKSPACE.status())
        if path == "/api/jobs":
            from .ingestion import jobs_snapshot

            return self.respond(200, {"jobs": jobs_snapshot()})
        if path == "/api/chunks":
            return self.respond(200, WORKSPACE.chunks(query.get("strategy", ["fixed"])[0]))
        if path == "/api/evaluation":
            return self.respond(200, WORKSPACE.evaluation())
        if path == "/api/market":
            from .market import history

            return self.respond(200, history(query.get("ticker", [""])[0]))
        if path not in STATIC_FILES:
            return self.respond(404, {"error": "Not found."})
        filename, kind = STATIC_FILES[path]
        self.respond(200, (WEB_ROOT / filename).read_bytes(), kind)

    def read_json(self):
        if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
            raise ValueError("Use JSON request content.")
        size = int(self.headers.get("Content-Length", "0"))
        if not 0 < size <= 16000:
            raise ValueError("Request is too large or empty.")
        try:
            body = json.loads(self.rfile.read(size))
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise ValueError("The request contains invalid JSON.") from None
        if not isinstance(body, dict):
            raise ValueError("The request must be a JSON object.")
        return body

    def do_POST(self):
        self.dispatch(self.post)

    def post(self):
        if self.path not in ("/api/ask", "/api/ingest"):
            return self.respond(404, {"error": "Not found."})
        kind = "ingest" if self.path == "/api/ingest" else "ask"
        if not LIMITS.allow(self.client_address[0], kind):
            event("http.rate_limited", level=logging.WARNING, operation=kind)
            return self.respond(
                429, {"error": "Local demo request limit reached. Try again later."}
            )
        body = self.read_json()
        if kind == "ingest":
            from .ingestion import start

            return self.respond(202, start(body.get("ticker", "")))
        request = AskRequest.parse(body)
        self.respond(200, ask(request))


def main():
    load_env()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8501)
    args = parser.parse_args()
    configure_logging()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    server.daemon_threads = True
    event("server.started", host="127.0.0.1", port=args.port)
    print(f"Financial Document Intelligence is ready at http://127.0.0.1:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        event("server.stopping")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
