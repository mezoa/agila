# Plan: Project Agila (Days 1 to 15, Oct 15 to Oct 29)

- Version: v1 (2026-10-15). Backup: none yet.
- Read first: `PROTOCOL.md`, `research_latest.md`. PRD: `docs/PRD.md` (Draft 3.2). Hours are from PRD section 5.
- Stop rule: any failed verification stops work. Mark the step `[x] Failed (cause)`, add a line to the Lessons log in research, return to Research.
- Session rule: one block per coding session where possible; start a fresh session after each gate.

## Checklist with verification

### Day 1 (Oct 15): lock, no code
- 1.1 Save Draft 3.2 as `docs/PRD.md`; update `docs/decisions.md`. [Verification: files exist; PRD header says Draft 3.2]
- 1.2 Review step: fresh-eyes chat reads PRD 3.2 and this plan; accept/reject each finding. [Verification: findings list with a decision on each]
- 1.3 Acceptance sentences exist for every in-scope FR (PRD section 15). [Verification: every FR in sections 8 Tier 1 to 3 appears in section 15]
- 1.4 Claude Code drafts `CLAUDE.md` (Python with uv, run ruff and pytest before each commit, never touch `.env`, read `docs/ace/PROTOCOL.md` first, loop-lab is read-only). Eo reads and edits it. [Verification: Eo has read it; no secrets inside]
- 1.5 `.gitignore` lists `.env`, `raw/`, `.obsidian/`, `.venv/`, `n8n/` exports if public. `git add`, commit "Add PRD, ACE files and project rules". [Verification: `git status` clean; `git log` shows the commit]
- 1.6 Board setup in Obsidian (one note per block a to l, Tier 2, Tier 3) and a Hub note with the Sprint 1 goal. [Verification: notes exist, each has status/estimate]
- 1.7 Learning log: 5 lines. Job-search block. [Verification: written]

### Tier 1: Foundation (Days 2 to 9)
- a. (Day 2, 3.0 h) Repo structure, `uv` project, `compose.yaml` with `pgvector/pgvector` (pin a tag, e.g. pg17 or pg18 chosen after checking Docker Hub), `.env.example`, `ruff`, `pytest`, `docs/setup-log.md`. [Verification: container survives `docker compose down` and `up`; one vector inserted and found with `<=>`; one passing test; run U9 checks]
- b. (Day 2, 1.0 h) Throwaway container calls host Ollama and a host test server via `host.docker.internal` (U3). Start n8n alone from a pinned image with a volume, `TZ=Asia/Manila`, port `127.0.0.1:5678` (U4); note RAM. [Verification: results written in research section 3 with the date; if U3 fails, decide with Eo using PRD section 6 before any other plan step depends on it]
- c. (Days 2 to 3, 1.5 h) Ollama spike: pull `qwen3.5:4b`; `ollama show`; `/api/show` thinking values; time a 3-chunk question with `think` default and `false`; note RAM (U1, U2). [Verification: numbers in setup-log and research; decision recorded: thinking on/off, num_ctx value, keep_alive]
- d. (Day 3, 2.0 h) Schema and numbered migrations per PRD section 10; `db.py`; migration script. [Verification: one command builds an empty database; test inserts and reads a chunk and cleans up]
- e. (Days 3 to 4, 4.5 h) Chunker (read loop-lab `rag.py` first, reuse `chunk_md` shape), fastembed embeddings (check U6), atomic save for text and Markdown. [Verification: acceptance FR1, FR4, FR5, FR6, FR8 pass; no chunk over 600 words]
- f. (Days 4 to 5, 2.5 h) URL save with `trafilatura`, 15 s timeout, 200-character rule, URL normalization. [Verification: acceptance FR2 on 3 saved HTML fixtures plus one live URL by hand; typo URL gives one readable error]
- g. (Day 5, 2.5 h) Supersede, archive, delete, list. [Verification: acceptance FR7, FR18, FR19, FR20]
- h. (Days 5 to 6, 2.5 h) Retrieval top 3 by cosine, threshold, `/search`. [Verification: acceptance FR9, FR10, FR13 on fixtures]
- i. (Days 6 to 7, 5.0 h) `llm.py`: prompt with delimiters, JSON contract, quote and chunk-id check, one retry, passages-only fallback, timeouts, injection test. [Verification: acceptance FR11, FR12, FR17, FR34 with a fake scripted model; one live injection test with `qwen3.5:4b`]
- j. (Days 7 to 8, 3.5 h) CLI, FastAPI with key, `/docs`, `/health`, localhost binding, `query_log`. [Verification: acceptance FR25, FR26, FR35; U8 checked; RAM measured with full stack (Day 7)]
- k. (Day 8, 1.0 h) API Dockerfile and container start. [Verification: `docker compose up` brings up db and api; `/health` answers; acceptance FR38 dry run]
- l. (Days 8 to 9, 4.0 h) Golden set (20 questions, 14 answerable, 6 not), frozen test library, eval script, baseline. Draft questions earlier while saving documents (Days 3 to 6). [Verification: acceptance FR33; M1 and M2 reported with the honest-limits note]
- **Gate 1 (Day 9):** save text/md/url; ask from CLI and API; cited answer or refusal; fallback works; eval baseline saved; pytest and ruff pass. [Verification: run all; tag `v0.1-core`]

