# Research: Project Agila build (Days 1 to 15)

- Version: v3 (2026-10-15, after the Day 1 review). Backup: `research_prev.md` (v2).
- Phase rule: nothing in plan_latest.md may rely on an item in section 3 until it has been tested and moved to section 2.

## 1. Context and definitions
- **Goal:** personal knowledge assistant: save links, text, Markdown and text PDFs; ask a question; get a short cited answer from only the saved material, or a refusal. All local, $0.
- **Machine:** Windows laptop, Ryzen 5 5600H, 20 GB RAM, CPU only (stated by Eo earlier). Docker Desktop (WSL2), Ollama native on the host.
- **Time:** at most 15 days, Oct 15 to Oct 29, 4.5 h/day; Day 1 is PRD/planning; build Days 2 to 15 (63 h; committed 54.0 h).
- **Existing code to reuse (DRY):** `C:\Users\Meo Angelo Alcantara\loop-lab` (reference only, never edit): `rag.py` (heading chunker `chunk_md`, retrieval), `loop.py`, `memory_store.py`, `rag_questions.jsonl`, `evals/`. File list is from an earlier session; read the files before reusing anything (plan step 3.1).
- **Constraints:** Python 3.10+ (fastembed and trafilatura, from earlier PyPI checks); secrets only in `.env`; API bound to 127.0.0.1; private items never reach Discord.

## 2. Verified facts (official pages, fetched 2026-10-15)
| ID | Fact | Source | Confidence |
| --- | --- | --- | --- |
| V1 | Ollama `qwen3.5` tags: `4b` 3.3 to 4.0 GB, `9b` 6.6 to 7.6 GB, `latest` same size as 9b; all list a 256K context window and text+image input; the page lists "thinking" but does not say how to control it | https://ollama.com/library/qwen3.5 | High |
| V2 | Thinking is controlled by the `think` field on the chat/generate API (`true`, `false`, `null`=model default, or a named level); `/api/show` returns a `thinking` object with `values` and `default`; the page does not mention Qwen3.5 specifically | https://docs.ollama.com/capabilities/thinking | High for the API, unknown for Qwen3.5 |
| V3 | Ollama keeps a model loaded 5 minutes by default; `keep_alive` per request (`-1` = forever, `0` = unload) or `OLLAMA_KEEP_ALIVE`; default context 4096, set with `options.num_ctx` or `OLLAMA_CONTEXT_LENGTH`; binds to `127.0.0.1:11434` unless `OLLAMA_HOST` is set | https://docs.ollama.com/faq | High (defaults can change by version: set explicitly) |
| V4 | Docker Desktop: containers reach the host via the DNS name `host.docker.internal`. The page does not say whether host services bound to `127.0.0.1` are reachable | https://docs.docker.com/desktop/features/networking/networking-how-tos/ | High for the name; loopback reachability UNVERIFIED (see U3) |
| V5 | Discord: first response to an interaction within 3 seconds or the token is invalidated; type 5 (`DEFERRED_CHANNEL_MESSAGE_WITH_SOURCE`) shows a loading state; interaction tokens are valid 15 minutes for follow-ups | https://docs.discord.com/developers/interactions/receiving-and-responding | High |
| V6 | Discord message `content` is limited to 2000 characters | https://docs.discord.com/developers/resources/message | High |
| V7 | pgvector: image `pgvector/pgvector` with tags like `pg18`, `pg17`, `pg18-trixie`, `0.8.7-pg18`; `CREATE EXTENSION vector;` once per database; cosine distance operator `<=>` (similarity = 1 minus distance); exact search by default and no index needed for small tables; page references v0.8.7 | https://github.com/pgvector/pgvector | High |
| V8 | n8n: image `n8nio/n8n`, pin a tag (example `1.81.0` is only an example, not a recommendation); volume `n8n_data` at `/home/node/.n8n`; port 5678; set `TZ` and `GENERIC_TIMEZONE`. The docker-run page is marked outdated. The current Compose guide adds sandbox (privileged Docker-in-Docker) and SearXNG services for n8n's assistant features, recommends at least 4 GB RAM and 2 vCPUs, and on Windows says to run inside WSL with the project in the WSL filesystem | https://docs.n8n.io/hosting/installation/docker/ and https://docs.n8n.io/deploy/host-n8n/install-options/install-using-docker-compose.md | High for what the pages say; whether a minimal n8n-only setup is fine is UNVERIFIED (U4) |
| V9 | The HumanLayer ACE page: Research, Plan, Implement; "frequent intentional compaction"; keep context in the 40 to 60 percent range; review research and plans (more leverage than reviewing code) | https://github.com/humanlayer/advanced-context-engineering-for-coding-agents/blob/main/ace-fca.md | High |
| V10 | `daveshap/ACE_Framework` is the "Autonomous Cognitive Entities" six-layer architecture, not a coding workflow | https://github.com/daveshap/ACE_Framework/blob/main/ACE_Framework.md | High |

