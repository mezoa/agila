# Setup log (commands that worked, with results)

## Day 2 (2026-10-17), block a

### Versions (U9)
| Tool | Command | Result |
| --- | --- | --- |
| Python (system) | `python --version` | 3.14.7 (project pins 3.12 via `.python-version`; `requires-python >=3.12`) |
| uv | `uv --version` | 0.12.17 |
| Docker | `docker --version` | 29.6.1 (build 8900f1d) |
| Docker Compose | `docker compose version` | v5.3.0 |
| ruff | `uv add --dev ruff` | 0.17.1 |
| pytest | `uv add --dev pytest` | 9.1.1 |

### Project
- `uv init --lib --name agila --vcs none --python 3.12 .` -> created `pyproject.toml`, `.python-version`, `src/agila/` (src layout). `--lib` gives the src layout; `--vcs none` because the repo already exists.
- `uv add --dev ruff pytest` -> both added to the dev dependency group (`--dev` confirmed by `uv add --help`).
- `uv run ruff check .` -> All checks passed.
- `uv run ruff format --check .` -> already formatted.
- `uv run pytest` -> 1 passed.

### Docker and Compose
- Docker Desktop engine was not running at first: `failed to connect to the docker API at npipe:////./pipe/dockerDesktopLinuxEngine`. After starting it (WSL 2 engine, context `desktop-linux`) the engine works from Windows PowerShell. All Agila commands run in PowerShell, not Ubuntu.
- `docker compose config --no-interpolate -q` -> syntax ok (no values printed, so no password leaks).
- `docker compose up -d` -> pulled `pgvector/pgvector:0.8.7-pg17` (tag confirmed to exist). First publish of `127.0.0.1:5432` failed: "bind: An attempt was made to access a socket in a way forbidden by its access permissions".
- Diagnosis: `netsh interface ipv4 show excludedportrange protocol=tcp` showed only 50000-50059 and 51203-52002 reserved. `netstat -ano | findstr :5432` showed a local Windows `postgres` (process 8012) listening on 0.0.0.0:5432. The Docker message does not say "in use", so run both commands to tell the causes apart.
- Fix: `compose.yaml` publishes `127.0.0.1:5433:5432` (inside the container Postgres stays on 5432). **Every host-side connection (db.py, tests, psql) must use port 5433.**
- `docker compose ps` -> `agila-db-1` Up (healthy) on `127.0.0.1:5433->5432/tcp`.
- Vector test (`docker compose exec -T db psql ...`): `CREATE EXTENSION vector` (already present), table with `vector(3)`, three rows, `ORDER BY v <=> '[1,0,0]'` returned ids 1, 3, 2 with distances 0.0000, 0.0061, 1.0000. Works.
- Restart test: `docker compose down` (volume kept), `docker compose up -d`, health went back to `healthy`, the 3 rows were still there. Data survives. Test table dropped afterwards.

## Day 2 (2026-10-17), block b: host reachability (U3) and n8n alone (U4)
- Image pinned: `n8nio/n8n:2.43.6`, digest `sha256:dd580fe1ab6e99e85bc66f2acf8bc8c5e9409fbe61b2e2803c5024403ef52833` (from `docker images --digests`).
- Container `n8n` (created 2026-10-17 09:15 UTC), checked with `docker inspect`: port `127.0.0.1:5678->5678`, volume `n8n_data` at `/home/node/.n8n`, env `TZ=Asia/Manila` and `GENERIC_TIMEZONE=Asia/Manila`.
- Log: `Version: 2.43.6`, "Editor is now accessible via http://localhost:5678", owner set up, then clean stop on SIGTERM (exit 0). The log shows "Sandbox: enabled=false".
- Idle memory after the editor loads (`docker start n8n`, `http://127.0.0.1:5678/` returned 200, waited 60 s, `docker stats n8n --no-stream`): `MEM=369.2MiB / 9.641GiB CPU=0.29%`.
- Timezone result: `docker exec n8n date` -> `Sat Oct 17 17:30:35 PST 2026` (host UTC was 09:30, so UTC+8 = Philippine Standard Time); `docker exec n8n sh -c 'echo TZ=$TZ'` -> `TZ=Asia/Manila`. The container clock follows Asia/Manila. Not checked: the timezone shown inside the n8n editor UI (the `/rest/settings` output does not list it).
- Container stopped again afterwards (`docker stop n8n`).

### U3: container to host (2026-10-17)
- Host Ollama: `curl http://127.0.0.1:11434/api/version` -> `{"version":"0.40.4"}` (listening on 127.0.0.1:11434).
- Host test server: `python -m http.server 8765 --bind 127.0.0.1` serving `hello-from-host` (listening on 127.0.0.1:8765 only). Stopped afterwards.
- Throwaway container `docker run --rm curlimages/curl:8.11.1 -sS -m 10 -w '
HTTP %{http_code}
' <url>`:
  - `http://host.docker.internal:11434/api/version` -> `{"version":"0.40.4"}` `HTTP 200`
  - `http://host.docker.internal:8765/index.txt` -> `hello-from-host` `HTTP 200`
- Both reachable, including the server bound only to 127.0.0.1.

## Other
- `uv --version` -> uv 0.12.17 (line carried over from the earlier `docs/setup-logs.md`, which can be deleted).
