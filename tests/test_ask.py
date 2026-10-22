import json
import threading
from datetime import UTC, datetime

import pytest

from agila import ask, llm
from agila.ask import REFUSAL, UNCHECKED, answer, format_answer
from agila.retrieval import Passage

SAVED = datetime(2026, 10, 21, 9, 0, tzinfo=UTC)
TEXT = "The first sentence is here. The second sentence holds the answer. A third one ends it."


class ScriptedModel:
    """Fake model: replies with the scripted strings in order, or raises a scripted error."""

    def __init__(self, *steps):
        self.steps = list(steps)
        self.calls = []

    def chat(self, messages):
        self.calls.append(messages)
        step = self.steps.pop(0)
        if isinstance(step, Exception):
            raise step
        return llm.Reply(step, 1200)


def _passage(chunk_id, heading=None, page=None, text=TEXT):
    return Passage(chunk_id, text, heading, page, "llm-wiki", "https://example.test", SAVED, 0.8)


PASSAGES = [_passage(11), _passage(12)]


def _reply(answerable=True, text="The second sentence has it.", citations=((11, 2),)):
    return json.dumps(
        {
            "answerable": answerable,
            "answer": text,
            "citations": [{"chunk_id": c, "sentence": s} for c, s in citations],
        }
    )


def test_a_valid_reply_gives_an_answer_with_the_quote_copied_from_the_chunk():
    model = ScriptedModel(_reply(text="  The answer is in the second sentence.  "))
    result = answer("Where is it?", PASSAGES, model=model)
    assert (result.kind, result.text, result.model_calls) == (
        "answer",
        "The answer is in the second sentence.",
        1,
    )
    (cited,) = result.citations
    assert cited.quote == "The second sentence holds the answer."
    assert (cited.chunk_id, cited.sentence, cited.title, cited.source) == (
        11,
        2,
        "llm-wiki",
        "https://example.test",
    )


def test_the_same_citation_twice_is_kept_once():
    result = answer("q", PASSAGES, model=ScriptedModel(_reply(citations=((11, 2), (11, 2)))))
    assert len(result.citations) == 1


def test_a_made_up_chunk_id_is_retried_with_a_correction():
    model = ScriptedModel(_reply(citations=((35, 1),)), _reply())
    result = answer("q", PASSAGES, model=model)
    assert (result.kind, result.model_calls) == ("answer", 2)
    retry = model.calls[1]
    assert retry[:2] == model.calls[0]
    assert retry[2] == {"role": "assistant", "content": _reply(citations=((35, 1),))}
    assert retry[3]["role"] == "user"
    assert "chunk_id 35 is not one of the passages" in retry[3]["content"]
    assert "Use only chunk_id 11, 12" in retry[3]["content"]


def test_a_made_up_chunk_id_twice_falls_back_to_passages():
    model = ScriptedModel(_reply(citations=((35, 1),)), _reply(citations=((35, 1),)))
    result = answer("q", PASSAGES, model=model)
    assert (result.kind, result.note, result.model_calls) == ("passages", UNCHECKED, 2)
    assert result.passages == tuple(PASSAGES) and result.citations == ()


@pytest.mark.parametrize("sentence", [0, 4, -1])
def test_a_sentence_number_that_does_not_exist_is_invalid(sentence):
    model = ScriptedModel(_reply(citations=((11, sentence),)), _reply(citations=((11, sentence),)))
    result = answer("q", PASSAGES, model=model)
    assert (result.kind, result.model_calls) == ("passages", 2)
    assert f"passage 11 has no sentence {sentence}" in model.calls[1][3]["content"]


def test_answerable_false_is_a_refusal():
    model = ScriptedModel(_reply(answerable=False, text="", citations=()))
    result = answer("q", PASSAGES, model=model)
    assert (result.kind, result.text, result.model_calls) == ("refusal", REFUSAL, 1)


def test_invalid_json_twice_falls_back_to_passages_with_a_note():
    model = ScriptedModel("PWNED", '{"answerable": "yes"}')
    result = answer("q", PASSAGES, model=model)
    assert (result.kind, result.note, result.model_calls) == ("passages", UNCHECKED, 2)
    assert "the reply was not JSON" in model.calls[1][3]["content"]


@pytest.mark.parametrize(
    "bad",
    [_reply(text="   "), _reply(citations=()), '{"answerable": 1, "answer": "", "citations": []}'],
)
def test_an_empty_answer_no_citations_or_wrong_types_are_invalid(bad):
    result = answer("q", PASSAGES, model=ScriptedModel(bad, bad))
    assert (result.kind, result.model_calls) == ("passages", 2)


