# eval/ : the exam for Agila (block l)

- questions.txt: 20 questions, tagged dev or held-out. Locked on 2026-10-26; do not edit.
- answer-key.md: what the shelf says. Do not read the held-out rows while tuning.
- web-sources.txt: three web pages saved once into the eval database.
- library/: six plain text files (kept out of git: three are university documents).
Nine documents in total. The shelf is frozen: change it only by starting a new exam version.

## Rerunning the exam (block l, 2026-10-26)
The held-out half was run once, on 2026-10-26, after the query prefix and the threshold were fixed on the dev half; results in `report.md`, numbers in `baseline.json`. Do not tune anything on the held-out half: a new tuning round needs a new exam version.

From the project folder (PowerShell), with the database running:
- `uv run --env-file .env python -m agila.cli evaluate build`: recreates the database `agila_eval` from `library/` and the frozen web pages (no network). It never touches the real library `agila`.
- `uv run --env-file .env python -m agila.cli evaluate retrieval`: all 20 questions, compared with `baseline.json`; exits 1 if hit@3 or the refusals drop (FR33). Never pass `--save-baseline` again unless starting a new exam version.
- Optional: `uv run --env-file .env python -m agila.cli evaluate answers` (needs Ollama; stop the `api` container first) writes a new grading sheet in `runs/` and refuses to overwrite one of the same date.
- `uv run --env-file .env python -m agila.cli evaluate drop`: deletes `agila_eval` when done; the frozen files stay.
