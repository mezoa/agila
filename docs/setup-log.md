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

### C1 /api/show (2026-10-19)
- qwen3.5:4b: 4.2B Q4_K_M, capabilities completion/vision/tools/thinking, thinking values [false,true] default true, max ctx 262144, Apache-2.0
- qwen3.5:9b: 9.7B Q4_K_M, same capabilities and thinking field, max ctx 262144, Apache-2.0
- Both default to temperature 1, top_k 20, top_p 0.95, presence_penalty 1.5
- Conclusion: thinking is on by default; send think:false per request. Resolves U1/U2 (field is top-level `thinking`).

### C2 structured output (2026-10-19) - U11 PASSED
- format JSON schema + think:false: 6/6 runs valid, 3 tags each (4b x3, 9b x3)
- Warm: 4b ~7.6 s, 9b ~9.9 s. Cold first call ~30 s (also when switching models)
- Tags vary in case/wording at default sampling (temp 1) -> normalize + validate in llm.py
- 4b summaries sometimes add details not in the source -> add "use only the given text"
- Caveat: one prompt, n=6; recheck in C3 with real questions

### C3 cited-answer timing (2026-10-19) - U11 holds (20/20 valid JSON here, 6/6 in C2)
Command: `uv run python scripts/ollama_spike.py qwen3.5:4b` (then `qwen3.5:9b`). 10 questions each.
- 4b: median 4.2 s (2.6-5.7), 9/10 correct (missed Q5 as false negative), 0 invented answers
- 9b: median 9.9 s (7.0-14.4), 9/10 correct (missed Q6 as false negative), 0 invented answers
- Per question, 4b (s): 5.3, 5.0, 5.6, 5.7, 3.5, 5.0, 3.0, 3.4, 2.9, 2.6. 9b (s): 12.5, 13.1, 14.4, 12.5, 12.7, 7.2, 7.2, 7.1, 7.0, 7.4
- Answerable replies take ~2x longer than refusals (output length)
- Not tested: citation correctness, real-size chunks, run-to-run variance
- Lean: 4b default (2.4x faster, same score)

### C3 cited-answer timing, 2 runs (2026-10-19) - U11 holds
- Run 2: 4b 10/10 correct, median 4.5 s; 9b 10/10 correct, median 13.1 s. Valid JSON 20/20 per model across both runs
- Run-1 misses (4b Q5, 9b Q6) did not repeat -> random variation, not a systematic weakness. Combined 19/20 each, 0 invented answers
- Time follows answer length: real answers 4b ~4.4-7 s / 9b ~13-15 s; refusals 4b ~3 s / 9b ~7 s
- Decision input: same accuracy, 9b ~2.5-3x slower -> 4b default
- Still untested: citation correctness, real-size chunks (check with the golden set later)

### C4 keep_alive and num_ctx (2026-10-19)
- keep_alive `"30m"` accepted (`ollama ps` showed UNTIL 29 minutes from now)
- qwen3.5:4b runs 52%/48% CPU/GPU at 3.8 GB; default context is already 4096 (`ollama ps` CONTEXT column)
- `num_ctx` 8192 tested: SIZE 3.8 -> 3.9 GB, CPU/GPU 52/48 -> 54/46. Speed at 8192 not measured (U16)

### C5 decisions (2026-10-19)
- Recorded in `docs/decisions.md`: `think:false` always, 4b default (9b optional), `format` schema + Pydantic + one retry + tag normalization, keep_alive 30m, `num_ctx` 8192 with a warning above 80%, answer-only-from-passages prompts
- Research: U2 PASSED; U1 and U11 PARTIAL; new U14 (temperature and tags), U15 (citation correctness), U16 (8192 speed)
- `scripts/ollama_spike.py` is temporary: delete it once `llm.py` exists (not deleted now)

## Day 3 (2026-10-19), block d: schema, migrations, db.py
- Installed: `psycopg[binary]` 3.3.6 (with psycopg-binary 3.3.6) and `pgvector` 0.5.1 via `uv add "psycopg[binary]" pgvector`
- Migrate (applies `migrations/*.sql` in order, one transaction each): `uv run --env-file .env python -m agila.db migrate` -> first run `applied: 0001_init.sql`, second run `nothing to apply`; `\dt` shows 5 tables + `schema_migrations`
- Fast tests (no database): `uv run pytest` -> 5 passed, 7 deselected. Database tests: `uv run --env-file .env pytest -m db -v` -> 7 passed (uses a throwaway `agila_test` database, dropped afterwards)
- Missing variable: `uv run --no-env-file python -m agila.db migrate` -> `migrate failed: Missing environment variable POSTGRES_HOST` (no value shown)
- Gotchas: plain `uv run` does not read `.env` (use `--env-file .env`); `register_vector` fails before the `vector` extension exists, so `migrate` connects with `register=False`
- `.env.example` now has POSTGRES_HOST=127.0.0.1 and POSTGRES_PORT=5433

