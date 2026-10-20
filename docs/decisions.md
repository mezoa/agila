# Agila decisions (updated 2026-10-15; PRD Draft 3.2 is the authority)

| Need | Choice | Why | Catch / status |
| --- | --- | --- | --- |
| Schedule | At most 15 days, Oct 15 to Oct 29; Day 1 = PRD, build Days 2 to 15 | Eo's limit | 54.0 h committed of 63 h |
| Hosting | All-local; cloud (Neon, Render) is future work only | $0, privacy, laptop is the demo machine | Free tiers change often; re-check later |
| Local model | Ollama with `qwen3.5:4b` (9b dropped) | Laptop is CPU-only | Speed and thinking switch unverified: ACE items U1, U2 |
| Database | Docker `pgvector/pgvector` (pin a pg17 or pg18 tag), exact search, no index | pgvector 0.8.7 seen in its README | Tag chosen on Day 2 |
| Embeddings | `fastembed` BAAI/bge-small-en-v1.5 (384 dims) | Used before; local | Offline use after first run: U6 |
| Web text | `trafilatura` | Maintained | Python 3.10+ |
| PDF | `pypdf`; `pdfplumber` only if needed; avoid PyMuPDF (AGPL) | Permissive licenses | U5 |
| Discord | `discord.py`, bot runs on the laptop; defer within 3 s, follow-up within 15 min, messages up to 2000 chars | Verified in Discord docs | Intents: U7 |
| Automation | n8n self-hosted Community edition; bot calls an n8n Webhook node | No native Discord trigger | Official install is heavier than assumed: U4. No license email for now (D9): exports stay unpublished |
| Container networking | Undecided | Docker docs do not cover loopback reachability | Test Day 2 (U3); decision rule in PRD section 6 |
| Video links (FR36) | Backlog; stretch on Day 15 only from the buffer | Time | `youtube-transcript-api` is the candidate; re-verify then |
| Chunking | Token-based cap of 400 tokens (target about 300) including title and heading | bge-small-en-v1.5 reads 512 tokens (checked 2026-10-15) | Embedded text = title + heading + chunk; query prefix decided on the golden set (U10) |
| Answer format | Ollama `format` JSON schema with `answerable`, chunk id and sentence number; the program copies the quote | A 4B model paraphrases quotes | Behavior with thinking on: U11 |
| Ports | Database published as `127.0.0.1:5433->5432` (host 5432 is taken by Eo's local Windows PostgreSQL, process `postgres`; seen 2026-10-17). Publish the API as `127.0.0.1:8000:8000` | `8000:8000` exposes it to the network (Docker docs) | Checked by `docker compose config` |
| Schedule | 57.0 h planned of 63 h; Workflow A dropped first | Review finding: buffer was too thin | Gates inside slack |
| Process | ACE: Research, Plan, Implement; files in `docs/ace/` | Avoid hallucinated facts and context drift | Two versions per file |
| Thinking | Always send `think:false` on every request | Default is thinking on; it cost 145.6 s vs 4.2 s (9b) and 63.9 s vs 0.9 s (4b) (C1, block c) | U2 passed; `format` with thinking on untested (U11) |
| Default model | `qwen3.5:4b`; `qwen3.5:9b` optional (supersedes the older "9b dropped" row) | Same accuracy in the spike (19/20 each, 0 invented), 9b about 2.5 to 3x slower | Spike was small and did not check citations (U15); recheck on the golden set. Confirmed by Eo 2026-10-19: 4b is the default, 9b stays optional (D3) |
| Structured output | `format` JSON schema plus Pydantic validation, one retry, tag normalization (lowercase, hyphenate, dedupe) in `llm.py` | Valid JSON 26/26 with `think:false`; tag case and wording vary at temp 1 | Lower temperature effect: U14 |
| keep_alive | `"30m"` on every request | Accepted by Ollama (`ollama ps` UNTIL 29 minutes); avoids the ~30 s cold start | Set explicitly; defaults can change by version |
| Context size | `num_ctx` 8192 set explicitly and sent identically on every request; log `prompt_eval_count` from each reply and warn above 80% of `num_ctx` (about 6,500) | Default is 4096; at 8192 size 3.8 to 3.9 GB, CPU/GPU 54/46 | Speed at 8192 not measured (U16) |
| Prompt rule | Prompts must say to answer only from the given passages | The 4b sometimes added details not in the source (C2) | Test with the injection and golden sets |
| Model cache | fastembed model files live in `<repo>/.cache/fastembed`, passed as `cache_dir=` (never the temp-folder default); `.cache/` is in `.gitignore` | The default is the Windows temp folder, which can be cleared and would break offline use (U6, V24, V25) | The model loaded is Qdrant's quantized ONNX copy (`Qdrant/bge-small-en-v1.5-onnx-Q`), not the BAAI original; its tokenizer was not compared with BAAI's (low priority). A fresh clone needs the network once to download (~67 MB) |
| Default space | The default space is named `default` with kind `local` | PRD FR22 says kind local; `0001_init.sql` inserts this row | Kind `cloud` is reserved for future work |
| Long headings | `chunk_document` raises `ValueError` when the title plus a heading leave no room under the 400-token cap; it does not truncate | Eo's decision 2026-10-19: a clear error beats silently cutting text | A save with a very long heading fails with a readable message; callers must show it (FR2 style) |
