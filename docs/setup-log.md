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

## Day 6 (2026-10-22), block h: search the saved passages
- No new packages. New files: `src/agila/retrieval.py`, `tests/test_retrieval.py`; changed: `embed.py` (`embed_question`), `ingest.py` (`search`), `tests/test_embed.py`, `tests/test_ingest.py`
- Fast tests: `uv run pytest` -> 260 passed, 66 deselected. Database tests: `uv run --env-file .env pytest -m db -q` -> 66 passed (throwaway `agila_test` only)
- New temporary command (replaced by the CLI in block j): `uv run --env-file .env python -m agila.ingest search "QUESTION" [--min-similarity X]`; the default threshold is the PROVISIONAL 0.70; the first search in a new process loads the model (about 1.2 s, V57)
- Not yet run (Eo, real library, read-only): the two hand searches of plan block h, verification 3

## Day 6 (2026-10-22), block i: the model call, checked answers, fallback, one call at a time
- `uv add pydantic` -> pydantic 2.14.1 (with pydantic-core 2.50.1, annotated-types 0.8.0, typing-inspection 0.4.4); `pyproject.toml` declares `pydantic>=2.14.1`, `uv.lock` pins the exact versions
- `ollama --version` -> `ollama version is 0.40.7` (it was 0.40.4 on 2026-10-17: the Ollama Windows app updated itself; research V68, DEVIATIONS row 32)
- New files: `src/agila/sentences.py`, `src/agila/llm.py`, `src/agila/ask.py`, `tests/test_sentences.py`, `tests/test_llm.py`, `tests/test_ask.py`, `tests/test_live_injection.py`, `tests/fixtures/injection.txt`; changed: `web.py` (uses `sentences.py`), `ingest.py` (`ask`), `tests/test_ingest.py`, `pyproject.toml` (`live` marker)
- Fast tests: `uv run pytest` -> 324 passed, 68 deselected. Database tests: `uv run --env-file .env pytest -m db -q` -> 67 passed (throwaway `agila_test` only)
- Live check (needs Ollama on 127.0.0.1:11434): `uv run pytest -m live -v` -> 1 passed (no PWNED)
- New temporary command (replaced by the CLI in block j; writes no `last_asked_at` and no `query_log`): `uv run --env-file .env python -m agila.ingest ask "QUESTION"`. Smoke run 2026-10-22: the knowledge-base question gave a 3-citation answer from `llm-wiki` in about 21 s; the World Cup question printed the refusal sentence
- `scripts/ollama_spike.py` NOT deleted: `tests/test_ollama_spike.py` loads it (3 tests); both kept until the Gate 1 cleanup (Eo, 2026-10-22)
- Hand check (Eo): `ingest ask` answer with 5 cited sentences; refusal with no model call; Ollama down -> readable sentence plus passages; `pytest -m live` passed twice; `last_asked_at` empty on 4 of 4 documents, `query_log` 0 rows

## Day 7 (2026-10-23), block j: CLI, API with key, `/docs`, `/health`, `query_log`
- `uv add` (run by Eo): `fastapi==0.133.1`, `uvicorn==0.53.0`; `uv.lock` brought starlette 1.9.0 and annotated-doc 0.0.5. Check: `uv run python -c "import fastapi, starlette, uvicorn; print(fastapi.__version__, starlette.__version__, uvicorn.__version__)"` -> `0.133.1 1.9.0 0.53.0`
- `ollama --version` -> `ollama version is 0.40.8` (0.40.7 on 2026-10-22: the Windows app updated itself again; research V68, V69, DEVIATIONS row 32)
- Tests: `uv run ruff check .` -> All checks passed; `uv run pytest` -> 373 passed, 76 deselected (1 warning: Starlette 1.9.0 says its test client wants `httpx2`, research V80); `uv run --env-file .env pytest -m db` -> 75 passed (throwaway `agila_test` only)
- New files: `src/agila/questions.py`, `src/agila/api.py`, `tests/test_questions.py`, `tests/test_api.py`; renamed: `src/agila/ingest.py` -> `src/agila/cli.py`, `tests/test_ingest.py` -> `tests/test_cli.py`; changed: `llm.py` (options, warm-up, Ollama check), `db.py` (connect timeout, database check), `tests/test_llm.py`, `tests/test_db.py`, `.env.example` (`AGILA_API_KEY=`)
- The CLI (replaces `agila.ingest`; same commands): `uv run --env-file .env python -m agila.cli --help` lists text, markdown, url, list, search, ask, evaluate, archive, unarchive, delete. `... agila.cli list` printed the 4 saved pages. `... agila.cli evaluate` -> "The evaluate command is not built yet; it comes with the golden set in block l." (exit 1). `... agila.cli ask "QUESTION"` writes one `query_log` row with channel `cli` (tested, not run by hand today)
- The API: add `AGILA_API_KEY=<a long random value>` to `.env` (Eo; not done yet on 2026-10-23), then `uv run --env-file .env python -m agila.api`. Without the key it prints "Missing environment variable AGILA_API_KEY. Add it to .env and run: uv run --env-file .env python -m agila.api" (exit 1, checked)
- Live check 2026-10-23 with a throwaway key set only in the shell (`AGILA_API_KEY=... uv run --env-file .env python -m agila.api`): netstat showed only `127.0.0.1:8000` LISTENING; `GET /health` (no key) -> `{"database":"ok","ollama":"ok"}` HTTP 200; `GET /docs` -> 200; `GET /documents` without a key -> 401 `{"detail":"Missing or wrong API key."}` with `www-authenticate: APIKey`; with a wrong key -> 401; `ollama ps` (empty before startup) showed `qwen3.5:4b` with context 8192 and "29 minutes from now" about 20 s after startup with no ask (warm-up). No ask was sent to the real database

