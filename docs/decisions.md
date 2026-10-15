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
| Ports | Publish the API as `127.0.0.1:8000:8000` | `8000:8000` exposes it to the network (Docker docs) | Checked by `docker compose config` |
| Schedule | 57.0 h planned of 63 h; Workflow A dropped first | Review finding: buffer was too thin | Gates inside slack |
| Process | ACE: Research, Plan, Implement; files in `docs/ace/` | Avoid hallucinated facts and context drift | Two versions per file |
