# ACE protocol for Project Agila (read this first in every coding session)

Source: Eo's uploaded file "ACE simple format" (it cites HumanLayer's advanced-context-engineering-for-coding-agents). Checked 2026-10-15 against the HumanLayer page: it describes Research, Plan, Implement with "frequent intentional compaction", keeps context use around 40 to 60 percent, and says human review of research and plans is worth more than reviewing code. Note: the link `daveshap/ACE_Framework` is a different thing (a six-layer cognitive architecture for autonomous agents) and is NOT what we follow.

## Rules
1. **Context is finite.** Start each session by reading only: this file, `research_latest.md`, `plan_latest.md`, and the files of the one step you are doing. Keep sessions short. When a phase is done, write what was learned into the plan and research files, then start a fresh session.
2. **Research, then Plan, then Implement.** Never write code for a step that is not in `plan_latest.md`. Never plan a step on a fact that `research_latest.md` marks as unverified.
3. **Specs are the source of truth,** not chat history. If chat and files disagree, the files win until someone edits them.
4. **DRY / YAGNI / KISS / SOLID.** Reuse before writing (check `loop-lab`, which is reference only: never edit it). Cut anything the PRD does not require. Pick the simplest path. One job per module.
5. **Stop on failure.** If a step fails or a verification does not pass: stop, mark the step `[x] Failed (cause)` in `plan_latest.md`, add a dated line to the Lessons log in `research_latest.md`, return to Research. Do not retry blindly.
6. **No guessing.** If something is not verified (a command, a flag, a version, a limit), say so, then test it or look it up in the official docs and record the source and date.

## Versioning (two files per artifact, at most)
- `research_latest.md` (active) and `research_prev.md` (backup); `plan_latest.md` and `plan_prev.md`.
- Before a major edit: copy `*_latest.md` over `*_prev.md`, then edit `*_latest.md` only. The older backup is overwritten (only two versions exist).
- The first version of each file is `*_latest.md` (it is "v1"; there is no `_prev` yet).

## Templates
- research: Context and definitions, Verified facts (claim, source, date, confidence), Unverified items, Knowledge graph, Lessons log.
- plan: Checklist with a verification per step, Status log (`[ ]` not started, `[~]` in progress, `[x]` done, `[x] Failed (cause)`).