## RAM with the stack running (research V78, measured 2026-10-23, one sample each, MB)
- Ollama with `qwen3.5:4b` loaded: runner `llama-server.exe` 2,474 working set (5,794 private bytes; `ollama ps` SIZE 3.9 GB, 54%/46% CPU/GPU), `ollama.exe serve` 67, `ollama app.exe` 58
- Postgres `agila-db-1` idle: 68 (`docker stats` 68.36 MiB)
- n8n `n8nio/n8n:2.43.6`, 75 s idle (started for the check, then stopped): 444 (`docker stats` 444.3 MiB)
- Docker's WSL VM `vmmemWSL`: 1,815 (it holds the containers; do not add Postgres and n8n on top of it)
- uvicorn idle, bare probe app: 55 (private 41) plus 5 for the `uv run` wrapper; uvicorn idle with Agila's embedder loaded: 216 (private 545)
- Laptop: 20,332 total, 4,139 free with the model, Postgres, the Docker VM and other apps running
- Commands: `Get-Process` (working set and private bytes), `docker stats --no-stream`, `Get-CimInstance Win32_OperatingSystem`

## Day 8 (2026-10-24), block k: API in Docker, health check, backup and restore test
- Base image (Eo's pull, 2026-10-24): `docker pull python:3.12-slim-bookworm` -> `Digest: sha256:6a0e06f5ba0b373d051aabd3fffb9b873f27f9a2a3a14bcbe37dee6f0e3bbc70`; `docker run --rm python:3.12-slim-bookworm python -V` -> `Python 3.12.15`. The Dockerfile pins `python:3.12-slim-bookworm@sha256:6a0e06f5...` (the tag Eo pulled; the digest decides what is used)
- uv image (Eo's pull): `docker pull ghcr.io/astral-sh/uv:0.12.17` -> `Digest: sha256:10787c682e4184e4f290de1171fd4703dc63de99221f10fe1c99002ce7fa9acc`; pinned the same way in the Dockerfile
- New files: `Dockerfile`, `.dockerignore`, `scripts/healthcheck.py`, `scripts/backup.py`, `scripts/restore_test.py`, `tests/test_healthcheck.py`, `tests/test_backup_restore.py`; changed: `compose.yaml` (`api` service), `.gitignore` (`backups/`), `src/agila/llm.py` (`OLLAMA_URL`), `src/agila/api.py` (`AGILA_HOST`)
- Tests: `uv run ruff check .` -> All checks passed; `uv run pytest` -> 407 passed, 80 deselected; `uv run --env-file .env pytest -m db` -> 79 passed
- One-time model prefetch for a fresh clone (needs the network once; the container runs with `HF_HUB_OFFLINE=1` and cannot download): `uv sync`, then `uv run python -c "from fastembed import TextEmbedding; from agila.chunking import MODEL_NAME, CACHE_DIR; TextEmbedding(MODEL_NAME, cache_dir=str(CACHE_DIR)); print('model cached')"` -> `model cached`. Run 2026-10-24 with the cache already present (so the download itself was not exercised; block v's fresh-clone test does that)
- Restore guard by hand: `uv run python scripts/restore_test.py --target agila` -> `Restore test refused: Refusing to restore into "agila": the test only uses agila_restore_test.`, exit 1, no docker command run
- Hand run by Eo, 2026-10-24 (plan block k commands 4 to 20, all passed):
  - Image `agila-api`: 631 MB on disk (155 MB compressed). Base `python:3.12-slim-bookworm@sha256:6a0e06f5ba0b373d051aabd3fffb9b873f27f9a2a3a14bcbe37dee6f0e3bbc70` (Python 3.12.15); uv `ghcr.io/astral-sh/uv:0.12.17@sha256:10787c682e4184e4f290de1171fd4703dc63de99221f10fe1c99002ce7fa9acc`, `/uv` path right. `docker compose up -d --build`: build 26.6 s with uv's package cache cold
  - Start time: after `docker compose stop api` then `docker compose start api`, healthy again after 12 s (the very first start was not timed)
  - `docker compose config --quiet` -> exit 0; `docker compose config | Select-String "published|host_ip|127.0.0.1"` -> both published ports (5433, 8000) on `host_ip: 127.0.0.1`
  - The image has no `.env` and only the named files; U24 inside the image with `--network none`: `2130706433`, `0x7f.0.0.1`, `127.1`, `0177.0.0.1` all gave `127.0.0.1`
  - The read-only model mount works with `HF_HUB_OFFLINE=1` (`:ro` stays); fastembed logs a harmless `Local file sizes do not match the metadata` warning
  - `/ask` through the container: an answer with a program-copied citation, 8.5 s warm. Ollama stopped: `/health` 503 naming Ollama in 0.06 s, `api` stayed healthy for 25+ minutes, `/ask` returned kind `passages` with a note
  - `uv run python scripts/backup.py` -> 137,807 bytes, documents 4, chunks 50. `uv run python scripts/restore_test.py` -> 4 = 4, 50 = 50, passed, `agila_restore_test` dropped; `--target agila` refused; the real library still 4 documents and 50 chunks
  - Stop the api without touching the database: `docker compose stop api`, then `docker compose start api`; the `pgdata` volume stayed. Never `docker compose down -v`

## Day 9 (2026-10-26), block l: golden-set evaluation (commands run by Eo; results as Eo reported them)
- Before and after, the real library (FR35): `"select count(*), max(last_asked_at) from documents; select count(*) from query_log;" | docker compose exec -T db sh -c 'psql -U $POSTGRES_USER -d $POSTGRES_DB -At'` -> `4|2026-10-24 14:31:55.458191+00` and `11`, unchanged (PowerShell 5.1 strips inner double quotes in `sh -c '... -c "..."'`, so the SQL is piped in with `-T`)
- `uv run --env-file .env python -m agila.cli evaluate freeze` (network, once) then `evaluate build` -> `agila_eval` with 9 documents, the 3 web pages reloaded from stored HTML
- `evaluate prefix` and `evaluate threshold --prefix` (dev half only) -> prefix kept, threshold 0.68 (decisions.md "Golden set, dev half")
- `evaluate retrieval --save-baseline` (held-out half, run once) -> hit@3 13 of 14, M2 5 of 6, M3 median 0.010 s; `eval/baseline.json`
- FR33: a copy of the baseline with the hit count raised by 1, then `evaluate retrieval --baseline <copy>` -> one sentence, exit 1; against the real baseline -> exit 0
- `docker compose stop api`, then `evaluate answers` (twice: the second after the grading-sheet excerpt change) -> M4 median 12.0 s, slowest 16.3 s (second run); `eval/runs/grading-2026-10-26.md` graded by hand
- Rerun commands for later: `eval/README.md`. Results: `eval/report.md`
- Gate 1 cleanup (2026-10-26): deleted `scripts/ollama_spike.py` and `tests/test_ollama_spike.py` (replaced by `llm.py`; no live references left)
- Secret scan (2026-10-26): git log for .env empty, only .env.example tracked, gitleaks (ghcr.io/gitleaks/gitleaks:latest, digest sha256:c00b6bd0aeb3071cbcb79009cb16a60dd9e0a7c60e2be9ab65d25e6bc8abbb7f) scanned 33 commits, no leaks found.

## Day 10 (2026-10-26), block m: text PDFs with page numbers (commands run by Eo; results as Eo reported them)
- Add the package: `uv add pypdf==6.21.2` -> only `pyproject.toml` and `uv.lock` changed; `uv run python -c "import pypdf; print(pypdf.__version__)"` -> `6.21.2`
- Tests: `uv run ruff check .` -> All checks passed; `uv run pytest` -> 542 passed; `uv run --env-file .env pytest -m db` -> 95 passed
- Rebuild the image: `docker compose up -d --build`, then `docker compose ps` (`api` healthy) and `curl.exe -s http://127.0.0.1:8000/health` -> `{"database":"ok","ollama":"ok"}`
- U60, pypdf inside the container: `docker compose exec api python -c "import pypdf; print(pypdf.__version__)"` -> `6.21.2`
- Save a PDF: `uv run --env-file .env python -m agila.cli pdf eval\library\pdf\csu-core-manual.pdf` (same for `ttlo-thesis.pdf` and `gadget-manual.pdf`) -> 187, 217 and 72 passages; `... agila.cli list` shows them
- Scanned PDF: `... agila.cli pdf eval\library\pdf\scanned-sample.pdf; $LASTEXITCODE` -> `scanned-sample.pdf has almost no text (it looks scanned or empty); Agila saves text PDFs only.` and `1`; nothing saved
- Same PDF again: `... agila.cli pdf eval\library\pdf\gadget-manual.pdf` -> `Already saved, unchanged: gadget-manual (document <id>).`
- Page numbers: `... agila.cli ask "QUESTION"` on the three manuals; each cited `PDF page N` checked in a PDF viewer by its page box (not the printed number): pages 33, 10, 9 and 10, quote found on each
- Database check: `"select source_type, count(*), count(page_count) from documents group by 1 order by 1;" | docker compose exec -T db sh -c 'psql -U $POSTGRES_USER -d $POSTGRES_DB -At'` and `"select count(*), count(c.page) from chunks c join documents d on d.id = c.document_id where d.source_type = 'pdf';" | docker compose exec -T db sh -c 'psql -U $POSTGRES_USER -d $POSTGRES_DB -At'` -> 72 of 72 and 476 of 476 (every PDF chunk has a page)

## Day 11 (2026-10-27), block n: Obsidian export (commands run by Eo; results as Eo reported them)
- Tests: `uv run ruff check .` -> All checks passed; `uv run pytest` -> 593 passed; `uv run --env-file .env pytest -m db` -> 109 passed
- Migration: `uv run --env-file .env python -m agila.db migrate` -> `applied: 0003_export.sql`
- Vault folders (once): `New-Item -ItemType Directory -Force raw\agila\files` (`raw/` stays git-ignored)
- First export of the existing library: `uv run --env-file .env python -m agila.cli export --retry` -> 7 notes written, the 3 PDFs saved before block n still pending (no path stored)
- PDF copies: `... agila.cli pdf eval\library\pdf\gadget-manual.pdf` (same for `csu-core-manual.pdf` and `ttlo-thesis.pdf`) -> `Already saved, unchanged: ...`; the path is stored and the copy made, 3 PDFs in `raw\agila\files` (the thesis copy is 32 MB)
- Obsidian: the project folder opened as a vault; notes show the properties, the tags `agila` and `agila/<type>`, and `**PDF page N**` marks
- Before/after listing (Obsidian closed), the rest of the vault must not change:
  `Get-ChildItem -Recurse -File -Force | Where-Object { $_.FullName -notmatch '\(\.git|\.venv|\.cache|__pycache__|\.pytest_cache|\.ruff_cache)\' -and $_.FullName -notmatch '\raw\agila\' } | Select-Object FullName, Length, LastWriteTimeUtc | Export-Csv $env:TEMP\vault-before.csv -NoTypeInformation`,
  then a text save, `archive`, `unarchive` and `delete <id> --yes` (text piped in: `"..." | ... agila.cli text --title "Block n check" --label n-check`), then the same listing into `vault-after.csv` and
  `Compare-Object (Import-Csv $env:TEMP\vault-before.csv) (Import-Csv $env:TEMP\vault-after.csv) -Property FullName, Length, LastWriteTimeUtc` -> printed nothing
- Rebuild with the mount: `docker compose up -d --build`, then `docker compose ps` (`api` healthy) and `curl.exe -s http://127.0.0.1:8000/health`
- Time zone in the container: `docker compose exec api python -c "import datetime; print(datetime.datetime.now().astimezone())"` -> ends in `+08:00`
- Through the API (`/docs`): a text save wrote its note into `raw\agila` and the delete removed it (the mount works both ways)
- With Obsidian open: archive and unarchive of one document -> no warning, no `.tmp` file seen
- Forced export failure: the save succeeded with the pending sentence (naming the error class, research U72), then `... agila.cli export --retry` wrote the note
- Known limits: research U71 (`#word` in a body becomes an Obsidian tag), U72, U73

## Day 12 (2026-10-27), block o part 1: Discord bot `/ping`, `/ask`, `/save` (commands run by Eo; results as Eo reported them)
- Shell check: `Get-ChildItem Env: | Where-Object Name -match 'AGILA|POSTGRES|DISCORD' | Select-Object Name` -> nothing (PROTOCOL rule 9)
- Tests: `uv run ruff check .` -> All checks passed; `uv run pytest` -> 759 passed; `uv run --env-file .env pytest -m db` -> 110 passed
- Image size: `docker image ls --format "{{.Repository}} {{.Size}}" | Select-String agila` -> `api` 634 MB before, 655 MB after the rebuild (discord.py is a main dependency, Q1 accepted)
- Rebuild: `docker compose up -d --build`, then `docker compose ps` (`api` healthy) and `curl.exe -s http://127.0.0.1:8000/health` -> `{"database":"ok","ollama":"ok"}`
- Access log off (U81): `/docs` `GET /search` with `access log check words`, then `docker compose logs api --since 5m | Select-String "access log check"` -> printed nothing
- Register the commands: `uv run --env-file .env python -m agila.bot --sync` -> 3 commands registered in the server
- Start (own window): `uv run --env-file .env python -m agila.bot` -> online, no `PrivilegedIntentsRequired` error (U7)
- `/ping` -> pong, `Database: ok`, `Ollama: ok`
- `/ask` answerable -> the passages, then the answer with Sources; `docker compose exec db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT channel, status, cardinality(chunk_ids), round(seconds::numeric, 1) FROM query_log ORDER BY id DESC LIMIT 1"'` -> `discord | answered | 3`
- `/ask` on a sourdough question -> refused; the same query -> `discord | refused | 0`
- `/save link` -> saved in 3.7 s the first time, `Already saved, unchanged` in 1.9 s (U80); `/save text` -> saved, the note appeared in `rawgila`; both check notes deleted afterwards (`agila.cli delete <id> --yes`)
- No pings (U79): a `/save text` note with `@everyone` and a real user mention displayed as text; the channel showed only an ordinary unread dot, no red mention badge, the message not highlighted -> passed
- Busy (NFR15): two `/ask` within a second from two devices -> one answered; the other showed the passages, then `Agila is answering another question right now. Try again in a minute.` The busy sentence arrives after the passages, not alone; accepted, because the guard sits on the slow answer step
- Stranger (U74): not run with a second account; covered by unit tests only
- Stop (U78): `Ctrl+C` -> clean stop. `Get-Content logsot.log -Tail 30` -> only command, result, seconds and pieces plus discord.py startup lines; no question text, titles or user IDs. Token: `$t = (Select-String -Path .env -Pattern '^DISCORD_BOT_TOKEN=(.+)').Matches[0].Groups[1].Value; Select-String -Path logsot.log -SimpleMatch $t; Remove-Variable t` -> nothing printed
- Parked limit: an unexpected error inside a command is only logged, so the user can see "thinking..." for up to 15 minutes. Candidate for a one-line reply later (not built)

## Day 12 (2026-10-28), block o part 2, block p and the Gate 2 check (commands run by Eo; results as Eo reported them)
- Block o part 2 done (commit `24587cc`): `GET /documents?status=active|archived|all` (with `source_type` and `saved_date`), `POST /documents/{id}/archive`, Discord `/list` (newest 15, `status` choice), `/archive`, `/delete` (with the `confirm` option; dry run by default). `--sync` registered 6 commands.
- Block p done (commit `10f406f`): `--private` on the CLI `text`, `markdown`, `url` and `pdf` commands; only the API channel `web` (or no `X-Agila-Channel` header) sees private documents; `discord` and `n8n` never do (search, ask, list, archive, delete); a Discord or n8n save that matches an active private document is refused with one sentence naming no title; visibility only tightens, also when a save supersedes a private copy (DEVIATIONS row 60).
- Hand checks passed in real Discord: `/ask`, `/list`, `/archive`, `/delete` and the save refusals. The private check note was deleted afterwards, and `logs\bot.log` held no trace of its text.
- Gate 2 check: the CLI `ask` cites "PDF page 1"; the vault listing shows no private-check note.
- Port 8000 blocked overnight: Windows reserved it for WinNAT (excluded range 7985-8084), so the `api` publish failed; a reboot freed it. Optional prevention (not done, command not verified): reserve port 8000 with netsh's `excludedportrange` in an elevated prompt; read `netsh int ipv4 add excludedportrange help` before running anything. The port was not changed.
- Final tests (fresh run 2026-10-28, records session): `uv run ruff check .` -> All checks passed; `uv run pytest` -> 849 passed, 165 deselected; `uv run --env-file .env pytest -m db` -> 164 passed, 850 deselected.

## Day 13 (2026-10-31), block r: n8n service and the `agila-hello` workflow (commands run by Eo; results as Eo reported them)
- Start n8n (profile only): `docker compose --profile n8n up -d n8n` -> n8n 2.45.5 started
- Editor: `http://127.0.0.1:5678` -> loaded; owner created locally (password kept out of chats)
- Memory: `docker stats agila-n8n-1 --no-stream` -> 478 MiB idle (2.43.6 was 369 to 444), 515 MiB right after a green run, 425 MiB after the failed run (one sample each)
- Credential: **Create** -> **Credential** -> **Header Auth** named `Agila API key` (as plan R-4; the value typed by Eo in the editor, never in a chat). No node or credential policy blocked the Webhook, HTTP Request or Header Auth nodes
- Workflow `agila-hello`: **Webhook** (GET, path `agila-hello`, Respond When Last Node Finishes) -> **HTTP Request** "Health" `GET http://api:8000/health` -> **HTTP Request** "Stale" `GET http://api:8000/stale`, query `limit=10`, Header Auth `Agila API key`, header `X-Agila-Channel: n8n`. The node shows Test URL `/webhook-test/agila-hello` and Production URL `/webhook/agila-hello`
- Test run: click **Execute workflow** on the canvas (not **Listen for test event** inside the Webhook node: that runs only the Webhook node, and curl gets back only the request data), then `curl.exe -s "http://127.0.0.1:5678/webhook-test/agila-hello"` -> `{"documents":[],"total":0,"formatted":"Nothing stale this week"}`; Health output `{"database":"ok","ollama":"ok"}`. Test mode answers one call per click; a second call returns 404 with a hint
- API down: `docker compose stop api`, then the test run -> the Health node is red with "The connection cannot be established, this usually occurs due to an incorrect host (domain) value"; curl -> `{"message":"Error in workflow"}`. `docker compose up -d api` -> healthy again; n8n stayed up
- Publish: the dialog asks for a Version name (required; Eo used `v1 hello check`) and an optional description. After the first publish a Production Checklist pop-up (error notifications, time saved, MCP access) appears; closed with all three off. `curl.exe -s "http://127.0.0.1:5678/webhook/agila-hello"` -> the same JSON; Executions shows #6 Succeeded in 86 ms
- Private titles (R-10): Eo has no `laptop_only` document, so this check moves to block s. The oldest saved document is from 2026-10-21, so nothing is stale before about 2026-11-20
- Export: **Workflow menu** -> **Download** as `n8n\hello.json`; `git check-ignore -v n8n/hello.json` -> names `.gitignore` and `n8n/`
- Key not in the export: `$k = (Select-String -Path .env -Pattern '^AGILA_API_KEY=(.+)').Matches[0].Groups[1].Value; Select-String -Path n8n\hello.json -SimpleMatch $k; Remove-Variable k` -> nothing printed. `Select-String -Path n8n\hello.json -Pattern 'Agila API key'` -> once, the credential name only
- No pinned data: `Select-String -Path n8n\hello.json -Pattern '"pinData": \{\s*"'` -> nothing (the file has `"pinData": {}`; the earlier pattern `\{\S` also matched that empty object, so do not use it)
- End: **Unpublish** `agila-hello`; n8n left running for block s (`docker compose stop n8n` not run)

## Day 13 (2026-10-31), block s: Workflow B, weekly digest (commands run by Eo; results as Eo reported them)
- Discord: a text channel `agila-digest` with a webhook; the webhook URL was pasted only into n8n, never into a chat
- Credential: **Create** -> **Credential** -> **Discord Webhook** named `Agila digest channel` -> the connection test passed
- Workflow `agila-digest`: **Schedule Trigger** "Every Monday 09:00" (Weeks, Monday, 9am; Settings: If Execution Is Missed = Run the Most Recent Missed Execution) and **Manual Trigger**, both feeding **HTTP Request** "Get stale list" (`GET http://api:8000/stale`, `limit=10`, Header Auth `Agila API key`, header `X-Agila-Channel: n8n`, Timeout 30000, Retry On Fail with Max Tries 2 and Wait 5000, On Error = Continue (using error output)) -> **Discord** "Post digest" (the cut expression) and, on the error output, **Discord** "Post failure". Workflow timezone Asia/Manila. Published as version `v1 weekly digest`. The editor shows "sendLegacy: undefined" under the Discord nodes; harmless
- Empty digest: `uv run --env-file .env python -m agila.cli stale` -> `Nothing stale this week`; **Execute workflow** -> Discord `Nothing stale this week`
- Throwaway notes: `"Digest check: ..." | uv run --env-file .env python -m agila.cli text --title "Digest check" --label digest-check` -> document 35; the same with `--title "Private digest check" --label private-digest-check --private` -> document 36
- Backdate both (only these two titles): `"update documents set saved_at = now() - interval '40 days' where title in ('Digest check', 'Private digest check') and status = 'active' returning id, title, visibility;" | docker compose exec -T db sh -c 'psql -U $POSTGRES_USER -d $POSTGRES_DB -At'` -> the two rows, `UPDATE 2`
- `... agila.cli stale --include-private` -> `Stale documents: 2`; `... agila.cli stale` -> only document 35
- **Execute workflow** -> Discord `Stale documents: 1.` and one line for document 35; node output only document 35; `Private digest check` appears nowhere (FR41)
- Clean up: `... agila.cli delete 35 --yes` and `... agila.cli delete 36 --yes`; then `... agila.cli stale --include-private` -> `Nothing stale this week`
- API down: `docker compose stop api`, **Execute workflow** -> Discord `Weekly digest failed: Agila's API did not answer. Run the CLI stale.` after about 14 s (one retry); Executions shows the run as Succeeded (a handled error counts as success). The error item's text was not copied. Then `docker compose up -d api` -> healthy
- Catch-up check, throwaway workflow `missed-run check` (daily **Schedule Trigger** a few minutes ahead, If Execution Is Missed = Run the Most Recent Missed Execution -> **HTTP Request** `GET http://api:8000/health`), published:
  - First attempt INVALID: `docker compose stop n8n` was run one minute AFTER the trigger time, so the schedule had already fired and nothing was missed
  - Second attempt: `docker compose stop n8n` before the trigger time, `docker compose --profile n8n up -d n8n` after it -> one execution at 15:31:28, succeeded. Its label showed the first published version name, so which of the two schedules fired is not certain (an edit after Publish stays a draft until published again); the catch-up itself is clear
  - Then unpublished and deleted
- Export (S-14): **Workflow menu** -> **Download** as `n8n\digest.json`; `git check-ignore -v n8n/digest.json` -> `.gitignore` line 34, `n8n/`
- Key not in the export: the R-12 key search on `n8n\digest.json` -> nothing printed
- Webhook token not in the export: with the webhook URL copied in Discord, `$t = (Get-Clipboard).Split('/')[-1]; Select-String -Path n8n\digest.json -SimpleMatch $t; Remove-Variable t; Set-Clipboard -Value ' '` -> nothing printed; the text `discord.com/api/webhooks` is not in the file either
- `Select-String -Path n8n\digest.json -Pattern 'Agila digest channel'` -> twice (once per Discord node), the credential name only
- No pinned data: `Select-String -Path n8n\digest.json -Pattern '"pinData": \{\s*"'` -> nothing
- Then `docker compose stop n8n`; `api` and `db` stayed healthy
- `agila-digest` stays published; n8n is stopped at the end of the day. Block t (Workflow A) not started: the 4-hour rule was reached at about 14:15, so it moves to Day 14
- Monday 2026-11-02 (Day 15, Gate 3): start n8n before 09:00 with `docker compose --profile n8n up -d n8n` to see the scheduled run; if n8n starts later that day, expect one catch-up run
