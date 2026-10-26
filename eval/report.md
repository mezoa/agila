# Agila golden-set report: exam v1 (block l, 2026-10-26)

Numbers only: no question, phrase or passage text. 20 questions (14 answerable, 6 not), 10 dev and 10 held-out (7 answerable and 3 unanswerable in each). Frozen library in the separate database `agila_eval` (9 documents). The held-out half was run once, after the settings below were fixed.

## Settings
- Query prefix: **on** (`embed.USE_QUERY_INSTRUCTION`; questions only, stored passages unchanged).
- Threshold: **0.68** (`retrieval.MIN_SIMILARITY`, compared with `>=`; was 0.70). Set on the dev half with the prefix: gap -0.037, 2 dev errors (answerable Q03 and Q05 below it), no dev unanswerable question above it.
- Embedding model `BAAI/bge-small-en-v1.5`; answer model `qwen3.5:4b`. Chunk size unchanged (about 300 tokens, never over 400).

## Results

| Measure | Result | PRD target | Met? |
| --- | --- | --- | --- |
| M1 hit@3 (raw top 3, no threshold) | **13 of 14 (0.93)**; dev 6 of 7, held-out 7 of 7 | at least 0.80 (12 of 14) | Met |
| False refusals (answerable below 0.68) | 3 of 14 (Q03, Q04, Q05) | none set (reported) | n/a |
| M2 refused with no model call | **5 of 6**; dev 3 of 3, held-out 2 of 3 | at least 5 of 6 | Met, with no spare |
| M3 time to passages | cold 0.82 s; **median 0.010 s** over 10 warm searches | median 3 s or less (cold reported, not targeted) | Met |
| M4 time to full answer (second run) | cold 21.9 s; **median 12.0 s**, slowest 16.3 s over the 10 warm answers that called the model | median 60 s or less; slowest reported | Met |
| Right document cited | 21 of 21 citation rows | none set (reported) | n/a |
| Citation precision (U15) | 13 of 21 "yes", 8 "partly", 0 "no" | none set (reported) | n/a |
| M10 answer faithfulness | 6 of 10 answered questions have every citation "yes" (6 of 14 questions) | no pass mark: "Report the count (no pass mark; it shows whether G2 holds)" | No target, so neither met nor not met |

- M4 run: of 14 answerable questions, 10 were answered, 3 were refused by the threshold (no model call) and 1 was refused by the model (Q08). The first run of `evaluate answers` gave, after the M4 fix (DEVIATIONS 44): cold 10.6 s, median 10.5 s, slowest 15.6 s. M4 above is from the second run, made for the grading-sheet excerpt change (DEVIATIONS 45).
- Grading: done once by hand by Eo in `eval/runs/grading-2026-10-26.md` (git-ignored: it holds quotes), 21 citation rows.

## Checks
- **FR33 passed:** `evaluate retrieval` exited 0 against the saved `eval/baseline.json` and exited 1 against a copy with the hit count raised by 1.
- **FR35 passed twice:** the real library's `count(*), max(last_asked_at)` of `documents` and `count(*)` of `query_log` read `4|2026-10-24 14:31:55.458191+00` and `11` before and after the evaluation runs.

## Limits (read these with the numbers)
- 14 and 6 questions, a regression check, not proof: one miss moves hit@3 by about 7 points (about 14 within a half) and the refusal count by about 17 (about 33 within a half).
- The threshold was set on 10 dev questions.
- Q08 (the Lint question) is a retrieval miss with and without the prefix, and the model refused it.
- 3 of 14 valid short questions are refused by the threshold.
- One held-out unanswerable question passed the threshold and would reach the model; only the model's refusal stands between it and an answer.
- The "partly" citation rows come from padded citations (Q02, Q06, Q09) and a thin answer (Q13).
- Q14's quote describes planned testing, not finished testing.
- The rule used to keep the query prefix had no minimum margin (the gap moved by 0.012 with the same hits); the next evaluation plan must set one before seeing the numbers.
