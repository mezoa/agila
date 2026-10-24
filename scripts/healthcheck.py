"""Compose health check for the api container (V83): healthy while the database answers.

    python scripts/healthcheck.py

Exits 0 when `/health` says the database is ok, also when Ollama is down (then answers only fall
back to passages, so the container is still useful). Exits 1 for anything else. Standard library
only, so the image needs no curl; it reports the state and does not restart anything (U48).
"""

import json
import sys
import urllib.error
import urllib.request

URL = "http://127.0.0.1:8000/health"
TIMEOUT_SECONDS = 8  # /health runs two 3 s checks (V75); Compose allows 10 s


def main(url: str = URL) -> int:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # never a proxy
    try:
        with opener.open(url, timeout=TIMEOUT_SECONDS) as response:
            body = response.read()
    except urllib.error.HTTPError as exc:  # a 503 still carries the body that names the cause
        try:
            body = exc.read()
        except OSError:
            return 1
    except (OSError, ValueError):  # nothing listening, a timeout, a bad URL
        return 1
    try:
        state = json.loads(body)
    except ValueError:
        return 1
    return 0 if isinstance(state, dict) and state.get("database") == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
