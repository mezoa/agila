# Agila: rules for Claude Code

Agila is Eo's personal knowledge assistant: save links, text, Markdown and text PDFs, then ask questions and get short cited answers from only the saved material, or a refusal. Everything runs on Eo's laptop. The authority is `docs/PRD.md` (Draft 3.3).

## Start of every session
1. Read `docs/ace/PROTOCOL.md`, `docs/ace/research_latest.md` and `docs/ace/plan_latest.md`. Read nothing else until a step needs it.
2. Work only on the block Eo names. Run its verification. Tick it in the status log of `plan_latest.md`.
3. If a verification fails, stop. Mark the step `[x] Failed (cause)`, add a dated line to the Lessons log in `research_latest.md`, and ask Eo. Do not retry blindly.

## Facts
- A tool, version, flag or limit counts as true only if `research_latest.md` lists it as verified. Anything else is unverified: test it or read the official page, then record the source and date there.
- Before a major edit to an ACE file, copy `*_latest.md` over `*_prev.md`. Keep only these two versions.

## Code rules
- Python managed with `uv`. Run `ruff` and `pytest` before every commit; commit only when both pass.
- Unit tests use a fake scripted model and saved fixtures: no network, no Ollama, no live websites.
- Never read, print, edit or commit `.env`. Secrets (Discord token, API key, database password) live only there.
- `loop-lab` is reference only. Read it, never edit it.
- Only llm.py talks to Ollama. The CLI and the API call the same search and ask functions (questions.py) and write the same query_log; the Discord bot and n8n call the API and hold no search or answer logic.
- The API is published only as `127.0.0.1:8000:8000`. Documents saved with `--private` never go to Discord, `/stale`, the digest, the bot or n8n.
- Do not build anything the PRD does not list for the current tier. A new idea goes to the backlog in the PRD, not into the code.

## Working with Eo
- Eo is learning while building. Explain each changed file in one plain sentence, and keep explanations short.
- Small commits with clear messages. Verified commands are written into `docs/setup-log.md`, not guessed.
