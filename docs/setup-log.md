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

## Other
- `uv --version` -> uv 0.12.17 (line carried over from the earlier `docs/setup-logs.md`, which can be deleted).