## Day 4 (2026-10-20), block e part 2: embed and save text and Markdown
- `embed.py` imports `numpy` directly, so it is now an explicit dependency: `uv add "numpy>=2.5.4"` (2.5.4 was already installed through fastembed 0.9.0; the installed version did not change)
- Fast tests: `uv run pytest` -> 33 passed, 20 deselected. Database tests: `uv run --env-file .env pytest -m db -q` -> 20 passed (throwaway `agila_test`, gone afterwards: `\l`-style check listed only `postgres`, `agila`, `template0`, `template1`)
- Temporary command line (assumed, replaced by the CLI in block j): `uv run --env-file .env python -m agila.ingest markdown PATH [--title T] [--label L]` and `uv run --env-file .env python -m agila.ingest text --title T --label L [--file PATH]` (stdin if no `--file`). Prints `Saved <name>: N chunks` or one sentence
- Saving the same source type + label twice prints `Already saved: <label>. Replacing a saved item comes later (block g).` and writes nothing
- Not yet run by hand on the real `agila` database (plan verification 4, Eo's call: there is no delete command until block g)
- Deleted the spike scripts `scripts/embed_spike.py` and `scripts/token_count_spike.py`
- Hand check on the real `agila` database (Eo ran it): `uv run --env-file .env python -m agila.ingest --help` lists `text` and `markdown`; saving a 3-section Markdown file printed `Saved agila-day4.md: 3 chunks`, and the same command again printed `Already saved: agila-day4.md. Replacing a saved item comes later (block g).` That test document is still in the real database

## Day 4 (2026-10-20), block f part 1: save a URL (library only)
- Installed: `uv add "httpx>=0.28.1" "trafilatura>=2.3.1"` -> httpx 0.28.1 (declared; it was only transitive before) and trafilatura 2.3.1 with 13 more packages (courlan, htmldate, justext, lxml, lxml-html-clean, dateparser, babel, python-dateutil, pytz, regex, six, tld, tzlocal). Python 3.12.14
- Fast tests: `uv run pytest` -> 107 passed, 30 deselected. Database tests: `uv run --env-file .env pytest -m db -q` -> 30 passed (throwaway `agila_test`)
- Offline check: the plain suite was also run with every non-loopback `socket.connect` blocked (a guard set from `python -c` before `pytest.main`): 107 passed; the only connections were to `127.0.0.1`
- No command line for URLs yet (Day 5): `save_url` exists only in `library.py` and the tests; there is no private-address block, size cap or content-type check yet, so do not point it at real links before Day 5
- Fixtures: `tests/fixtures/article.html`, `menus.html`, `empty.html` (small, made up, readable in any editor)

## Day 5 (2026-10-21), block f part 2: safe download, redirects, size limits, `ingest url`
- No new packages. New files: `src/agila/netcheck.py`, `tests/test_netcheck.py`, `tests/test_netguard.py`, `tests/fixtures/login_wall.html`; changed: `web.py`, `library.py` (200-chunk cap, `Saved.title`), `ingest.py` (`url` command), `tests/conftest.py` (network guard), `test_web.py`, `test_library.py`, `test_ingest.py`
- Fast tests: `uv run pytest` -> 231 passed, 34 deselected. Database tests: `uv run --env-file .env pytest -m db -q` -> 34 passed (throwaway `agila_test`, gone afterwards: `psql ... select datname from pg_database` lists postgres, agila, template0, template1). `uv run ruff check .` clean
- Every test runs under the network guard in `tests/conftest.py`: any connection outside loopback or lookup of a real name fails the test. Guard self-tests: `uv run pytest tests/test_netguard.py -v` -> 7 passed
- New temporary command (replaced by the CLI in block j): `uv run --env-file .env python -m agila.ingest url URL [--title T]`
- Hand checks that touch no outside network (the refusal happens before any request): `... ingest url http://localhost:8000` and `... ingest url http://169.254.169.254/` each print `The address <host> is private, local or reserved, so it is not fetched.`; `... ingest url htp://example.test` prints `Only http and https links can be saved, and htp://example.test is neither.`; each exits with code 1 and `documents` stays at 0 rows
- Not run: `pytest` with the network switched off (the guard makes any outside connection a test failure, which is stricter); the 5 real links (Eo, report only)
- Gotcha: a `ruff format` over the whole tree reformats files that were never formatted that way; format only new files

## Day 6 (2026-10-22), block g: same item saved again, list, archive, delete
- No new packages. New file: `migrations/0002_identity_index_web_only.sql`; changed: `library.py`, `ingest.py`, `tests/test_db.py`, `tests/test_library.py`, `tests/test_ingest.py`
- Fast tests: `uv run pytest` -> 240 passed, 52 deselected. Database tests: `uv run --env-file .env pytest -m db -q` -> 52 passed (throwaway `agila_test` only, which migrates 0001 then 0002 itself; afterwards the server listed only `postgres`, `agila`, `template1`, `template0`)
- New temporary commands (replaced by the CLI in block j): `uv run --env-file .env python -m agila.ingest list`, `... archive ID`, `... unarchive ID`, `... delete ID` (dry run) and `... delete ID --yes`; `--replace` on `text`, `markdown` and `url`
- Not yet run (Eo, real `agila` database): `uv run --env-file .env python -m agila.db migrate` (expected `applied: 0002_identity_index_web_only.sql`, then `nothing to apply` on a second run) and the hand checks of plan block g, verification 4. Until 0002 is applied, a second text note with an existing label is refused with "The database needs an update: run uv run --env-file .env python -m agila.db migrate"
