# Agila

Agila is a personal knowledge assistant that runs on one Windows laptop. You save links, pasted text, Markdown files and text PDFs; then you ask questions and get a short answer that cites the saved passage it came from, or a plain "I couldn't find this in your saved material". Nothing is sent to a hosted model or a hosted database: the model runs locally in Ollama, and the library lives in PostgreSQL with pgvector in Docker.

It is a single-user project (one owner, one laptop). The API listens on `127.0.0.1` only. There is no cloud version, no user accounts, and no support for scanned PDFs.

## Host prerequisites

Install these first. They are not part of Docker Compose, and their downloads are not counted in the setup time.

1. **Windows 10 or 11** with about 20 GB of RAM (the database, Ollama, the API and, optionally, n8n run side by side).
2. **Docker Desktop** with the WSL 2 engine, running. Check: `docker --version` and `docker compose version`.
3. **Ollama**, running on the host (not in Docker), with the model pulled:
   `ollama pull qwen3.5:4b`
4. **uv** (it installs Python 3.12 for the project by itself). Check: `uv --version`.
5. **git**.

All commands below are for Windows PowerShell, run in the project folder.

## Quick start

1. Get the code:
   ```powershell
   git clone https://github.com/mezoa/agila.git
   cd agila
   uv sync
   ```
2. Create `.env` from the example:
   ```powershell
   Copy-Item .env.example .env
   ```
   Open `.env` in an editor. `POSTGRES_PASSWORD` and `AGILA_API_KEY` need long random values. This puts one on the clipboard without printing it; paste it into `.env`, run it again for the second value, then clear the clipboard:
   ```powershell
   uv run python -c "import secrets; print(secrets.token_urlsafe(32))" | Set-Clipboard
   Set-Clipboard -Value ' '
   ```
   The Discord lines can stay empty unless you use the bot. Never commit `.env` (it is in `.gitignore`).
3. Download the embedding model once (it needs the network once; the API container runs offline):
   ```powershell
   uv run python -c "from fastembed import TextEmbedding; from agila.chunking import MODEL_NAME, CACHE_DIR; TextEmbedding(MODEL_NAME, cache_dir=str(CACHE_DIR)); print('model cached')"
   ```
   It prints `model cached`.
4. Create the folder for the Obsidian notes, then start the database and the API:
   ```powershell
   New-Item -ItemType Directory -Force raw\agila\files
   docker compose up -d
   docker compose ps
   ```
   The first run builds the `api` image. `docker compose ps` shows `db` and `api` as healthy (the API can take up to a minute).
5. Create the tables:
   ```powershell
   uv run --env-file .env python -m agila.db migrate
   ```
   It prints one line listing every file it applied: `applied: 0001_init.sql, 0002_identity_index_web_only.sql, 0003_export.sql`. A second run prints `nothing to apply`.
6. Check the API:
   ```powershell
   curl.exe -s http://127.0.0.1:8000/health
   ```
   It prints `{"database":"ok","ollama":"ok"}`. If it names Ollama, start Ollama.
7. Save a note and ask about it:
   ```powershell
   "The harbour lights are green on Tuesdays. This note is a first test. Nothing else is here." | uv run --env-file .env python -m agila.cli text --title "First test" --label first-test
   uv run --env-file .env python -m agila.cli ask "What colour are the harbour lights on Tuesdays?"
   ```
   The save prints `Saved First test: 1 chunks`. The ask prints the short answer first, then a `Sources:` list with the cited passage. The first question is slower while the model loads.

## Everyday use

- All commands: `uv run --env-file .env python -m agila.cli --help` (text, markdown, url, pdf, list, stale, search, ask, evaluate, archive, unarchive, delete, export). Each has its own `--help`.
- Save a text PDF: `uv run --env-file .env python -m agila.cli pdf path\to\file.pdf`
- Keep a document off Discord, the weekly digest and n8n: add `--private` to a save command.
- List the library: `uv run --env-file .env python -m agila.cli list`
- Old and never-asked documents: `uv run --env-file .env python -m agila.cli stale`
- Delete a document: `uv run --env-file .env python -m agila.cli delete <id> --yes` (without `--yes` it only says what would go)
- Rewrite missing Obsidian notes: `uv run --env-file .env python -m agila.cli export --retry`
- In the browser: `http://127.0.0.1:8000/docs` (the API key goes in the `X-API-Key` header).
- Backup of the library: `uv run python scripts/backup.py`

## Optional: Discord bot

The bot runs on the laptop and works from a phone only while the laptop, Docker and Ollama are running. Fill `DISCORD_BOT_TOKEN`, `DISCORD_ALLOWED_USER_IDS` and `DISCORD_GUILD_ID` in `.env`, then:

```powershell
uv run --env-file .env python -m agila.bot --sync   # once, and again when the commands change
uv run --env-file .env python -m agila.bot          # in its own window; Ctrl+C stops it
```

Only the user IDs in `DISCORD_ALLOWED_USER_IDS` get answers. Replies never ping anyone.

## Optional: n8n workflows

n8n runs in the same Compose file but only when asked:

```powershell
docker compose --profile n8n up -d n8n
docker compose stop n8n
```

The editor is at `http://127.0.0.1:5678`. The workflows (a weekly digest of stale documents posted to Discord, and a save pipeline for the bot) are not in this repository: exported n8n workflows and their screenshots are kept out of public places until n8n's licence terms for that are confirmed.

## Privacy and safety

- Everything runs on the laptop. Compose publishes the database, the API and n8n on `127.0.0.1` only.
- Text shown in Discord passes through Discord's servers; documents saved with `--private` are never sent there, nor to n8n.
- Secrets live only in `.env`. Do not print `.env` or the environment, and do not run `docker compose config` without `--quiet`: it prints the values.

## Tests

```powershell
uv run ruff check .
uv run pytest                              # offline tests: no database, no Ollama, no network
uv run --env-file .env pytest -m db        # needs the database container and .env
```

The GitHub Action runs `ruff` and the offline `pytest` on Windows for every push. It cannot run the database or Ollama tests, the Docker image, the bot or n8n.

## Troubleshooting

- `docker` cannot connect to `dockerDesktopLinuxEngine`: start Docker Desktop and wait until the engine is running.
- `uv run` does not read `.env` by itself: keep `--env-file .env` in the commands that need it.
- `/health` names Ollama: start Ollama on the host; the API keeps running and `ask` falls back to the passages.
- Port 5433, 8000 or 5678 is already in use: another copy of this project, or another Postgres or n8n, is running. Stop it first.

## Licence

MIT. See `LICENSE`.
