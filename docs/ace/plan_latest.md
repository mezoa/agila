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

## Block d plan: schema, migrations, db.py (Day 3, 2.0 h) - PLAN ONLY, waiting for Eo's approval
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

## Block e part 2 plan: embed and save text and Markdown - PLAN ONLY, waiting for Eo's approval
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

### Answers (Eo, 2026-10-20): Q1 plain "Already saved" error, no hash comparison, no "unchanged" message. Q2 yes, `agila.ingest` stays as a temporary command line (assumed) until block j. Q3 yes: Markdown title = first `# ` heading, else the file name without extension; Markdown source label = the file name WITH extension (e.g. `notes.md`). Q4 yes: zero chunks gives one readable sentence and nothing is written.
### Questions for Eo (answered above)
- **Q1** (step 3): when an active document with the same identity exists, the save fails with a readable error and writes nothing, for identical and changed content alike. OK for now, or should an identical-hash save already say "already saved, unchanged" (a hash comparison, but still no supersede)?
- **Q2** (step 4): OK to add the temporary `agila.ingest` command line, calling `library.py` directly, or do you prefer no command line until block j (tests only)?
- **Q3** (step 2): `save_text` requires both title and label (FR1). For Markdown, are the defaults (title = first `# ` heading else file name; label = file name) OK?
- **Q4** (step 2): refuse input that gives zero chunks with a readable error. OK?

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
- [ ] f, g, h, i, j, k, l, Gate 1
- [ ] m, n, o, p, Gate 2
- [ ] q, r, s, t, u, v, Gate 3, Day 15 tasks, w, x (optional)

## Drop order if behind (from PRD)
Optional (w, x); Workflow A; Discord commands other than `/ask` and `/save`; Obsidian export. Never drop Tier 1.