### Tier 2: Reach (Days 9 to 11)
- m. (Days 9 to 10, 2.5 h) Text PDF with `pypdf` (U5). [Verification: acceptance FR3 with a text PDF and a scanned fixture]
- n. (Day 10, 1.5 h) Obsidian one-way export to `raw/agila/`. [Verification: acceptance FR28 including before/after folder listing]
- o. (Days 10 to 11, 5.0 h) Discord bot: app, token in `.env`, allow-list, `/ping` with defer, then `/ask`, `/save`, `/list`, `/archive`, `/delete`, splitting. Check U7. [Verification: acceptance FR27 and FR40 in the private server; reply over 2000 characters arrives as several messages]
- p. (Day 11, 1.0 h) `--private` flag. [Verification: acceptance FR41 including `/stale` and the digest later]
- **Gate 2 (Day 11):** tag `v0.2`.

### Tier 3: Automation and release (Days 12 to 15)
- q. (Day 12, 1.0 h) `/stale` endpoint. [Verification: acceptance FR39 including a backdated private document that must not appear]
- r. (Day 12, 1.0 h) n8n spike: webhook "hello" calls the local API using the route decided in block b. [Verification: n8n run is green]
- s. (Day 12, 2.5 h) Workflow B weekly digest via a Discord channel webhook URL (in `.env`/n8n credential, not in chat). [Verification: acceptance FR30, with data and with none]
- t. (Day 13, 3.0 h) Workflow A save pipeline; `SAVE_VIA_N8N` switch. [Verification: acceptance FR29 incl. a bad URL]
- u. (Day 13, 1.5 h) Exports, screenshots, two-minute demo script (not published, D9). [Verification: acceptance FR32]
- v. (Day 14, 2.0 h) README, fresh-clone test in an empty folder, backup video. [Verification: M6 time recorded under 20 minutes; demo checklist passes]
- w. (Day 14, 2.5 h) Optional only if ahead: `ask-general` (FR14), stats (FR21), age warning (FR15). [Verification: their acceptance sentences]
- **Gate 3 (Day 14).**
- x. (Day 15) Buffer; secret scan (NFR3) of full history; tag `v1.0`. Stretch FR36 video captions only if Gate 3 passed and nothing slipped (then research first: re-verify the caption library and its terms). [Verification: gitleaks clean; tag exists]

## Status log
Legend: `[ ]` not started, `[~]` in progress, `[x]` done, `[x] Failed (cause)`.
- [ ] 1.1 to 1.7 (Day 1)
- [ ] a, b, c, d, e, f, g, h, i, j, k, l, Gate 1
- [ ] m, n, o, p, Gate 2
- [ ] q, r, s, t, u, v, w (optional), Gate 3
- [ ] x (Day 15)

## Drop order if behind (from PRD)
Optional and stretch; then Workflow A; then Discord commands other than `/ask` and `/save`; then Obsidian export. Never drop Tier 1.
