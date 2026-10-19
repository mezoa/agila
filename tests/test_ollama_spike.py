import importlib.util
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

SPIKE_PATH = Path(__file__).resolve().parent.parent / "scripts" / "ollama_spike.py"
spec = importlib.util.spec_from_file_location("ollama_spike", SPIKE_PATH)
spike = importlib.util.module_from_spec(spec)
spec.loader.exec_module(spike)


def make_server(replies, requests):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers["Content-Length"])
            requests.append(json.loads(self.rfile.read(length)))
            reply = replies[(len(requests) - 1) % len(replies)]
            payload = json.dumps({"response": reply}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_port}"


def test_questions_split_six_and_four():
    assert len(spike.QUESTIONS) == 10
    assert sum(1 for _, _, ok in spike.QUESTIONS if ok) == 6
    assert all(len(passages) == 3 for _, passages, _ in spike.QUESTIONS)


def test_run_against_fake_server(capsys):
    requests = []
    good = json.dumps({"answerable": True, "answer": "x", "citations": []})
    server, url = make_server([good, good, "not json"], requests)
    try:
        code = spike.main(["spike", "fake-model"], base_url=url)
    finally:
        server.shutdown()

    assert code == 0
    assert len(requests) == 11  # 1 warm-up + 10 questions
    assert requests[0]["model"] == "fake-model"
    assert requests[0]["stream"] is False
    assert requests[0]["think"] is False
    assert requests[0]["format"] == spike.ANSWER_SCHEMA
    out = capsys.readouterr().out
    assert "median" in out and "valid JSON" in out
    assert "json_ok=False" in out


def test_usage_without_model(capsys):
    assert spike.main(["spike"]) == 2
