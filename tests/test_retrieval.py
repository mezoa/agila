import ast
import inspect
import math
import sys
from pathlib import Path

import numpy as np
import pytest

from agila import library, retrieval
from agila.chunking import CACHE_DIR
from agila.embed import QUERY_INSTRUCTION
from agila.retrieval import MIN_SIMILARITY, search

needs_model = pytest.mark.skipif(
    not CACHE_DIR.exists(), reason="model not cached in .cache/fastembed"
)

# Scripted vectors: the question is e0; a chunk at similarity s is s*e0 + sqrt(1 - s^2)*e1.
Q = np.zeros(384, dtype=np.float32)
Q[0] = 1.0


def at(similarity):
    v = np.zeros(384, dtype=np.float32)
    v[0] = similarity
    v[1] = math.sqrt(1.0 - similarity**2)
    return v


class QuestionEmbedder:
    """Fake model: every question becomes Q; passages (for library saves) get scripted vectors."""

    def __init__(self):
        self.questions = []

    def query_embed(self, query):
        self.questions.append(query)
        return iter([Q.copy()])

    def passage_embed(self, texts):
        return (at(0.5) for _ in texts)


def _document(conn, title, status="active", source_type="text", url=None, label="L", key=None):
    return conn.execute(
        "INSERT INTO documents (space_id, title, source_type, source_url, source_label,"
        " identity_key, content_hash, status)"
        " VALUES ((SELECT id FROM spaces LIMIT 1), %s, %s, %s, %s, %s, 'h', %s) RETURNING id",
        (title, source_type, url, label, key or f"{source_type}:{title}", status),
    ).fetchone()[0]


def _chunk(conn, document_id, position, vector, text="Some text.", heading=None):
    return conn.execute(
        "INSERT INTO chunks (document_id, position, heading, text, embedding)"
        " VALUES (%s, %s, %s, %s, %s) RETURNING id",
        (document_id, position, heading, text, vector),
    ).fetchone()[0]


def _search(conn, **kwargs):
    return search(conn, "a question", embedder=QuestionEmbedder(), **kwargs)


# --- FR9: active documents only, at most 3 ---


@pytest.mark.db
def test_archived_and_superseded_chunks_are_never_returned(conn):
    active = _chunk(conn, _document(conn, "Active"), 0, at(0.8))
    _chunk(conn, _document(conn, "Archived", "archived"), 0, Q)  # exact matches
    _chunk(conn, _document(conn, "Superseded", "superseded"), 0, Q)
    result = _search(conn, min_similarity=-1.0)
    assert [p.chunk_id for p in result.passages] == [active]
    assert result.best_similarity == pytest.approx(0.8, abs=1e-6)


@pytest.mark.db
def test_archive_then_unarchive_removes_and_restores_a_passage(conn):
    document_id = _document(conn, "Note")
    chunk_id = _chunk(conn, document_id, 0, at(0.9))
    assert [p.chunk_id for p in _search(conn).passages] == [chunk_id]
    library.archive(conn, document_id)
    assert _search(conn).passages == []
    library.unarchive(conn, document_id)
    back = _search(conn).passages
    assert [p.chunk_id for p in back] == [chunk_id]
    assert back[0].similarity == pytest.approx(0.9, abs=1e-6)


@pytest.mark.db
@needs_model
def test_a_note_superseded_by_replace_is_never_returned(conn):
    old = library.save_text(conn, "T", "notes", "First version.", QuestionEmbedder())
    new = library.save_text(conn, "T", "notes", "Second version.", QuestionEmbedder(), replace=True)
    old_chunks = {r[0] for r in conn.execute(
        "SELECT id FROM chunks WHERE document_id = %s", (old.document_id,))}
    found = {p.chunk_id for p in _search(conn, min_similarity=-1.0).passages}
    assert found and not found & old_chunks
    assert found == {r[0] for r in conn.execute(
        "SELECT id FROM chunks WHERE document_id = %s", (new.document_id,))}


@pytest.mark.db
def test_at_most_three_passages_come_back_best_first(conn):
    document_id = _document(conn, "Many")
    for position, score in enumerate([0.75, 0.95, 0.80, 0.90, 0.85, 0.72]):
        _chunk(conn, document_id, position, at(score))
    result = _search(conn)
    assert [round(p.similarity, 2) for p in result.passages] == [0.95, 0.90, 0.85]


@pytest.mark.db
def test_equal_scores_come_back_in_chunk_id_order(conn):
    document_id = _document(conn, "Ties")
    ids = [_chunk(conn, document_id, position, at(0.9)) for position in range(4)]
    for _ in range(3):
        assert [p.chunk_id for p in _search(conn).passages] == ids[:3]


# --- FR10: no model anywhere in this path ---


@pytest.mark.db
def test_search_never_imports_or_calls_a_model(conn, monkeypatch):
    for name in ("agila.llm", "ollama"):
        monkeypatch.setitem(sys.modules, name, None)  # any import now fails
    _chunk(conn, _document(conn, "Note"), 0, at(0.9))
    embedder = QuestionEmbedder()
    result = search(conn, "a question", embedder=embedder)
    assert len(result.passages) == 1
    # only the embedding model was used
    assert embedder.questions == [QUERY_INSTRUCTION + "a question"]


