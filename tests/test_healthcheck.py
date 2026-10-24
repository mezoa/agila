"""The Compose health check script (block k, V83), against a fake /health on 127.0.0.1."""

import importlib.util
import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "healthcheck.py"
_spec = importlib.util.spec_from_file_location("healthcheck", SCRIPT)
healthcheck = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(healthcheck)

OLLAMA_DOWN = "Ollama is not running, so answers fall back to passages. Start Ollama."
DATABASE_DOWN = "The database is not reachable, so nothing can be saved or found."


@pytest.fixture
def fake_health():
    """A loopback server whose /health answers with the status and body set by the test."""
    reply = {"status": 200, "body": b""}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(reply["status"])
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(reply["body"])

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    def answer(status, body):
        reply["status"] = status
        reply["body"] = body if isinstance(body, bytes) else json.dumps(body).encode()
        return f"http://127.0.0.1:{server.server_port}/health"

    yield answer
    server.shutdown()
    server.server_close()


def test_both_ok_is_healthy(fake_health):
    assert healthcheck.main(fake_health(200, {"database": "ok", "ollama": "ok"})) == 0


def test_ollama_down_is_still_healthy(fake_health):
    assert healthcheck.main(fake_health(503, {"database": "ok", "ollama": OLLAMA_DOWN})) == 0


def test_database_down_is_unhealthy(fake_health):
    assert healthcheck.main(fake_health(503, {"database": DATABASE_DOWN, "ollama": "ok"})) == 1


@pytest.mark.parametrize("body", [b"<html>not json</html>", b"", b'["database", "ok"]'])
def test_a_body_that_is_not_the_health_json_is_unhealthy(fake_health, body):
    assert healthcheck.main(fake_health(200, body)) == 1


def test_nothing_listening_is_unhealthy():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    assert healthcheck.main(f"http://127.0.0.1:{port}/health") == 1


def test_the_script_checks_the_api_inside_its_own_container():
    assert healthcheck.URL == "http://127.0.0.1:8000/health"