def test_a_timeout_is_not_retried_and_falls_back_with_its_sentence():
    model = ScriptedModel(llm.ModelError(llm.TIMED_OUT, timed_out=True), _reply())
    result = answer("q", PASSAGES, model=model)
    assert (result.kind, result.note, result.model_calls) == ("passages", llm.TIMED_OUT, 1)
    assert result.passages == tuple(PASSAGES)


def test_ollama_not_running_falls_back_without_a_retry():
    result = answer("q", PASSAGES, model=ScriptedModel(llm.ModelError(llm.NOT_RUNNING)))
    assert (result.kind, result.note, result.model_calls) == ("passages", llm.NOT_RUNNING, 1)


def test_nothing_retrieved_is_a_refusal_with_zero_model_calls():
    model = ScriptedModel()
    result = answer("Who won the 2022 FIFA World Cup?", [], model=model)
    assert (result.kind, result.text, result.model_calls) == ("refusal", REFUSAL, 0)
    assert model.calls == []


def test_a_second_caller_gets_the_busy_sentence_with_the_passages():
    started, release = threading.Event(), threading.Event()
    results = {}

    class SlowModel:
        def chat(self, messages):
            started.set()
            release.wait(5)
            return llm.Reply(_reply(), 1200)

    first = threading.Thread(
        target=lambda: results.update(first=answer("q", PASSAGES, model=SlowModel()))
    )
    first.start()
    assert started.wait(5)
    second = ScriptedModel()
    results["second"] = answer("q", PASSAGES, model=second)
    release.set()
    first.join(5)
    assert (results["second"].kind, results["second"].note) == ("busy", llm.BUSY)
    assert results["second"].passages == tuple(PASSAGES)
    assert (results["second"].model_calls, second.calls) == (0, [])
    assert results["first"].kind == "answer"


def test_the_retry_happens_inside_one_lock():
    seen = []

    class CheckingModel(ScriptedModel):
        def chat(self, messages):
            with pytest.raises(llm.ModelBusy):
                with llm.one_call_at_a_time():
                    pass  # pragma: no cover
            seen.append(True)
            return super().chat(messages)

    answer("q", PASSAGES, model=CheckingModel("bad", _reply()))
    assert seen == [True, True]


def test_every_ask_sentence_has_at_most_25_words():
    assert len(REFUSAL.split()) <= 25 and len(UNCHECKED.split()) <= 25


# --- format_answer and the heading rule (7.D) ---


@pytest.mark.parametrize("heading", [None, "", "  "])
def test_a_missing_or_empty_heading_shows_no_section_in_an_answer(heading):
    passages = [_passage(11, heading=heading)]
    result = answer("q", passages, model=ScriptedModel(_reply()))
    assert result.citations[0].section is None
    out = format_answer(result)
    assert "None" not in out and " - " not in out and " ()" not in out
    assert "   llm-wiki (https://example.test, saved " in out


@pytest.mark.parametrize("heading", [None, ""])
def test_a_missing_or_empty_heading_shows_no_section_in_the_passages_view(heading):
    result = answer("q", [_passage(11, heading=heading)], model=ScriptedModel("x", "y"))
    out = format_answer(result)
    assert "None" not in out and " - " not in out
    assert "1. llm-wiki (https://example.test, saved " in out


def test_a_real_heading_and_page_are_shown():
    result = answer("q", [_passage(11, heading="Setup", page=4)], model=ScriptedModel(_reply()))
    saved = SAVED.astimezone().strftime("%Y-%m-%d")
    assert format_answer(result) == (
        "The second sentence has it.\n\nSources:\n"
        '1. "The second sentence holds the answer."\n'
        f"   llm-wiki - Setup (https://example.test, page 4, saved {saved})"
    )


def test_a_refusal_formats_as_its_sentence():
    assert format_answer(answer("q", [], model=ScriptedModel())) == REFUSAL


def test_the_passages_view_starts_with_the_note_and_shortens_long_text():
    long = _passage(11, text="word " * 100)
    result = answer("q", [long], model=ScriptedModel(llm.ModelError(llm.NOT_RUNNING)))
    lines = format_answer(result).splitlines()
    assert lines[:3] == [llm.NOT_RUNNING, "", "Closest passages:"]
    assert lines[4].endswith("...") and len(lines[4]) == 3 + ask.SHOWN_CHARACTERS + 3
