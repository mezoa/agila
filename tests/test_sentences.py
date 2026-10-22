from agila import web
from agila.sentences import count_sentences, split_sentences


def test_web_uses_the_one_sentence_rule():
    assert web.count_sentences is count_sentences


def test_sentences_are_numbered_in_order():
    text = "The cat sat down. The dog barked loudly! Did the bird fly away?"
    assert split_sentences(text) == [
        "The cat sat down.",
        "The dog barked loudly!",
        "Did the bird fly away?",
    ]


def test_decimals_abbreviations_and_initials_do_not_split():
    assert split_sentences("Prices rose 3.5 percent, e.g. in May, vs. last year.") == [
        "Prices rose 3.5 percent, e.g. in May, vs. last year."
    ]
    assert split_sentences("The U.S. office opens at 9 a.m. every day. It closes late.") == [
        "The U.S. office opens at 9 a.m. every day.",
        "It closes late.",
    ]


def test_known_gap_etc_splits():  # research U35: kept as it is until after block l
    assert split_sentences("We use pgvector etc. for search in this app.") == [
        "We use pgvector etc.",
        "for search in this app.",
    ]


def test_a_text_under_three_words_is_one_sentence_but_counts_zero():
    assert split_sentences("Short note.") == ["Short note."]
    assert count_sentences("Short note.") == 0


def test_blank_text_has_no_sentences():
    assert split_sentences("") == []
    assert split_sentences("  \n ") == []


def test_count_matches_the_split_for_longer_texts():
    text = "Home\nAbout us\nContact\n\nOur shop sells books. We open at nine every day."
    assert count_sentences(text) == len(split_sentences(text))


def test_the_same_text_gives_the_same_numbers():
    text = "One sentence here now. Another sentence follows it. And a third one ends."
    assert split_sentences(text) == split_sentences(text)