## 2b. Facts from earlier in this project (checked 2026-10-15, not re-fetched in this pass; re-check on install day)
- Package versions seen on PyPI: `discord.py` 2.7.1, `trafilatura` 2.3.1, `fastembed` 0.9.0 (default model BAAI/bge-small-en-v1.5, 384 dimensions), `pypdf` 6.20.1 (BSD-3). PyMuPDF is AGPL-3.0 (avoid).
- n8n Community edition (Sustainable Use License): free for personal, learning and internal use; no explicit statement about portfolio display; decision D9: no email, exports stay unpublished.
- n8n has a Discord node for sending; no native trigger for incoming Discord messages, so the bot calls an n8n Webhook node.
- `youtube-transcript-api` (video captions) is backlog, not in the core plan.
Confidence: medium. Rule: pin what you actually install; write the version in `docs/setup-log.md`.

## 2c. Facts merged from `docs/research-log.md` (review chat, 2026-10-15; "Read" = seen on the page that day)
- Qwen3.5 thinking: the Modelfile cannot turn it off (Ollama issue 14617, user report on 0.17.4); API `think:false` works per request. A third-party guide says thinking is off by default for 0.8B to 9B in llama.cpp; NOT confirmed for Ollama, so U2 stays open. Source: https://github.com/ollama/ollama/issues/14617 ; https://unsloth.ai/docs/models/qwen3.5
- Postgres 18 images keep data under `/var/lib/postgresql`; 17 and below use `/var/lib/postgresql/data`. Choose the volume path to match the tag. Source: https://hub.docker.com/_/postgres
- pgvector Docker tags include `0.8.7-pg17`, `0.8.7-pg18`, `pg17`, `pg18`. Source: https://hub.docker.com/r/pgvector/pgvector/tags
- n8n latest stable 2.42.7 (2026-10-12); 2.x is current. Source: https://github.com/n8n-io/n8n/releases
- PyPI JSON API versions on 2026-10-15: fastembed 0.9.0, trafilatura 2.3.1, pypdf 6.20.1, pdfplumber 0.11.10, discord.py 2.7.1, fastapi 0.143.1, uvicorn 0.54.0, psycopg 3.3.6, pgvector 0.5.1, pytest 9.1.1, ruff 0.17.0.
- Not measured: `qwen3.5:4b` under 60 s (U1). n8n license and public portfolio display: not addressed (D9).

