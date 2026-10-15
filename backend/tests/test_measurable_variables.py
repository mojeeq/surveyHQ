"""What counts as a quantity, and what the answer is allowed to prevent.

The measure picker said "No variable matches" on datasets made of numbers.
Household size, rooms, number of children, years of schooling, age in a small
sample: all stored as numbers, none of them offered for a mean.

The cause was this rule. Any whole-number column with twenty or fewer distinct
values was called a code set, labels or no labels, and the picker offered only
what had been called a quantity. Twenty is a lot of survey questions: a
household size runs 1 to 15, children 0 to 12, rooms 1 to 8.

What actually distinguishes a code set from a quantity is whether somebody
named the codes. That comes from the questionnaire rather than from a guess
about shape, and it is the one piece of real evidence available. Without it,
only a two-value column is confidently a code - a tick, or a yes-or-no, where
the column's own name carries the whole meaning.

The rule still only decides what is offered first. Being wrong about a region
code is now a mean nobody asked for rather than a mean nobody can take, and
the front end asks the other question entirely: not "is this a quantity" but
"is this stored as a number", which is in lib/measures.
"""

from __future__ import annotations

import pytest

from app.services.ingest import classify


def kind(**over) -> str:
    settings = {
        "is_boolean": False,
        "is_datetime": False,
        "is_numeric": True,
        "is_integral": True,
        "has_value_labels": False,
        "non_null": 500,
        "distinct": 10,
    }
    settings.update(over)
    return classify(**settings)


# --- The questions people could not measure ----------------------------------


@pytest.mark.parametrize(
    ("what", "distinct"),
    [
        ("household size, 1 to 15", 15),
        ("children ever born, 0 to 12", 13),
        ("rooms in the dwelling, 1 to 8", 8),
        ("years of schooling, 0 to 18", 19),
        ("age in a village of sixty people", 20),
        ("people per sleeping room", 6),
        ("visits made by the interviewer", 4),
        ("a three-value count", 3),
    ],
)
def test_an_unlabelled_count_is_a_quantity(what, distinct):
    assert kind(distinct=distinct) == "numeric", what


def test_a_wide_measure_was_never_in_doubt():
    assert kind(distinct=4000) == "numeric"


# --- What is still a code set ------------------------------------------------


def test_named_codes_are_a_code_set_however_many_there_are():
    """The questionnaire said what the numbers mean, which settles it."""
    assert kind(has_value_labels=True, distinct=2) == "categorical"
    assert kind(has_value_labels=True, distinct=15) == "categorical"
    assert kind(has_value_labels=True, distinct=400) == "categorical"


def test_a_tick_is_a_code_set_without_being_told():
    """Yes or no, ticked or not: the column's name is the whole meaning, and
    there is nothing a mean of it would add that a count does not say."""
    assert kind(distinct=2) == "categorical"
    assert kind(distinct=1) == "categorical"


def test_a_fractional_column_is_never_a_code():
    """Codes are whole numbers. A column with halves in it is a measurement."""
    assert kind(distinct=2, is_integral=False) == "numeric"


# --- The kinds that answer before any of this --------------------------------


def test_the_other_types_are_unaffected():
    assert kind(is_boolean=True) == "boolean"
    assert kind(is_datetime=True) == "datetime"
    # A column nobody answered is not evidence of anything.
    assert kind(non_null=0, distinct=0) == "text"


def test_text_still_becomes_a_code_set_when_it_repeats():
    assert kind(is_numeric=False, distinct=6, non_null=500) == "categorical"
    assert kind(is_numeric=False, distinct=500, non_null=500) == "text"
