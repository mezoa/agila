# Agila: interview notes (2026-10-14)

Source: PRD interview in Claude chat, 15 questions. These are Eo's decisions; items marked (default) were accepted defaults.

## Problem
- Saves links and docs, then forgets the content and must re-read it, which is a hassle.
- Cluttered file directories: some files are forgotten, some are deprecated.

## Users and access
- Personal project first; can also be used for work or with a team/friends without breaking privacy (separate spaces per person).
- Mostly used on phone; laptop during work or lessons. Discord is the main interface.
- v1 has one user; every item has an owner/space field from day one.

## Content types (priority)
- v1: web articles/blog posts, documentation pages and READMEs, text-based PDFs (PDFs first by choice, with page numbers), pasted text and own Markdown notes, chat messages/transcripts as pasted text.
- v1 (updated 2026-10-15): video links with captions (transcript with timestamps); a video without captions gets a clear message and the option to paste a transcript.
- v2 (could): speech-to-text on the laptop for videos without captions. Only spoken words are covered, not on-screen content.
- v3: screenshots, scanned PDFs (OCR).

## What a good answer looks like
- Normal reply: short answer, a quote, source with link and page, saved date.
- On request (/explain): comprehensive explanation with analogy/figurative language/simple diagrams, in a block labelled "not from your sources".
- Passages appear right away, then the written answer; target under 60 seconds.

## When the answer is not in the library
- Refuse ("I couldn't find this in your saved material"), then offer a general answer clearly labelled as not from the sources and possibly wrong (small local Qwen).

## Old and deprecated material
- Re-saving the same URL/file replaces the old copy (old one marked superseded).
- Manual /archive command.
- Age warning on answers (e.g. source over 12 months old).

## Privacy
- Two-space design: cloud space for public web content, local-only space for sensitive material that never leaves the laptop.

## Budget and constraints
- $0 at the start; option to add a capped hosted model on Day 6 if the demo feels too limited.
- CPU-only Windows laptop (Ryzen 5 5600H, 20 GB RAM), Ollama + Qwen, free tools.
- Priority is the foundation of the automation; nothing complicated beyond that.

## Out of scope for now (v3 / later list: keep, do not lose)
- Public sign-up or login system for strangers
- Scanned PDFs, screenshots and images (OCR)
- Generated images for explanations
- Browser extension for one-click saving
- Automatic import of browser bookmarks or whole folders
- Custom web app or mobile app (Discord and FastAPI /docs only)
- Telegram bot
- Editing or rewriting saved content
- Hybrid search (moved to v3 to make room for n8n)

## Automation and portfolio goals
- Must be able to demo the workflow and explain it briefly to interviewers (automation roles).
- Workflow 1 (in scope): save pipeline, trigger Discord /save, then fetch, clean, chunk, embed, store, Obsidian note, confirm in Discord, friendly errors and retry.
- Workflow 2 (in scope): weekly digest on a schedule, posts old / never-asked-about / possibly deprecated items to Discord.
- Workflow 3 (stretch): inbox folder watcher, drop a PDF/Markdown file in inbox/ and it is imported then moved to processed/.
- n8n is used as the visible orchestration layer (HTTP calls to the Python API); Python stays the brain. n8n work starts only after core v1 works (after Oct 25); it takes the slot of hybrid search (default accepted).
- Demo is a screen recording plus exported workflow files and screenshots in the repo (n8n runs on the laptop).

## Risks (top concerns)
- Staying motivated and consistent day after day: mitigations are a visible board, floor-day rule, short daily clip, streak tracker in Obsidian.
- Lacking an automation portfolio: mitigated by the workflow demo above.
- Being able to demo and explain the workflow to interviewers.