## 2d. Facts verified for the Day 1 review (official pages, 2026-10-15)
| ID | Fact | Source | Confidence |
| --- | --- | --- | --- |
| V11 | bge-small-en-v1.5 maximum sequence length is 512 tokens; the query instruction for retrieval is "Represent this sentence for searching relevant passages: " (trailing space); passages get no instruction; omitting it causes only a slight drop | https://huggingface.co/BAAI/bge-small-en-v1.5 | High |
| V12 | Ollama structured output: pass a JSON schema in the `format` field (Pydantic `model_json_schema()` works; set temperature 0; include the schema in the prompt). The page does not say how it behaves with thinking models | https://docs.ollama.com/capabilities/structured-outputs | High; thinking behavior UNVERIFIED (U11) |
| V13 | Discord `allowed_mentions`: `parse: []` blocks all mention pings; in interactions and webhooks only user mentions are parsed by default; `parse` cannot be combined with `users` or `roles` | https://docs.discord.com/developers/resources/message | High |
| V14 | n8n Schedule Trigger discards missed runs by default; a "run most recent missed execution" option exists with the durable scheduler, stated to be on by default from n8n 2.45.0 (our log shows latest stable 2.42.7, so check the pinned version); the workflow must be published; default instance timezone is America/New_York | https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.scheduletrigger/ | High; availability in our version UNVERIFIED (U12) |
| V15 | Docker: `-p 8000:8000` publishes on all host addresses (reachable from other machines); `-p 127.0.0.1:8000:8000` restricts to the host | https://docs.docker.com/engine/network/port-publishing/ | High |
| V16 | The fastembed README does not say whether BGE models get the query instruction automatically; it only mentions "query" and "passage" prefix support | https://github.com/qdrant/fastembed | UNVERIFIED (U10) |

## 3. Unverified items (test before relying on them)
| ID | Question | How to test | When | Result |
| --- | --- | --- | --- | --- |
| U1 | Does `qwen3.5:4b` give a full cited answer within 60 s median on this laptop? | 10 warm questions with 3 chunks each, time them; note RAM | Day 2 to 3 (block c) | PARTIAL 2026-10-17 (one short question, 3 short passages, not the 10-question test): 4b with default thinking 63.9 s (run 2; 64.5 s run 1), over the 60 s target; 4b with `think:false` 0.9 s; 9b default 145.6 s, `think:false` 4.2 s. `ollama ps`: 4b 3.8 GB, 9b 6.2 GB, both with a GPU share. 10 warm questions with 3 real chunks still to do |
| U2 | How is thinking switched off for Qwen3.5 in Ollama, and what does it do to time? | `ollama show qwen3.5:4b`, call `/api/show`, then a request with `"think": false`; compare seconds | Day 2 (block c) | PARTIAL 2026-10-17: both models think by default on Ollama 0.40.4 (thinking chars 2153 to 3155 with `think` left out, 0 with `think:false`); per-request `"think": false` switches it off and cut time from 146 s to 4 s (9b) and 64 s to 0.9 s (4b). `/api/show` thinking values not yet checked |
| U3 | Can a container reach Ollama and a host test server bound to 127.0.0.1 through `host.docker.internal`? | Start a throwaway container with curl and call both | Day 2 (block b) | PASSED 2026-10-17: from `curlimages/curl:8.11.1`, `http://host.docker.internal:11434/api/version` -> `{"version":"0.40.4"}` HTTP 200; `http://host.docker.internal:8765/index.txt` (host server bound to 127.0.0.1 only) -> `hello-from-host` HTTP 200 |
| U4 | Does n8n run alone from a pinned image, with a volume, TZ=Asia/Manila and port bound to 127.0.0.1? How much RAM? | Minimal compose service; open the UI; Task Manager | Day 2 (block b) | PASSED 2026-10-17: `n8nio/n8n:2.43.6` (sha256:dd580fe1ab6e99e85bc66f2acf8bc8c5e9409fbe61b2e2803c5024403ef52833) alone, volume `n8n_data`, `127.0.0.1:5678`, editor HTTP 200; idle after 60 s `MEM=369.2MiB / 9.641GiB CPU=0.29%`; `docker exec n8n date` -> `Sat Oct 17 17:30:35 PST 2026`, `TZ=Asia/Manila`. Timezone inside the editor UI not checked |
| U5 | Does `pypdf` extract 3 of Eo's real PDFs well enough? | Compare with `pdfplumber` only if garbled | Day 9 | pending |
| U6 | After the first run, does fastembed work with no network? Where is the model cache? | Disconnect network; embed one sentence | Day 3 | pending |
| U7 | Does the Discord bot need any privileged intent for slash commands? | Read the discord.py and Discord docs while setting up | Day 10 | pending |
| U8 | Is the API unreachable from another device on the network? | Check port mapping and try from the phone on the same Wi-Fi | Day 7 to 8 | pending |
| U10 | Does `query_embed` in the installed fastembed add the BGE query instruction? Does the instruction help on the golden set? | Read the installed source; compare hit@3 with and without | Day 9 (block l) | pending |
| U11 | Does Ollama `format` (JSON schema) work with `qwen3.5:4b` when thinking is on or off? | Send the answer schema both ways | Day 2 to 3 (block c) | pending |
| U12 | Does the pinned n8n version offer the missed-run option on the Schedule Trigger? | Open the node in the pinned version | Day 13 (block s) | pending |
| U13 | Does `docker version` show a Server section from Windows PowerShell with Docker Desktop (WSL 2 engine) on Eo's laptop, and is Ollama installed on Windows (not only in Ubuntu)? | Run the 0.1 commands in the Day 2 runbook Step 0 | Day 2 (Oct 17) | pending |
| U9 | Python version and tool installs (uv, Docker) on this laptop | Run `python --version`, `uv --version`, `docker --version` | Day 2 (block a) | pending |

