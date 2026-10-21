# Plan: Project Agila (Days 1 to 15, Oct 15 to Oct 29)

- Version: v2 (2026-10-15, after the Day 1 external review; decisions in PRD Appendix D). Backup: `plan_prev.md` (v1).
- Read first: `PROTOCOL.md`, `research_latest.md`. PRD: `docs/PRD.md` (Draft 3.3). Hours: PRD section 5 (planned 57.0 of 63 h; slack 6.0 h includes the gate checks).
- Stop rule: any failed verification stops work. Mark the step `[x] Failed (cause)`, add a line to the Lessons log in research, return to Research.
- Session rule: one block per coding session where possible; fresh session after each gate.

## Checklist with verification

### Day 1 (Oct 15): lock, no code
- 1.1 Draft 3.3 saved as `docs/PRD.md`; `decisions.md` updated. [Verification: PRD header says Draft 3.3]
- 1.2 Fresh-eyes review done; findings triaged (PRD Appendix D). Eo reads Appendix D and overrules any row. [Verification: Eo's yes or changes recorded]
- 1.3 Every in-scope FR has an acceptance sentence (PRD section 15). [Verification: spot-check FR2, FR5, FR6, FR7, FR12, FR26, FR27, FR28, FR35 (changed today)]
- 1.4 Claude Code drafts `CLAUDE.md`; Eo edits it. [Verification: Eo has read it; no secrets]
- 1.5 `.gitignore` exists (done). `git add` and commit "Add PRD, ACE files and project rules". [Verification: `git status` clean; `git log` shows the commit]
- 1.6 Board: the status log below is the board (one source of truth, no duplicate notes). Obsidian opens the project folder as the vault, so this file shows there. Sprint goal for Days 2 to 9: save text, Markdown and URLs, find their passages, and get a cited answer or a refusal from the CLI and API. [Verification: Eo can open this file in Obsidian]
- 1.7 Learning log, job-search block.

### Tier 1: Foundation (35.5 h, Days 2 to 9)
- a. (Day 2, 3.0 h) Repo, `uv`, `compose.yaml` with pinned `pgvector/pgvector`, `.env.example`, `ruff`, `pytest`, `docs/setup-log.md`; Postgres 18 volume path differs from 17 (research 2c). [Verification: restart survives; vector inserted and found with `<=>`; one passing test; U9 versions recorded]
- b. (Day 2, 1.0 h) Throwaway container calls host Ollama and a host server through `host.docker.internal` (U3); n8n alone from a pinned image, volume, `TZ=Asia/Manila`, port `127.0.0.1:5678` (U4), RAM noted. [Verification: results in research section 3; if U3 fails, decide the route with Eo (PRD section 6) before step j]
- c. (Days 2 to 3, 1.5 h) Pull `qwen3.5:4b`; `/api/show` thinking values; time a 3-chunk question with `think` default and `false`; test `format` JSON schema with the answer shape (U1, U2, U11). [Verification: numbers in setup-log; decisions recorded: thinking, num_ctx, keep_alive, whether `format` works]
- d. (Day 3, 2.0 h) Schema per PRD section 10 with `timestamptz`; numbered migrations; `db.py`. [Verification: one command builds an empty database; insert/read/clean test]
- e. (Days 3 to 4, 4.5 h) Read loop-lab `rag.py`; token-based chunker (cap 400 tokens incl. title and heading, target about 300); fastembed (U6, U10); atomic save text and Markdown; embedded text = title + heading + chunk. [Verification: FR1, FR4, FR5, FR6, FR8; a long-chunk test stays within 512 tokens]
- f. (Days 4 to 5, 3.0 h) URL save with `trafilatura`: 15 s timeout, scheme allow-list, private-address block (after redirects), 5-redirect cap, 5 MB cap, content-type check, 3-sentence rule; normalization. Save 5 real phone links as a separate sample and note results (report only). [Verification: FR2 fixtures incl. localhost, private IP, redirect-to-private, 50 MB, login wall]
- g. (Day 5, 2.5 h) Supersede with `--replace` rule for label collisions, archive, delete, list. [Verification: FR7, FR18, FR19, FR20] **Open conflict to resolve first (noted 2026-10-20):** FR7 says two different notes saved with the same label both exist, the second with a warning (unless `--replace`), but the partial unique index `documents_active_identity` allows only ONE active document per `(space_id, identity_key)`, and the identity key for text and Markdown is source type + source label. So a second active note with the same label cannot be inserted today. Block g must decide (for example a different identity key or status for the second note, or a changed index, which needs a new migration) and record it in `decisions.md`. Not built in block e.
- h. (Days 5 to 6, 2.5 h) Retrieval top 3, threshold, `/search`. [Verification: FR9, FR10, FR13; `/search` does not change `last_asked_at`]
- i. (Days 6 to 7, 5.0 h) `llm.py`: delimiters, `format` schema with `answerable`, program-copied quote, retry once, fallback, timeouts, one-call lock, injection test. [Verification: FR11, FR12, FR17, FR34; live injection test]
- j. (Days 7 to 8, 3.5 h) CLI, FastAPI with key, `/docs`, `/health` (database and Ollama), `query_log`. [Verification: FR25, FR26, FR35; U8; RAM with full stack (Day 7)]
- k. (Day 8, 2.0 h) API Dockerfile; Compose healthchecks and restart policy; port published as `127.0.0.1:8000:8000`; `pg_dump` backup script and a tested restore. [Verification: `docker compose config` shows the 127.0.0.1 publish; `/health` with Ollama stopped names Ollama; restore test passes]
- l. (Days 8 to 9, 5.0 h) Golden set (20 questions: 14 answerable, 6 not), frozen test library, eval script, tuning on the dev half (threshold, chunk size, query prefix), baseline; hand-grade the 14 answers (M10). Draft questions earlier, while saving documents on Days 3 to 6. [Verification: FR33; M1, M2, M10 reported with the honest-limits note]
- **Gate 1 (Day 9, 0.5 h):** all of the above; tag `v0.1-core`.

### Tier 2: Reach (10.5 h, Days 10 to 12)
- m. (Day 10, 2.5 h) Text PDF with `pypdf` (U5). [Verification: FR3]
- n. (Day 10, 2.0 h) Obsidian export with `export_pending` and `export --retry`. [Verification: FR28]
- o. (Days 11 to 12, 5.0 h) Discord bot: token in `.env`, allow-list, `/ping` defer, commands, splitting, `allowed_mentions` empty; start/stop/log steps in the setup log (U7). [Verification: FR27, FR40]
- p. (Day 12, 1.0 h) `--private`; private documents never reach Discord, `/stale`, the digest, the bot or n8n. [Verification: FR41]
- **Gate 2 (Day 12, 0.5 h):** tag `v0.2`.

### Tier 3: Automation and release (11.0 h, Days 12 to 15)
- q. (Day 12, 1.0 h) `/stale`. [Verification: FR39 incl. a backdated private document]
- r. (Day 12, 1.0 h) n8n spike: webhook "hello" calls the local API using the route decided in b. [Verification: green run]
- s. (Day 13, 2.5 h) Workflow B via a Discord channel webhook URL (secret in `.env`/n8n credential); workflow timezone Asia/Manila; missed-run option if the pinned version has it (U12). [Verification: FR30; with data and with none]
- t. (Days 13 to 14, 3.0 h) Workflow A (Should; first to drop). [Verification: FR29 incl. bad URL]
- u. (Day 14, 1.5 h) Exports, screenshots, demo script (unpublished, D9). [Verification: FR32]
- v. (Day 14, 2.0 h) README (host prerequisites first), LICENSE (Eo chooses), GitHub Action for `ruff` and `pytest`, fresh-clone test, backup video. [Verification: M6 under 20 minutes; demo checklist]
- **Gate 3 (Day 15, 0.5 h).**
- Day 15 slack (4.0 h): catch-up, secret scan (NFR3), tag `v1.0`. Optional only after Gate 3: w `ask-general` + stats + age warning (2.5 h, needs 3.0 h slack); x video captions (4 h, only if Workflow A was dropped; re-verify the library and its terms first).

## Block d plan: schema, migrations, db.py (Day 3, 2.0 h) - DONE 2026-10-19
Written 2026-10-19. Schema comes from PRD section 10 only (no `users`, no `space_members`). Research: V17 to V20, U17 to U19.

### Choices (confirm or change)
1. **Packages:** `uv add "psycopg[binary]" pgvector` (3.3.6 and 0.5.1 on 2026-10-19; `uv.lock` pins the exact versions). No numpy, no ORM.
2. **Settings from `.env`:** recommended `uv run --env-file .env ...`. No new dependency; `db.py` reads only `os.environ`, so the same code works inside Docker later (Compose passes the variables). Not python-dotenv. Whether `uv run` loads `.env` without the flag is unverified (U18), so every command names the flag.
3. **Migrations:** `migrations/0001_init.sql` plus a `schema_migrations(version text primary key, applied_at timestamptz not null default now())` table that the runner (not the SQL file) creates. `migrate` applies unapplied files in filename order, each file and its `schema_migrations` row in one transaction, stops at the first error, and a second run prints "nothing to apply". No advisory lock (YAGNI, one user).
4. **Tables (ids are `bigint generated always as identity`, all times `timestamptz`):**
   - `spaces(id, name not null, kind not null check in ('local','cloud'), owner_id text null)`. `owner_id` has no foreign key because `users` is backlog. The migration inserts one row: name `default`, kind `local`.
   - `documents(id, space_id not null references spaces, title not null, source_label, source_url, normalized_url, source_type not null check in ('web','pdf','text','markdown','video'), identity_key not null, content_hash not null, status not null default 'active' check in ('active','archived','superseded'), visibility not null default 'anywhere' check in ('anywhere','laptop_only'), supersedes_id references documents on delete set null, saved_at not null default now(), last_asked_at null, page_count null)`.
   - Partial unique index on `(space_id, identity_key) where status = 'active'` (FR7). `identity_key` and `content_hash` are NOT NULL so nulls cannot bypass the index.
   - `chunks(id, document_id not null references documents on delete cascade, position not null, heading, page, start_seconds null, text not null, embedding vector(384) not null, created_at not null default now(), unique (document_id, position))`. No vector index (PRD section 10).
   - `query_log(id, asked_at not null default now(), channel not null check in ('cli','web','discord'), chunk_ids bigint[] not null default '{}', status not null check in ('answered','refused','fallback'), seconds double precision not null)`. `chunk_ids` has no foreign key so deleting a document never breaks the log (FR35: no secrets, no full text).
   - `settings(key text primary key, value text not null)`; the migration inserts `embedding_model = BAAI/bge-small-en-v1.5` and `embedding_dim = 384`.
   - `create extension if not exists vector;` comes first in the file.
5. **`db.py`:** `connect()` reads `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` and calls `psycopg.connect(host=..., port=..., user=..., password=..., dbname=...)` (keyword arguments, no URL). A missing or empty variable raises an error naming the variable only. The password is never logged or put in an error message. `connect()` takes an optional `dbname` override (tests use it) and a `register=True` flag: `migrate` connects with `register=False` because the `vector` type may not exist yet (U17); everything else calls `register_vector`. The migrations folder defaults to `<project root>/migrations` and can be overridden by an argument (tests and the later API image need that). Command: `uv run --env-file .env python -m agila.db migrate`.
6. **Tests:** marker `db` declared in `pyproject.toml` with `addopts = "-m 'not db'"`, so `uv run pytest` skips them and needs no `.env` or running database; `uv run --env-file .env pytest -m db` runs them (that a command-line `-m` overrides `addopts` is U19). A fixture connects to the maintenance database `postgres`, runs `drop database if exists agila_test with (force)` and `create database agila_test`, yields settings for it, and drops it afterwards. A guard refuses to drop any database not named exactly `agila_test`; the tests never connect to `agila`.
7. **Tests (7 `db`, 1 plain):** (a) migrate on an empty database creates all tables plus the default space and settings rows; (b) a second run applies nothing; (c) insert a document and a chunk with a 384-number vector and read both back; (d) the same vector gives `<=>` distance 0; (e) deleting the document removes its chunks; (f) an invalid `status` is rejected; (g) the `saved_at`, `last_asked_at`, `created_at`, `asked_at` and `applied_at` columns have type `timestamp with time zone`. Plain test: with `POSTGRES_HOST` unset and a fake password set, `connect()` raises an error that names `POSTGRES_HOST` and does not contain the password.

### Files
| File | Action | Purpose |
| --- | --- | --- |
| `migrations/0001_init.sql` | create | Creates the extension, the five tables, their constraints, the partial unique index, and the default space and settings rows. |
| `src/agila/db.py` | create | Opens a Postgres connection from environment variables and applies the numbered migration files (`python -m agila.db migrate`). |
| `tests/test_db.py` | create | Holds the throwaway `agila_test` fixture, the seven `db` tests and the missing-variable test. |
| `pyproject.toml` | edit | Adds `psycopg[binary]` and `pgvector`, declares the `db` marker and skips it by default. |
| `.env.example` | edit | Adds `POSTGRES_HOST=127.0.0.1` and `POSTGRES_PORT=5433` (no secrets; `.env` itself is never touched). |
| `docs/setup-log.md` | edit | Records the verified commands and versions for block d (after it passes). |
| `docs/ace/research_latest.md` | edit | Records the outcome of U17 to U19 (after they are run). |
| `docs/ace/plan_latest.md` | edit | Ticks d in the status log (after it passes). |

`compose.yaml` stays as it is: its port is already `127.0.0.1:5433:5432`. The earlier research note planned `scripts/migrate.py`; this plan uses `python -m agila.db migrate` (your instruction), one file less.

### Verification commands (in order, from the project folder in PowerShell)
1. `uv add "psycopg[binary]" pgvector`, then `uv run python -c "import psycopg, pgvector; print(psycopg.__version__)"` prints 3.3.x.
2. `docker compose up -d`, then `docker compose ps` shows `db` healthy.
3. `uv run ruff check .` passes.
4. `uv run pytest` passes with the `db` tests deselected.
5. `uv run --env-file .env pytest -m db -v` passes; afterwards `docker compose exec db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "\l"'` shows no `agila_test` database.
6. `uv run --env-file .env python -m agila.db migrate` reports 0001 applied; the same command again reports nothing to apply; `docker compose exec db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "\dt"'` lists the five tables plus `schema_migrations`.
7. `uv run --no-env-file python -m agila.db migrate` fails with a message naming the first missing variable and showing no value.
8. U17, U18 and U19 each get one recorded result in research section 3. Then ruff and pytest again, and commit.
Stop rule: any failing step stops the block; mark `d` as `[x] Failed (cause)` and add a lesson.

### Questions for Eo
1. Include the reserved values `cloud` (space kind) and `video` (source type) in the CHECK lists? Recommended yes: the PRD names them, and adding one later needs a new migration. Say no and I leave them out.
2. `owner_id` as plain nullable text with no foreign key (users are backlog): OK?
3. OK to make `identity_key` and `content_hash` NOT NULL? The PRD does not say; a null would let duplicates past the FR7 index.
4. Confirm `uv run --env-file .env` instead of python-dotenv.

## Block e part 2 plan: embed and save text and Markdown - DONE 2026-10-20
Written 2026-10-20. Part 1 (FR5, `chunking.py`) is done. Facts: research V26 to V30 (embed call, batch size, storing vectors, no passage prefix, PRD requirements). Nothing outside this list gets built; supersede and `--replace` are block g, URLs are block f.

### Steps (each ends with `uv run ruff check .`, `uv run pytest`, and for DB steps `uv run --env-file .env pytest -m db`)
1. **`src/agila/embed.py`: chunks to vectors (FR6).** `embed_chunks(title, chunks, embedder=None) -> list[ndarray]` builds each string with `chunking.embedded_text(title, chunk.heading, chunk.text)` and calls `passage_embed(texts)` (default batch size, no instruction prefix; V26, V27, V29). The default embedder is `TextEmbedding(MODEL_NAME, cache_dir=str(CACHE_DIR))`, loaded once. It checks every vector is `float32` with shape `(384,)` and raises a readable error otherwise. *Proves FR6.*
2. **`src/agila/library.py`: the two saves (FR1, FR4, FR8; FR7 keys only).** `save_text(conn, title, source_label, text, embedder=None)` and `save_markdown(conn, path, title=None, source_label=None, embedder=None)`, sharing one private `_save(...)`:
   - *Before the transaction:* normalise line endings, chunk with `chunk_document`, embed. Nothing touches the database yet, so a chunking or embedding error leaves nothing.
   - *In ONE transaction (`with conn.transaction():`):* find the `default` space id; insert the `documents` row (`source_type` `text` or `markdown`, `identity_key`, `content_hash`, `status` `active`, `visibility` `anywhere`); insert every `chunks` row with its vector (a numpy array passed straight in, V28). The commit happens only when the block ends without error. *Proves FR8.*
   - *Identity key and hash (FR7 rules, stored only):* `identity_key = f"{source_type}:{source_label}"` (PRD: source label plus source type); `content_hash` = SHA-256 hex of the text after line endings are normalised to `\n` (assumed: hash the whole text, not the chunks).
   - *Returns* the new document id and chunk count. An input that gives zero chunks (empty text, front matter only) is refused with a readable one-sentence error and nothing is saved (assumed; FR5 says empty input must not crash).
   - *Markdown title/label defaults (assumed):* title = first `# ` heading if any, else the file name without extension; source label = the file name. For `save_text` both title and label are required (FR1: "with a title and source label"). *Proves FR1 and FR4.*
3. **Same identity already active: what the save does today (QUESTION Q1).** The partial unique index `documents_active_identity` makes the second insert fail. Proposal: catch that error inside `_save`, let the transaction roll back, and raise a readable sentence: "Already saved: <label>. Replacing a saved item comes later (block g)." Same wording whether the content is identical or changed; nothing is written, nothing is replaced, and no "already saved, unchanged" shortcut yet. This does NOT meet FR7's "new document with a warning" or "unchanged" behaviours; those wait for block g. Eo confirmed (Q1, 2026-10-20): keep the plain error; no hash comparison and no "unchanged" message.
4. **Smallest command line (QUESTION Q2, assumed).** The PRD says only that the CLI has "save, ask, search, list, ..." (FR25, built in block j, and calls the API). Until then, proposal: `src/agila/ingest.py` with `python -m agila.ingest text --title T --label L [--file PATH | stdin]` and `python -m agila.ingest markdown PATH [--title T] [--label L]`, run as `uv run --env-file .env python -m agila.ingest ...`. It calls `library.py` directly, prints one sentence ("Saved <title>: N chunks") or the error sentence, and no stack trace (NFR7). It holds no search or answer logic and is replaced by the real CLI in block j.
5. **Tests.** Plain tests (no database, no Ollama, no network) use a fake embedder that returns 384-number float32 vectors; `db` tests are marked `db` and use the throwaway `agila_test` database through the existing fixture (extended with a `migrated_db` helper if `test_db.py` has none to reuse).
   - `tests/test_embed.py` (plain): fake embedder gets exactly `title + heading + text` strings, in order, with no prefix (FR6); a vector of the wrong length or dtype is rejected; one real-model test (skipped if `.cache/fastembed` is missing, like part 1) embeds a chunk and checks `float32` and `(384,)`.
   - `tests/test_library.py` (`db`): (a) FR1: save text with title and label, then the document exists with that title, label, `source_type` `text`, and its chunk rows exist; (b) FR4: save a Markdown file with 3 headings, at least 3 chunks, each starting at its heading, document listed; (c) FR6: each stored embedding has 384 numbers (`.to_numpy().shape == (384,)`) and `settings` has `embedding_model` = `BAAI/bge-small-en-v1.5` and `embedding_dim` = `384`; (d) FR6 long chunk: a long paragraph with a long title and heading, every stored chunk's `embedded_text` counted with the real tokenizer is at most 512 tokens (the cap is 400); (e) FR8: a fake embedder returns a wrong-length vector for the 2nd chunk, so the insert fails after the document row and the first chunk row were written inside the transaction, and afterwards `documents` and `chunks` both have 0 rows; (f) identity key and hash are stored as specified; (g) empty text is refused and writes nothing; (h) a second save with the same label gives the readable "Already saved" error and leaves exactly one document (Q1).
   - `tests/test_ingest.py` (plain): the command prints one sentence for a missing file and for a missing variable, and no traceback.
6. **Cleanup and records.** Delete the temporary `scripts/embed_spike.py` and `scripts/token_count_spike.py` (the note of 2026-10-19 says to do so once `embed.py` and the chunker exist; `scripts/ollama_spike.py` stays until `llm.py`). Add the verified commands to `docs/setup-log.md`, tick e in the status log, `ruff` and `pytest` pass. No commit until Eo says so.

### Files
| File | Action | Purpose |
| --- | --- | --- |
| `src/agila/embed.py` | create | Turns chunks into 384-number vectors with the local model, no instruction prefix. |
| `src/agila/library.py` | create | Saves pasted text or a Markdown file as one document with its chunks and vectors in a single transaction. |
| `src/agila/ingest.py` | create | Temporary command line for the two saves until the real CLI exists (block j). |
| `tests/test_embed.py`, `tests/test_library.py`, `tests/test_ingest.py` | create | Prove FR1, FR4, FR6 and FR8 as listed in step 5. |
| `scripts/embed_spike.py`, `scripts/token_count_spike.py` | delete | Throwaway spikes replaced by `embed.py` and `chunking.py`. |
| `docs/setup-log.md`, `docs/ace/plan_latest.md` | edit | Verified commands; status tick. |

### Verification commands (in order, PowerShell, from the project folder)
1. `uv run ruff check .` and `uv run pytest` pass (plain tests only).
2. `docker compose up -d`, `docker compose ps` shows `db` healthy.
3. `uv run --env-file .env pytest -m db -v` passes, then `agila_test` is gone (`docker compose exec db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "\l"'`).
4. By hand on the real database: `uv run --env-file .env python -m agila.ingest markdown <a real .md file>` prints "Saved ...: N chunks"; the same command again prints the "Already saved" sentence; `docker compose exec db ... -c "select count(*) from chunks"` matches N. Delete that test document afterwards by hand (Eo's call; there is no delete command until block g).
Stop rule: any failing step stops the block; mark it `[x] Failed (cause)` and add a lesson.

**Answers (Eo, 2026-10-20):** Q1 plain "Already saved" error, no hash comparison, no "unchanged" message. Q2 yes, `agila.ingest` stays as a temporary command line (assumed) until block j. Q3 yes: Markdown title = first `# ` heading, else the file name without extension; Markdown source label = the file name WITH extension (e.g. `notes.md`). Q4 yes: zero chunks gives one readable sentence and nothing is written.
### Questions for Eo (answered above)
- **Q1** (step 3): when an active document with the same identity exists, the save fails with a readable error and writes nothing, for identical and changed content alike. OK for now, or should an identical-hash save already say "already saved, unchanged" (a hash comparison, but still no supersede)?
- **Q2** (step 4): OK to add the temporary `agila.ingest` command line, calling `library.py` directly, or do you prefer no command line until block j (tests only)?
- **Q3** (step 2): `save_text` requires both title and label (FR1). For Markdown, are the defaults (title = first `# ` heading else file name; label = file name) OK?
- **Q4** (step 2): refuse input that gives zero chunks with a readable error. OK?

## Block f part 1 plan: save a URL, TODAY only - APPROVED 2026-10-20 (answers below)
Written 2026-10-20. Research: V31 to V36, U20 to U23. Goal for today: `save_url` in the library, with URL checking and normalization, our own download with `httpx`, trafilatura only for text extraction, the text rules, and the block e atomic save. The private-address block, redirect handling, size cap, content-type check, chunk cap and the 5 real links are DAY 5 (step 9).

### Decisions taken (Eo, from the F1 research)
- **U20 decided:** we download with `httpx` and give trafilatura only the HTML string (`trafilatura.extract`). Not trafilatura's downloader, because its timeout is per step (a 2 s setting took 8 s, V34), every failure is the same `None` so no readable sentence is possible, it retries without certificate checks by default (V33), and the content type is known only after the whole body is downloaded.
- **Total timeout:** 15 seconds of wall-clock time for the whole download, enforced by our code.
- **U22 decided, PRD rules only** (V35): see step 2.
- **U23 decided:** reject when the extracted text is `None`, under 200 characters, or under 3 sentences (assumed in FR2); one readable sentence per failure.

### Answers (Eo, 2026-10-20) and changes they cause
- **Q1 yes:** no `ingest url` command today; `save_url` lives in the library and the tests only.
- **Q2 yes, on three conditions:** (a) a sync wrapper around `asyncio.run` for the sync callers: `fetch_html(...)` is the sync function, `fetch_html_async(...)` holds the work; (b) Python version stated: the project requires Python >= 3.12 (`requires-python`) and runs on 3.12.x; `asyncio.timeout` needs 3.11 or newer; (c) the docstring of `fetch_html` says it must NOT be called from inside a running event loop, and the function checks this and raises a readable `FetchError` instead of asyncio's obscure error. There is a test for it.
- **Q3 yes:** title = `--title`, else the verified page title, else the normalized URL.
- **Q4 yes, marked assumed:** sentence rule and whitespace-collapsed character count as in step 4. Added: a test that `3.5` and `e.g.` do not break the rule. To make that true, a piece with fewer than 3 words is joined to the previous piece (or to the next one if it is the first) before counting; so `e.g.` cannot create a sentence and `3.5` (no space after the dot) is never a split point.
- **Q5 yes:** `http://x.com/` becomes `http://x.com`.
- **Q6 yes:** a redirect is refused with a readable sentence until Day 5.
- **Fixtures:** small saved HTML files in `tests/fixtures/` that Eo can open and read.

### Where the URL is stored on the document
`documents.source_url` = the URL exactly as given; `documents.normalized_url` = the normalized form (step 2); `documents.identity_key` = the same normalized URL (PRD FR7); `documents.source_label` = the normalized URL; `source_type` = `web`. No URL is stored on `chunks`.

### Steps (each ends with `uv run ruff check .`, `uv run pytest`, and for DB steps `uv run --env-file .env pytest -m db`)
1. **Dependencies.** `uv add httpx trafilatura`, which declares `httpx` (a transitive dependency today, V36: locked 0.28.1) and adds trafilatura (2.3.1 and 13 more packages, V31). Pin as `httpx>=0.28.1` and `trafilatura>=2.3.1`. Record the installed versions in `docs/setup-log.md`. Then verify two things not yet verified, and record them as V rows before relying on them: (a) `trafilatura.extract_metadata(html).title` returns the page title on a made-up page (used for the document title, Q3); (b) `httpx.AsyncClient` works with `asyncio.timeout` in this project (httpx needs `anyio`, check it is installed). If (a) fails, the title falls back to the normalized URL. *Proves: the plan rests on verified facts (PROTOCOL rule 6).*
2. **`src/agila/urls.py`: check and normalize (FR2 scheme rule, FR7).** `normalize_url(url) -> str`, standard library only (`urllib.parse`). Rules, exactly:
   - lowercase the scheme and the host;
   - drop the fragment (everything after `#`);
   - drop query parameters named `utm_*`, `fbclid` or `gclid`, names compared case-insensitively; all other parameters stay, in their original order, with their original text; if none remain the `?` goes too;
   - strip the trailing slash from the path (`/a/b/` becomes `/a/b`; a root path `/` becomes empty, so `http://x.com/` and `http://x.com` are the same);
   - nothing else: path case kept, parameter order kept, `www.` kept, `http` stays `http`, ports untouched.
   `check_url(url)` raises `UrlError` (one readable sentence) for anything that is not `http` or `https` (for example `ftp:`, `file:`, `javascript:`), has no host (`http://`, `http//example.com`, `example.com`), or is empty; a typo scheme such as `htp://` is covered by the same rule. *Proves: the allow-list part of FR2 and the identity key of FR7.*
   **Not normalized yet (V35 list; left as is on purpose):** (a) query parameter order; (b) default ports `:80` and `:443` and `http` versus `https`; (c) the other tracking parameters (`ref`, `mc_cid`, `igshid`, and so on); (d) a `www.` prefix; (e) percent-encoding case and non-ASCII (internationalized) hosts; (f) `user:password@` in the URL; (g) path case (two paths that differ only in case are different pages); (h) repeated slashes and `index.html`; (i) `#!` routes (dropped as fragments, so two such pages look the same). Two URLs that differ in any of these get two different identity keys.
3. **`src/agila/web.py`: the download, `fetch_html(url, timeout=15.0, transport=None) -> str` (FR2 timeout).** Uses `httpx.AsyncClient` inside `asyncio.run`, with the whole request and body read wrapped in `asyncio.timeout(timeout)`, so 15 seconds is a TOTAL limit (not per step). Certificate verification stays on (httpx default; there is no fallback to unverified connections). `follow_redirects=False` today, so a redirect cannot reach an unchecked address: a 3xx answer raises `FetchError("The page redirects; redirects are not supported yet.")` until Day 5. Other failures raise `FetchError` with one sentence each: timeout ("The page took longer than 15 seconds."), connection or DNS error, a non-200 status ("The page answered with status 404."), a body that is not valid text. `transport=` lets tests pass `httpx.MockTransport` (no network, no server). There is no size cap and no content-type check yet (Day 5). *Proves: FR2 timeout and readable errors.*
4. **`src/agila/web.py`: the text rules, `extract_page(html) -> (title, text)`.** Calls `trafilatura.extract(html)` and applies, in order: `None` or empty is rejected ("No readable text found on the page."); fewer than 200 characters is rejected; fewer than 3 sentences is rejected ("The page has too little text to save."). **How things are counted [assumed, FR2]:** characters = the length of the text after runs of whitespace are collapsed to one space and the ends are trimmed; sentences = split the text at `.`, `!` or `?` followed by whitespace, and at line breaks; a piece counts as a sentence only if it has at least 3 words. So a menu line like "Home" or "About us" never counts. *Proves: the 200-character and 3-sentence rules of FR2 (V32: `extract` alone returned junk for a menu-only page).*
5. **`src/agila/library.py`: `save_url(conn, url, title=None, fetcher=fetch_html, embedder=None) -> Saved` (FR2, FR7 keys, FR8).** Order: `check_url` (a bad URL never reaches the fetcher), `normalize_url`, `fetcher(url)`, `extract_page`, then the existing chunk, embed and ONE-transaction save from block e, so a rejected page stores nothing. `_save` is generalised by keyword arguments (`source_type`, `identity_key`, `source_url`, `normalized_url`, `source_label`) and `save_text` and `save_markdown` keep working unchanged. For a web page: `source_type` `web`; `source_url` = the URL as given; `normalized_url` = step 2 result; `identity_key` = the normalized URL (PRD FR7); `source_label` = the normalized URL; `content_hash` = SHA-256 of the extracted text (not of the HTML); title = `--title` if given, else the page title (step 1a), else the normalized URL. A second save of an active identity gives the same plain "Already saved: <normalized URL>" error as block e (Q1 of block e: no hash comparison, no "unchanged" message, no supersede; that is block g). `fetcher` is a parameter so tests pass a fake. *Proves: FR2, FR7 (key only), FR8.*
6. **Fixtures (made up by us, saved in `tests/fixtures/`).** `article.html` (menu, a short article of several sentences, footer), `menus.html` (a page that is almost all menu links and a cookie banner), `empty.html` (no text). No live website is used. Because the fixtures are invented, a pass proves our rules, not how real pages behave (that is the 5 real links, Day 5). If trafilatura's output on a fixture surprises us, the output is recorded in research before any rule is changed.
7. **Tests (all offline).**
   - `tests/test_urls.py` (plain): a table of normalization cases (uppercase scheme and host; fragment dropped; `utm_source`, `UTM_Medium`, `fbclid`, `GCLID` dropped while `id=7` and `q=a` stay in order; trailing slash on `/a/b/`, on `/`, and before a query `/a/?x=1`; path case kept; `www.` kept; port `:8080` and `:80` kept; `http` kept; a URL whose only parameters are tracking ends with no `?`); the unhandled cases from step 2 each pinned as "not changed" so a later change is deliberate; allow-list cases (`ftp://`, `file:///`, `javascript:`, `htp://example.com`, `http//example.com`, `example.com`, empty, `http://`).
   - `tests/test_web.py` (plain): `fetch_html` with `httpx.MockTransport` (200 returns the text; 404, a redirect, a connection error and a stalled answer each give their one sentence; the stall test uses `timeout=0.2` and an async handler that sleeps, and checks it ends in about 0.2 s); `extract_page` on the three fixtures (article returns the article text without the menu text; menus page and empty page are rejected with the right sentence) and on small strings that sit just under and just over 200 characters and 3 sentences.
   - `tests/test_library.py` (`db`, throwaway `agila_test`), added to the existing file: `save_url` with a fake fetcher returning the article fixture stores a `web` document with the right `source_url`, `normalized_url`, `identity_key`, title and chunks, and no chunk contains the menu text; the menus and empty fixtures raise `SaveError`-style readable errors and leave `documents` and `chunks` empty; a typo URL gives a readable error and the fake fetcher is never called; a fetcher that raises `FetchError` stores nothing; the same URL saved twice with different tracking parameters gives "Already saved" and exactly one document (the second half of the FR7 acceptance sentence, key only).
8. **Records.** Verified commands and versions in `docs/setup-log.md`; V and U rows for step 1 in research; tick `f part 1` in the status log only after all checks pass. No commit until Eo says so.
9. **DAY 5, not today (U21):** the private-address and `localhost` block (checked again after every redirect), following redirects with a cap of 5, the 5 MB cap while reading, the HTML-or-plain-text content-type check, the 200-chunk cap, the login-wall fixture, the 50 MB and redirect-to-private tests of the FR2 acceptance sentence, the `ingest url` command (see Q1), and the 5 real links saved as a report-only sample.

### Files
| File | Action | Purpose |
| --- | --- | --- |
| `pyproject.toml`, `uv.lock` | edit | Declare `httpx` and add `trafilatura` (step 1). |
| `src/agila/urls.py` | create | Checks that a URL is `http` or `https` and builds the normalized form used as the identity key. |
| `src/agila/web.py` | create | Downloads a page with a 15-second total limit and extracts its readable text, with one-sentence failures. |
| `src/agila/library.py` | edit | Adds `save_url`; generalises `_save` so text, Markdown and web pages share one atomic save. |
| `tests/fixtures/article.html`, `menus.html`, `empty.html` | create | Made-up pages for the extraction tests. |
| `tests/test_urls.py`, `tests/test_web.py` | create | Plain tests for normalization, the allow-list, the download errors and the text rules. |
| `tests/test_library.py` | edit | Adds the `save_url` database tests. |
| `docs/setup-log.md`, `docs/ace/research_latest.md`, `docs/ace/plan_latest.md` | edit | Versions and commands, new V rows, status tick. |

### Verification commands (in order, PowerShell, from the project folder)
1. `uv add httpx trafilatura`, then `uv run python -c "import httpx, trafilatura; print(httpx.__version__, trafilatura.__version__)"` prints `0.28.1 2.3.1` (or newer if resolution moved).
2. `uv run ruff check .` and `uv run pytest` pass (the plain tests: urls, web, extraction).
3. `docker compose up -d`, `docker compose ps` shows `db` healthy.
4. `uv run --env-file .env pytest -m db -v` passes, then `agila_test` is gone (`docker compose exec db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "\l"'`).
5. No network is used by any test: run `uv run pytest` once with the network off (as in U6) and see the same result.
Stop rule: any failing step stops the block; mark it `[x] Failed (cause)` and add a lesson.

### Questions for Eo
- **Q1:** Until Day 5 there is no private-address block, size cap or content-type check, so I propose NO `ingest url` command today: `save_url` exists only in the library and the tests, and the command line gets it on Day 5 after the block. Otherwise a typed `http://localhost` or a huge file would be fetched. OK?
- **Q2:** The 15-second total limit uses `httpx.AsyncClient` with `asyncio.timeout`, run from our normal code with `asyncio.run`. The alternative is a worker thread, which cannot cancel a stuck read. OK to use asyncio (needs the step 1 check)?
- **Q3:** Document title for a web page: the `--title` argument, else the page title from trafilatura (to be verified in step 1), else the normalized URL. OK?
- **Q4:** The sentence rule (a piece of at least 3 words, split at `.`, `!`, `?` or a line break) and the character count (whitespace collapsed) are my proposal and marked assumed. OK, or do you prefer a stricter or looser rule?
- **Q5:** The root URL `http://x.com/` becomes `http://x.com` (the trailing slash of `/` is stripped, so both forms are one document). OK?
- **Q6:** Today a redirect is refused with "redirects are not supported yet" (no following without a re-check). Many real pages redirect (for example `http` to `https`), so real links fail until Day 5. OK?

## Status log
Legend: `[ ]` not started, `[~]` in progress, `[x]` done, `[x] Failed (cause)`.
- [x] 1.1 Draft 3.3 saved; [x] 1.2 review triaged and accepted by Eo; [x] 1.3 acceptance sentences cover every in-scope FR (NFR15, NFR16 added); [x] 1.4 `CLAUDE.md` drafted (Eo to read and edit); [x] 1.5 commit 81ca19f; [x] 1.6 board decision
- [ ] 1.7 learning log and job-search block (Eo)
- [ ] Day 2 (Oct 16): runbook written (Claude Docs "Project Agila: Day 2 Runbook"); a, b, c(start) not started. Note: Eo installed qwen3.5:9b; block c times 9b and 4b, Eo decides after the table (D3 to be revisited). n8n tag seen on Docker Hub 2026-10-16: 2.43.6 (research log said 2.42.7 on Oct 12).
- [~] a (2026-10-17): uv project, pyproject/ruff, compose.yaml, .env.example, smoke test, setup-log done; ruff and pytest pass. [x] Failed (Docker daemon not running: restart test and `<=>` vector test not run). Resume after Docker Desktop is started.
- [~] Docker engine fixed (2026-10-17): `docker compose up -d` now pulls the image; next failure is host port 5432 refused by Windows (runbook A4). Resume: check netsh excluded ranges, change host port in compose.yaml, rerun A4.
- [ ] Docker fix (2026-10-17): runbook Step 0 added (diagnose, install or start Docker Desktop with the WSL 2 engine, gate `docker run --rm hello-world`); research U13. Decision: all Agila commands run in Windows PowerShell, not Ubuntu. Resume block a at A4 after the gate.
- [x] Docker engine and port (2026-10-17 16:12): `agila-db-1` healthy on host port 5433 (5432 held by Eo's local Windows PostgreSQL). Remaining in block a: vector `<=>` test, restart test, versions in setup-log, commit. Day 3 db code and tests must use port 5433.
- [x] a (2026-10-17): vector `<=>` test and restart test passed, versions in setup-log, ruff and pytest pass; committed.
- [x] b (2026-10-17): U3 and U4 passed, results in research section 3 and setup-log.
- [x] c (2026-10-17, ticked 2026-10-19 after Eo confirmed D3: 4b default, 9b optional): think timing done for one question (U1, U2 partial); `/api/show` done (C1, 2026-10-19); `format` test done (C2, 2026-10-19, U11 passed, see setup-log); the 10-question run (C3) done 2026-10-19 (first run: 4b median 4.2 s, 9b 9.9 s, 9/10 each; lean 4b; see setup-log); run 2 (2026-10-19): 10/10 each, 4b median 4.5 s, 9b 13.1 s, so the run-1 misses were random and 4b is the recommended default. Remaining for Eo: confirm the model choice (D3) and tick c.
- [x] C1 to C5 (2026-10-19 16:33): `/api/show`, `format` test, 10-question runs, keep_alive and `num_ctx`, decisions recorded (decisions.md, research U1/U2/U11, new U14 to U16). Block c was ticked `[x]` on 2026-10-19 after Eo confirmed D3 (see the c line above). `scripts/ollama_spike.py` is temporary: delete once `llm.py` exists.
- [x] d (2026-10-19): `0001_init.sql`, `db.py`, `tests/test_db.py` done; ruff and pytest pass, 7 db tests pass, migrate twice = no-op, U17 to U19 resolved. Committed 45b74fc, 3d53797.
- Note (2026-10-19): `scripts/embed_spike.py` and `scripts/token_count_spike.py` were temporary spike code (U6, V21 to V24); deleted 2026-10-20 now that `embed.py` and the chunker exist.
- [x] e part 1 (2026-10-19): done: `src/agila/chunking.py` and `tests/test_chunking.py` (18 tests; ruff and pytest pass). Remaining: embedding module, atomic save of text and Markdown, the 512-token check on stored chunks. Part 2 plan written 2026-10-20 (section "Block e part 2 plan"), waiting for Eo's approval and answers to Q1 to Q4.
- [x] e (2026-10-20): token-based chunker, embedding and atomic save of text and Markdown done and verified by hand on the real database (Markdown save: 3 chunks of 384 numbers; `settings` holds `BAAI/bge-small-en-v1.5` and 384; the duplicate save said "Already saved"; the two test documents were then deleted, library back to 0 documents and 0 chunks). Files: `chunking.py`, `embed.py`, `library.py`, `ingest.py` (temporary CLI, assumed). Proof by test (all under `tests/`): FR1 `test_library.py::test_save_text_stores_document_and_chunks` and `::test_save_text_needs_title_and_label`; FR4 `test_library.py::test_save_markdown_chunks_start_at_headings` and `::test_markdown_defaults_are_first_h1_and_file_name`; FR5 (part 1) `test_chunking.py` (18 tests incl. `test_real_tokenizer_keeps_every_chunk_at_or_under_400`); FR6 `test_library.py::test_embedding_has_384_numbers_and_settings_names_the_model`, `::test_long_chunks_embedded_text_is_within_512_tokens` and `test_embed.py::test_embedder_gets_title_heading_text_with_no_prefix`; FR8 `test_library.py::test_failure_inside_the_transaction_leaves_nothing`. Checks 2026-10-20: ruff clean, `pytest` 33 passed, `pytest -m db` 20 passed. Research rows V26 to V30. Open for later: FR7 supersede and the same-label conflict (block g), `agila.ingest` prints the file name, not the stored title, when `--title` is absent.
- [x] f part 1 (2026-10-20): `urls.py`, `web.py`, `save_url` in `library.py`, fixtures `article.html`, `menus.html`, `empty.html`, `tests/test_urls.py`, `tests/test_web.py` and the `save_url` tests in `tests/test_library.py` done; `ruff` clean, `pytest` 107 passed, `pytest -m db` 30 passed, plain suite also passes with non-loopback connections blocked. Proof: scheme allow-list and typo URLs `test_urls.py::test_bad_links_are_refused_with_one_sentence` and `test_library.py::test_a_typo_url_is_refused_before_any_download`; normalization `test_urls.py::test_normalization_rules`, `::test_unhandled_cases_stay_as_they_are`, `::test_tracking_parameters_do_not_change_the_identity`; total 15 s limit `test_web.py::test_total_time_limit_cancels_a_stalled_answer`; sync wrapper `::test_fetch_html_refuses_to_run_inside_an_event_loop`; text rules `::test_199_characters_fail_and_200_pass`, `::test_two_sentences_fail_and_three_pass`, `::test_a_decimal_number_does_not_split_a_sentence`, `::test_an_abbreviation_does_not_create_a_sentence`; three fixtures `::test_article_fixture_gives_its_text_without_the_menu`, `::test_menus_fixture_is_rejected`, `::test_empty_fixture_is_rejected`; atomic save `test_library.py::test_thin_pages_are_rejected_and_store_nothing` and `::test_a_failed_download_stores_nothing_and_keeps_its_sentence`; identity `::test_save_url_stores_a_web_document_with_its_urls` and `::test_same_url_with_other_tracking_parameters_is_already_saved`. NOT done (Day 5, step 9 of the plan): private-address block, redirects with a cap of 5, 5 MB cap, content-type check, 200-chunk cap, login-wall fixture, the `ingest url` command, the 5 real links. Block f itself stays open.
- [ ] f, g, h, i, j, k, l, Gate 1
- [ ] m, n, o, p, Gate 2
- [ ] q, r, s, t, u, v, Gate 3, Day 15 tasks, w, x (optional)

## Drop order if behind (from PRD)
Optional (w, x); Workflow A; Discord commands other than `/ask` and `/save`; Obsidian export. Never drop Tier 1.
