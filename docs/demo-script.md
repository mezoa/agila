# Agila: two-minute demo script

Lines marked **SAY** are spoken; edit their wording freely. Lines marked **DO** are what to click or type. The times are targets, about 2:00 in total.

**Before you start (PRD section 12):** laptop plugged in; Docker Desktop and Ollama running; one warm-up question asked; the Discord bot online; n8n running with `agila-digest` open in the browser; a terminal in the project folder. Pick one question that your library can answer, and one that it cannot.

## Beat 1: the problem and the rule (0:00 to 0:40)

- **SAY:** I save a lot of links, notes and PDFs, then forget what is in them. Agila is my own search assistant, and it runs entirely on this laptop.
- **SAY:** Its one rule: it answers only from my saved material, with a citation, or it refuses.
- **DO:** In the terminal: `uv run --env-file .env python -m agila.cli ask "<a question your library can answer>"`
- **DO:** Point at the short answer first, then the `Sources:` list with the quoted passage, its source and the date it was saved.
- **SAY:** The quote is copied by the program from the saved passage, not written by the model, so I can check it.
- (Discord alternative: `/ask` shows the passages first, then the answer as a second message.)

## Beat 2: a refusal (0:40 to 1:00)

- **DO:** `uv run --env-file .env python -m agila.cli ask "<a question your library cannot answer>"`
- **DO:** Point at the reply: `I couldn't find this in your saved material.`
- **SAY:** When nothing I saved is close enough, it says so instead of guessing, and the model is not even called.

## Beat 3: saving from my phone (1:00 to 1:25)

- **DO:** In Discord: `/save text` with title `Demo note` and a short text of three sentences.
- **DO:** Point at the bot's reply: `Saved Demo note: 1 chunks`
- **SAY:** From my phone I can save a link or a note through Discord; the bot only passes it to the same local API the terminal uses.
- If the n8n save pipeline exists, say its confirmation sentence instead: n8n posts the same `Saved Demo note: 1 chunks` in `#agila-digest`.
- (Saving the same note again replies `Already saved, unchanged: Demo note (document <id>).`)

## Beat 4: the automation and privacy (1:25 to 2:00)

- **DO:** Show the `agila-digest` workflow canvas in n8n: Schedule Trigger and Manual Trigger, then HTTP Request, then the two Discord nodes.
- **SAY:** Every Monday at nine, n8n asks Agila for old or never-used documents and posts the list to Discord, so stale material does not quietly pile up.
- **DO:** Click **Execute workflow**, then show the message in `#agila-digest` (when nothing is stale it reads `Nothing stale this week`).
- **SAY:** Everything listens on 127.0.0.1 only, and anything I save with `--private` never reaches Discord, the digest or n8n.

After the demo: delete the demo note with `uv run --env-file .env python -m agila.cli delete <id> --yes`.

If anything fails: play docs/screenshots/demo-backup.* (a local file, not in the repository).
