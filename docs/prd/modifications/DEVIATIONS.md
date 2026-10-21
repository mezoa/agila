# Deviations from PRD Draft 3.3 (as of 2026-10-20, end of Day 4)

Kinds: **Temporary** (matches the PRD later), **Gap filled** (PRD silent or marked assumed), **Refinement** (a choice inside what the PRD allows), **Conflict** (needs a decision), **Schedule**.
"Amended" = already written into `PRD-draft-3.3-amended.md`.

| # | Topic | PRD says | What we did | Kind | Resolves | Recorded in |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | Redirects | FR2: at most 5 redirects, private-address check after each | A redirect is refused with "redirects are not supported yet" | Temporary | Day 5 | decisions.md "Redirects" |
| 2 | Other FR2 safety limits | Private/localhost block, 5 MB cap, HTML or text only, 200 chunks per document | Not built yet; no command line fetches URLs yet | Temporary | Day 5 | plan_latest.md f, step 9 |
| 3 | Duplicate save | FR7: same label with different content is stored with a warning; identical content says "already saved, unchanged" | Any second active save with the same identity gives a plain "Already saved" error | Temporary | Block g | plan_latest.md Q1 |
| 4 | Same label, two notes | FR7: both notes exist | The unique index `documents_active_identity` allows one active document per identity key, so the second cannot be inserted | Conflict (amended as OPEN CONFLICT) | Block g, first | plan_latest.md g |
| 5 | Command line | FR25: save, ask, search, list, archive, unarchive, delete, evaluate | A temporary `python -m agila.ingest text|markdown` only | Temporary | Block j | plan_latest.md e part 2 |
| 6 | Page download | FR2 / block f: download, then extract with `trafilatura` | We download with `httpx`; `trafilatura` only extracts text. Reasons: per-step timeout, no readable failure cause, certificate fallback, content type known late | Refinement (amended in FR2) | n/a | decisions.md "Page download", research V33, V34 |
| 7 | Total timeout | FR2: 15-second timeout | One total wall-clock limit (`asyncio.timeout`) | Refinement | n/a | decisions.md "Download timeout" |
| 8 | Sentence rule | FR2: fewer than 3 sentences is rejected [assumed], no definition | A sentence is a piece of at least 3 words cut at `.`, `!`, `?` or a line break, with an abbreviation list; text counted after collapsing whitespace. Known loose: long headings count | Gap filled (amended as a pointer) | Tune on Day 5 sample (U23) | decisions.md "Page text rules", research V40 |
| 9 | URL normalization | FR7 lists lowercase host, no fragment, no `utm_*`, `fbclid`, `gclid`, no trailing slash | Exactly those rules plus lowercase scheme. Not normalized: parameter order, ports, www., http vs https, other tracking parameters, and more | Gap filled | Revisit if real links need it | decisions.md "URL normalization", research V35 |
| 10 | Default space name | FR22: one space of kind `local` | Named `default`, kind `local` (the Day 3 runbook said `local`) | Gap filled (amended) | n/a | decisions.md "Default space" |
| 11 | Thinking and context | Decisions: "speed and thinking switch unverified"; "9b dropped" | `think:false` always; `num_ctx` 8192 sent every time; `keep_alive` "30m"; `qwen3.5:4b` default with the 9b optional | Gap filled (verified) | Recheck on golden set | decisions.md rows for Thinking, Default model, keep_alive, Context size |
| 12 | Model cache | "Offline use after first run" (U6) | fastembed files in `<repo>/.cache/fastembed`, ignored by git | Gap filled | n/a | decisions.md "Model cache" |
| 13 | Long headings | Silent | The chunker raises an error when title plus heading leave no room under 400 tokens | Gap filled (Eo's decision 2026-10-19) | n/a | decisions.md "Long headings" |
| 14 | Markdown defaults | Silent | Title = first `#` heading, else the file name; label = the file name with extension | Gap filled | n/a | plan_latest.md Q3 |
| 15 | Web identity and hash | FR7: normalized URL as the identity key | `identity_key` and `source_label` = normalized URL; `content_hash` = SHA-256 of the extracted text, not the HTML | Gap filled | n/a | decisions.md "URL fields on a web document" |
| 16 | Dependencies | Lists `trafilatura` only | Also `httpx` declared explicitly | Refinement | n/a | setup-log.md |
| 17 | Schedule | Block e 4.5 h (Days 3 to 4); f 3.0 h (Days 4 to 5); g 2.5 h (Day 5) | e done on Day 4; f is half done, so Day 5 carries the rest of f plus g | Schedule | Watch the Day 5 hours | plan_latest.md |

Housekeeping: the first line of `docs/decisions.md` still says "PRD Draft 3.2 is the authority"; `CLAUDE.md` and the PRD say Draft 3.3.