U1 to U4 status (2026-10-17): U1 partial, U2 partial, U3 passed, U4 passed. Details in `docs/setup-log.md` (blocks a, b, c part).

## 4. Knowledge graph (planned layout, nothing exists yet)
- `compose.yaml`: db (pgvector), later api, n8n. `.env.example`. `Dockerfile` (API).
- `migrations/`: numbered SQL files; `scripts/migrate.py`.
- `src/agila/`: `db.py`, `chunking.py`, `embed.py`, `ingest.py` (text, md, url, pdf), `library.py` (supersede, archive, delete, list), `ask.py` (retrieval), `llm.py` (the only place that talks to Ollama), `api.py` (FastAPI), `cli.py`, `export_obsidian.py`, `bot/` (discord.py, thin).
- `tests/`, `eval/` (golden set, frozen library, baseline), `n8n/` (exported workflows), `docs/` (PRD, decisions, setup-log, ace/).
- Dependency rule: bot, CLI and n8n call the API only; the API calls `ask.py`/`library.py`; only `llm.py` calls Ollama.

## 5. Lessons log (compaction)
- 2026-10-15: The link `daveshap/ACE_Framework` is a different framework. We follow the HumanLayer approach in Eo's uploaded protocol.
- 2026-10-15: Draft 3.1 scheduled setup work on Oct 15, but Oct 15 is the PRD day. Re-based: Day 1 = PRD/ACE lock, build Days 2 to 15.
- 2026-10-15: n8n's current official Compose install is heavier than assumed (assistant sandbox and search services, 4 GB RAM advice). Added a minimal start check on Day 2 so surprises come early.
- 2026-10-15: The review chat kept its own `docs/research-log.md`. Merged here and the old file was removed, so there is one source of truth; add new facts to this file only.
- 2026-10-15: Day 1 external review (24 findings): triaged in PRD Appendix D. Two design changes follow from verified facts: chunks are capped by tokens (512-token model limit), and the model returns chunk id + sentence number with an `answerable` flag so the program, not the model, writes the quote.
- 2026-10-15: Container-to-host loopback reachability is not documented on the Docker page; do not design around it until U3 is tested.
- 2026-10-16: uv docs read: `uv init` creates .git, .gitignore, .python-version, pyproject.toml, README.md and src/<pkg>; `uv add`, `uv run`, `uv sync` confirmed. The `--dev` flag was not on the page read; Claude Code checks `uv add --help`.
- 2026-10-17: Block a verification stopped: `docker info` failed (Docker Desktop engine not running, npipe dockerDesktopLinuxEngine missing). Always start Docker Desktop before Day 2 compose steps. U9 recorded in setup-log: Python 3.14.7, uv 0.12.17, Docker 29.6.1, Compose v5.3.0; project pins Python 3.12.
- 2026-10-16: These pages were NOT read (permission prompts unanswered): Ollama api/show, n8n GitHub releases, Docker Hub tags and postgres page. The pgvector tag 0.8.7-pg18, the Postgres 18 volume path, the n8n 2.42.7 tag and Ollama commands rest on the 2026-10-15 entries and are proven only by running them on Day 2 (pull or compose up fails if wrong). Record the outcome under U3/U4/U9.
- 2026-10-17: Docker docs read: with Docker Desktop's WSL 2 engine `docker` works from any Windows terminal; Desktop runs in its own `docker-desktop` WSL distro; WSL 2.1.5+ required; Docker Engine installed inside a WSL distro should be removed before installing Desktop; Windows-container mode hides WSL integration ("Switch to Linux containers"). Decision: all Agila commands run in Windows PowerShell with Docker Desktop, not inside Ubuntu (so `host.docker.internal` means the Windows host). `docker context use desktop-linux` is NOT from the docs read: untested.
- 2026-10-17: `docker compose up -d` failed with "failed to connect to the docker API at npipe:////./pipe/dockerDesktopLinuxEngine". Cause class: Docker Desktop engine not running when PowerShell ran the command (Docker Desktop installed, not started). Docker docs (read 2026-10-17): Docker Desktop runs in its own `docker-desktop` WSL 2 distro; docker commands work from Windows without any Linux distro; Docker Engine installed separately inside a WSL distro "can cause conflicts"; WSL 2 backend needs WSL 2.1.5+, Windows 10 22H2 / 11 23H2+, 8 GB RAM, virtualization on, LanmanServer Automatic. NOT confirmed on Eo's machine: which of these applied. Added Step 0 to the Day 2 runbook. Also open: whether Ollama runs on Windows or inside Ubuntu (affects U3); check in runbook 0.4.
- 2026-10-17: Docker Desktop engine now runs (docker context desktop-linux, WSL 2, Docker 29.6.1). `docker compose up -d` pulled `pgvector/pgvector:0.8.7-pg17` but failed to publish `127.0.0.1:5432`: "bind: An attempt was made to access a socket in a way forbidden by its access permissions". Known Windows pattern (reserved/excluded TCP port ranges, or another listener); NOT yet diagnosed on Eo's machine: needs `netsh interface ipv4 show excludedportrange protocol=tcp` and `netstat -ano | findstr :5432`. Workaround: publish the db on another host port (try 5433), and every host-side connection string must use it. Ollama on Eo's machine reports version 0.40.4 (Windows app).
- 2026-10-17: Port 5432 failure resolved. `netsh ... excludedportrange` showed only 50000-50059 and 51203-52002 reserved, so my first guess (reserved range) was wrong. `netstat -ano` showed process 8012 (`postgres`, a local Windows install) listening on 0.0.0.0:5432. Docker's "forbidden by its access permissions" text did not say "in use", so the message alone does not tell the two apart: run netsh and netstat. Fix: host port 5433 (nothing listened on it); `docker compose ps` showed `agila-db-1` Up (healthy) on `127.0.0.1:5433->5432/tcp`. Day 3 `db.py`, tests and any host-side client must use port 5433. The other project's `pmo-dash` containers use 3000/3001 and an internal-only Postgres, so no conflict with the API on 8000.
- 2026-10-17: Block c timing (one question): Qwen3.5 thinks by default in Ollama 0.40.4 and `think:false` removes it (4b 64 s to 0.9 s). The default-thinking time for 4b is over the 60 s target, so llm.py must set `think:false` explicitly unless a later test shows it hurts answers. `ollama ps` showed a GPU share although our notes say CPU only; not investigated. U1 stays partial until the 10-question run.
