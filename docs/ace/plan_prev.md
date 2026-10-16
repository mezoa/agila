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
- g. (Day 5, 2.5 h) Supersede with `--replace` rule for label collisions, archive, delete, list. [Verification: FR7, FR18, FR19, FR20]
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

## Status log
Legend: `[ ]` not started, `[~]` in progress, `[x]` done, `[x] Failed (cause)`.
- [x] 1.1 Draft 3.3 saved; [x] 1.2 review triaged and accepted by Eo; [x] 1.3 acceptance sentences cover every in-scope FR (NFR15, NFR16 added); [x] 1.4 `CLAUDE.md` drafted (Eo to read and edit); [x] 1.5 commit 81ca19f; [x] 1.6 board decision
- [ ] 1.7 learning log and job-search block (Eo)
- [ ] a, b, c, d, e, f, g, h, i, j, k, l, Gate 1
- [ ] m, n, o, p, Gate 2
- [ ] q, r, s, t, u, v, Gate 3, Day 15 tasks, w, x (optional)

## Drop order if behind (from PRD)
Optional (w, x); Workflow A; Discord commands other than `/ask` and `/save`; Obsidian export. Never drop Tier 1.
