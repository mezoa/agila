"""Text for the Discord bot: the allow-list, message pieces and reply wording. No I/O at all.

Every reply is built from fields the API already returns (`formatted`, `text`, `note`,
`message`, ...), so no answer or search logic lives here (NFR10).
"""

LIMIT = 1900  # characters per message; Discord allows 2,000 (DEVIATIONS 57)
SENTENCE_ENDS = (". ", "? ", "! ")
ALLOWED_VARIABLE = "DISCORD_ALLOWED_USER_IDS"


def allowed_ids(text: str | None) -> frozenset[int]:
    """FR40: the Discord user IDs that get an answer. Blank or missing means nobody. A bad entry
    raises ValueError naming the variable, never the value."""
    ids = set()
    for part in (text or "").split(","):
        part = part.strip()
        if not part:
            continue
        if not (part.isascii() and part.isdigit()):
            raise ValueError(f"{ALLOWED_VARIABLE} must be comma-separated numbers.")
        ids.add(int(part))
    return frozenset(ids)


def split(text: str, limit: int = LIMIT) -> list[str]:
    """FR27: pieces of at most `limit` characters, none empty, cut at a blank line, else a line
    break, else a sentence end, else a space, else hard. Whitespace at a cut is dropped."""
    pieces = []
    rest = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    while len(rest) > limit:
        cut = _cut(rest, limit)
        pieces.append(rest[:cut].rstrip())  # never empty: `rest` starts with a non-space
        rest = rest[cut:].lstrip()
    if rest:
        pieces.append(rest)
    return pieces


def _cut(text: str, limit: int) -> int:
    """Where to cut: always between 1 and `limit`, so every piece fits and the loop moves on."""
    window = text[: limit + 1]  # a separator may end exactly at the limit
    for separator in ("\n\n", "\n"):
        at = window.rfind(separator)
        if at > 0:
            return at
    at = max(window.rfind(end) for end in SENTENCE_ENDS)
    if at >= 0:
        return at + 1  # keep the full stop with its sentence
    at = window.rfind(" ")
    return at if at > 0 else limit


def ask_reply(answer: dict) -> str:
    """The second `/ask` message: the answer with its sources, a refusal's sentence, or only the
    note for the fallback and busy cases (the passages were already the first message)."""
    if answer["kind"] == "answer":
        return answer["formatted"]
    if answer["kind"] == "refusal":
        return answer["text"]
    return answer["note"]


def save_reply(saved: dict) -> str:
    """The API's own save sentence, then its label warning and export warning when set."""
    lines = [saved["message"], saved.get("warning"), saved.get("export_warning")]
    return "\n".join(line for line in lines if line)


def ping_reply(health: dict | None, problem: str | None = None) -> str:
    """`/ping` always answers "pong"; with the `/health` body it adds the database and Ollama
    lines, and when the API did not answer it adds that sentence instead (Eo's Q8)."""
    if health is None:
        return "pong" + (f"\n{problem}" if problem else "")
    return f"pong\nDatabase: {health.get('database')}\nOllama: {health.get('ollama')}"
