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

### Block a re-run (2026-10-17, later)
- Vector test (A4) repeated with `docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"'` (container env, `.env` not read): rows 1, 3, 2 with distances 0.0000, 0.0061, 1.0000. Pass.
- Restart test (A5) repeated: `docker compose down`, `docker compose up -d`, health `healthy`, same 3 rows and distances. Pass. Test table dropped.

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

## Day 2, results reported by Eo (blocks a and b, own run)
These come from Eo's own run and sit beside the Claude Code run above; the numbers differ because the test data and server port were different.

### Block a (Compose)
- Docker Desktop engine was not running at first and was started.
- Port 5432 is held by Eo's local Windows PostgreSQL, so the database is published on `127.0.0.1:5433`.
- `docker compose ps` -> healthy.
- Vector test returned 1. After `docker compose down` and `up -d` the count was 2.
- pgvector extension version: 0.8.7.
- `ollama --version` -> ollama version is 0.40.4.
- `uv run ruff check .` -> All checks passed. `uv run pytest` -> 1 passed (Python 3.12.14, pytest 9.1.1, pluggy 1.7.0, `tests	est_smoke.py`).

### Block b
- A throwaway container reached Ollama 0.40.4 and a test server bound to `127.0.0.1` on port 8000 through `host.docker.internal`. (The Claude Code run used port 8765; see U3 above.)
- n8n 2.43.6 ran with `TZ=Asia/Manila`; idle memory 361.7 MiB (Claude Code run: 369.2 MiB).

## Day 2 (2026-10-17), block c (part): think timing, 9b vs 4b (U1, U2)
- Test: `POST http://127.0.0.1:11434/api/generate`, `stream=false`, 3 passages and the question "Is pgvector search exact or approximate without an index?", Ollama 0.40.4. `think` left out (default) or `false`. Each setting run twice; the table uses run 2 (model already loaded). Script: not committed (scratch file).
- `ollama ps` default context 4096 for both models. 9b was sampled during the runs (steady); 4b was read right after the runs while still loaded, not during a request.

| Model | think | seconds (run 2) | thinking chars | ollama ps SIZE | answer correct? |
| --- | --- | --- | --- | --- | --- |
| qwen3.5:9b | default | 145.6 (run 1: 162.2) | 2753 | 6.2 GB, 73%/27% CPU/GPU | yes ("exact ... checks every row") |
| qwen3.5:9b | false | 4.2 (run 1: 2.3) | 0 | 6.2 GB, 73%/27% CPU/GPU | yes |
| qwen3.5:4b | default | 63.9 (run 1: 64.5) | 3155 | 3.8 GB, 52%/48% CPU/GPU | yes |
| qwen3.5:4b | false | 0.9 (run 1: 1.2) | 0 | 3.8 GB, 52%/48% CPU/GPU | yes |

- Finding (U2): both models think by default under Ollama 0.40.4 (thinking chars above 0 with `think` left out). `"think": false` per request switches it off and cuts time from 146 s to 4 s (9b) and 64 s to 0.9 s (4b).
- Finding (U1, partial): this is one short question with 3 short passages, not the 10-question test. With default thinking, 4b took about 64 s (over the 60 s target) and 9b about 146 s. With `think:false` both are far under 60 s. Real 3-chunk prompts are longer, so the 10-question timing is still to do.
- Finding: all 8 answers say "exact", so no wrong answers on this question. Answer style varies (9b run 2 began with "Exact." on its own line).
- Finding: `ollama ps` shows a GPU share (27% and 48%) even though the notes say CPU only. Not investigated; record only.
- Not done yet in block c: `/api/show` thinking values, `format` JSON schema test (U11), the 10-question run.
