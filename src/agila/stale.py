"""FR39: stale documents, the ones worth archiving or re-checking, and their text for `/stale`.

Stale = active and never asked about and older than 30 days, or active and older than 12 months
(both [assumed] in the PRD). "Asked" means cited in an answered question (`last_asked_at`, set
only by the ask flow). Read-only: nothing here writes, and no model is involved. Private
(`laptop_only`) documents are left out unless the caller passes `include_private` (FR39, FR41).
"""

from dataclasses import dataclass
from datetime import datetime

import psycopg

from agila.export import local_date

LIMIT = 20  # rows the API returns by default; the CLI shows all
NEVER_ASKED = "never asked"
TOO_OLD = "older than 12 months"
NOTHING = "Nothing stale this week"  # FR30's sentence, no full stop

# research 2s C1: timestamptz compares instants, so the container's time zone does not matter.
# A document past 12 months gets that reason even when it was also never asked.
STALE = (
    "SELECT d.id, d.title, d.source_type, d.saved_at, d.last_asked_at,"
    " CASE WHEN d.saved_at < t.now - interval '12 months' THEN %(too_old)s"
    " ELSE %(never)s END,"
    " count(*) OVER ()"
    " FROM documents d JOIN spaces s ON s.id = d.space_id"
    " CROSS JOIN (SELECT coalesce(%(now)s::timestamptz, now()) AS now) t"
    " WHERE s.name = 'default' AND d.status = 'active'"
    " AND (d.visibility = 'anywhere' OR %(include_private)s)"
    " AND ((d.last_asked_at IS NULL AND d.saved_at < t.now - interval '30 days')"
    " OR d.saved_at < t.now - interval '12 months')"
    " ORDER BY d.saved_at, d.id"
    " LIMIT %(limit)s"
)


@dataclass(frozen=True)
class StaleDocument:
    document_id: int
    title: str
    source_type: str
    saved_at: datetime
    last_asked_at: datetime | None
    reason: str  # NEVER_ASKED or TOO_OLD


@dataclass(frozen=True)
class Stale:
    """`documents`: oldest first, at most the limit; `total`: how many are stale in all."""

    documents: list[StaleDocument]
    total: int


def find_stale(
    conn: psycopg.Connection,
    *,
    now: datetime | None = None,
    limit: int | None = None,
    include_private: bool = False,
) -> Stale:
    """FR39. `now` is for tests (default: the database clock); `limit` (1 or more) cuts the rows,
    None means all. `total` rides on the rows (`count(*) OVER ()`), so no row back means 0."""
    params = {
        "now": now,
        "limit": limit,
        "include_private": include_private,
        "too_old": TOO_OLD,
        "never": NEVER_ASKED,
    }
    with conn.transaction():  # short and read-only, so `conn` stays idle afterwards
        rows = conn.execute(STALE, params).fetchall()
    return Stale([StaleDocument(*row[:6]) for row in rows], rows[0][6] if rows else 0)


def format_stale(stale: Stale) -> str:
    """The text the CLI prints and `/stale` returns as `formatted` (Workflow B posts it as is)."""
    if not stale.documents:
        return NOTHING
    lines = [f"Stale documents: {stale.total}."]
    for d in stale.documents:
        lines.append(
            f"{d.document_id}  {local_date(d.saved_at)}  {d.source_type}  {d.title}  ({d.reason})"
        )
    if stale.total > len(stale.documents):
        lines.append(f"Showing {len(stale.documents)} of {stale.total}. Use the CLI stale for all.")
    return "\n".join(lines)