def test_retrieval_imports_no_model_or_http_client():
    tree = ast.parse(Path(inspect.getfile(retrieval)).read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            names.add(node.module or "")
    assert not {n for n in names if n.split(".")[0] in ("ollama", "httpx", "requests")}
    assert "agila.llm" not in names


# --- the threshold (FR13 part) ---


def test_the_default_threshold_is_the_tuned_constant():
    assert MIN_SIMILARITY == 0.68  # set on the golden set dev half (block l)
    default = inspect.signature(search).parameters["min_similarity"].default
    assert default is MIN_SIMILARITY


@pytest.mark.db
def test_threshold_keeps_only_passages_at_or_above_it(conn):
    document_id = _document(conn, "Scores")
    for position, score in enumerate([0.90, 0.71, 0.69]):
        _chunk(conn, document_id, position, at(score))
    result = _search(conn, min_similarity=0.70)
    assert [round(p.similarity, 6) for p in result.passages] == [0.9, 0.71]
    assert result.min_similarity == 0.70


@pytest.mark.db
def test_a_passage_exactly_at_the_threshold_is_kept(conn):
    # 0.70 cannot be stored exactly in float32, so the threshold is the score the database gives.
    document_id = _document(conn, "Exact")
    exact = _chunk(conn, document_id, 0, at(0.70))
    _chunk(conn, document_id, 1, at(0.69))
    score = next(p.similarity for p in _search(conn, min_similarity=-1.0).passages
                 if p.chunk_id == exact)
    assert score == pytest.approx(0.70, abs=1e-6)
    assert [p.chunk_id for p in _search(conn, min_similarity=score).passages] == [exact]
    assert _search(conn, min_similarity=math.nextafter(score, 2.0)).passages == []


@pytest.mark.db
def test_nothing_close_enough_gives_no_passages_and_the_best_score(conn):
    document_id = _document(conn, "Far")
    _chunk(conn, document_id, 0, at(0.65))
    _chunk(conn, document_id, 1, at(0.40))
    result = _search(conn)
    assert result.passages == []
    assert result.best_similarity == pytest.approx(0.65, abs=1e-6)


@pytest.mark.db
def test_weaker_passages_under_the_threshold_are_dropped(conn):
    document_id = _document(conn, "Mixed")
    for position, score in enumerate([0.85, 0.60, 0.50]):
        _chunk(conn, document_id, position, at(score))
    result = _search(conn)
    assert [round(p.similarity, 2) for p in result.passages] == [0.85]
    assert result.best_similarity == pytest.approx(0.85, abs=1e-6)


# --- what a passage carries ---


@pytest.mark.db
def test_a_passage_carries_title_source_heading_date_and_page(conn):
    web = _document(conn, "Web page", source_type="web", url="https://example.test/a",
                    label="https://example.test/a")
    note = _document(conn, "A note", label="notes.md", source_type="markdown")
    _chunk(conn, web, 0, at(0.9), text="Web text.")
    _chunk(conn, note, 0, at(0.8), text="Note text.", heading="Setup")
    first, second = _search(conn).passages
    saved = dict(conn.execute("SELECT title, saved_at FROM documents").fetchall())
    assert (first.title, first.source, first.text, first.heading) == (
        "Web page", "https://example.test/a", "Web text.", None
    )
    assert (second.title, second.source, second.heading) == ("A note", "notes.md", "Setup")
    assert (first.saved_at, second.saved_at) == (saved["Web page"], saved["A note"])
    assert (first.page, second.page) == (None, None)


@pytest.mark.db
@needs_model
def test_page_is_empty_for_current_documents(conn):
    library.save_text(conn, "T", "L", "Some saved text.", QuestionEmbedder())
    passages = _search(conn, min_similarity=-1.0).passages
    assert passages and all(p.page is None for p in passages)


# --- last_asked_at (FR35) and the empty library ---

DATES = "SELECT id, last_asked_at, saved_at FROM documents ORDER BY id"


@pytest.mark.db
def test_search_does_not_change_last_asked_at(conn):
    never = _document(conn, "Never asked")
    asked = _document(conn, "Asked once")
    conn.execute(
        "UPDATE documents SET last_asked_at = '2026-10-01 10:00+08' WHERE id = %s", (asked,)
    )
    _chunk(conn, never, 0, at(0.9))
    _chunk(conn, asked, 0, at(0.8))
    before = conn.execute(DATES).fetchall()
    for _ in range(3):
        assert len(_search(conn).passages) == 2
    after = conn.execute(DATES).fetchall()
    assert after == before
    assert before[0][1] is None


@pytest.mark.db
def test_an_empty_library_returns_no_passages(conn):
    result = _search(conn)
    assert (result.passages, result.best_similarity) == ([], None)
