"""A condition named once and used five times.

The ILO cascade this platform was asked to run says `ilo_wap==1` on every one
of its rules, and the employment test itself is a line and a half repeated in
the generate and in two of the replaces. Changing who counts as of working age
means finding every copy, which is how a cascade comes to disagree with
itself: one rule updated, the rest not, and the totals still add up.

So a piece of script text can be named and referred to:

    local wap   ilo_wap == 1
    replace ilo_lfs_emp = 1 if `employed' & `wap'

The name is replaced by its text before the command is parsed. That is the
whole mechanism, and it is why a macro can hold half a condition, an operator,
a variable name or a list - anything that is text in a command.

Checked here against the cascade written both ways, which must classify the
same nine people identically, because a macro that changes an answer is not a
macro.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import Dataset
from app.services import stata, stata_macros
from tests.test_api_analytics import _stata_bytes, _zip_bytes
from tests.test_recode_cascade import PEOPLE, STATA_SAYS, classification

# The same cascade as test_recode_cascade, with the two conditions that repeat
# given names. Nothing else about it changes.
WITH_MACROS = "\n".join(
    [
        "local wap      ilo_wap == 1",
        "local working  main_activity==1 | main_activity==3 | inc_2nd_activity==1",
        "local helping  additional_work==1 | help_family==1",
        "* A macro may be written in terms of the ones above it.",
        "local employed `working' | `helping'",
        "gen ilo_lfs_emp=.",
        "replace ilo_lfs_emp=1 if (`employed') & `wap'",
        "replace ilo_lfs_emp=1 if main_activity==2 & inlist(prod_purpose,1,2) & `wap'",
        "replace ilo_lfs_emp=2 if (inlist(reason_absent,1,2,3,4) | return_work==1"
        " | continue_income==1) & `wap'",
        "replace ilo_lfs_emp=3 if !inlist(ilo_lfs_emp,1,2) & `wap'",
    ]
)


@pytest.fixture
def people(client, auth_headers, request, db_session) -> Dataset:
    made = client.post(
        "/api/v1/projects",
        headers=auth_headers,
        json={"name": f"Macros {request.node.name[:28]}"},
    ).json()
    uploaded = client.post(
        "/api/v1/datasets/upload",
        headers=auth_headers,
        files={
            "file": (
                "lfs.zip",
                _zip_bytes({"macro_people.dta": _stata_bytes(PEOPLE)}),
                "application/zip",
            )
        },
        data={"project_id": made["id"]},
    )
    assert uploaded.status_code == 201, uploaded.text
    found = (
        db_session.execute(
            select(Dataset).where(
                Dataset.project_id == made["id"], Dataset.name == "macro_people"
            )
        )
        .scalars()
        .first()
    )
    assert found is not None
    return found


# --- the point of the whole thing --------------------------------------------


def test_the_cascade_gives_the_same_answer_written_with_macros(people, db_session):
    stata.run_script(db_session, people, WITH_MACROS)
    db_session.flush()
    db_session.refresh(people)

    assert classification(people) == STATA_SAYS


def test_a_name_survives_the_line_that_defined_it(people, db_session):
    """Every command gets its own Run, so this is not automatic: the macros
    are held by the script rather than by the command."""
    results = stata.run_script(
        db_session,
        people,
        "local wap ilo_wap == 1\ngen adults = 1 if `wap'",
    )
    assert "Created adults" in results[-1].message


def test_the_log_shows_what_ran_rather_than_what_was_typed(people, db_session):
    """A macro is only readable until something goes wrong with it. The log
    carries the expanded command, which is the one that actually ran."""
    results = stata.run_script(
        db_session,
        people,
        "local wap ilo_wap == 1\ngen adults = 1 if `wap'",
    )
    assert results[-1].command == "gen adults = 1 if ilo_wap == 1"


# --- defining --------------------------------------------------------------


def test_a_definition_needs_no_data_in_memory(people, db_session):
    """Conditions are named at the top of a script, above the `use`. A
    definition that insisted on data would make that impossible."""
    results = stata.run_script(db_session, people, "local wap ilo_wap == 1")
    assert "`wap' stands for ilo_wap == 1" in results[0].message


def test_the_equals_form_names_the_expression_and_says_so(people, db_session):
    """Stata reads observation 1 here and stores a 0 or a 1, which turns a
    condition into a constant with nothing to show for it. This names the
    expression, and the log says which of the two it did."""
    results = stata.run_script(db_session, people, "local wap = ilo_wap == 1")
    assert "stands for ilo_wap == 1" in results[0].message
    assert "not its value on the first row" in results[0].message


def test_quotes_come_off_a_definition(people, db_session):
    results = stata.run_script(db_session, people, 'local wap "ilo_wap == 1"')
    assert "`wap' stands for ilo_wap == 1" in results[0].message


def test_the_two_namespaces_are_separate(people, db_session):
    """A local and a global of one name are two macros, as in Stata."""
    results = stata.run_script(
        db_session,
        people,
        "local here ilo_wap == 1\nglobal here ilo_wap == 0\ngen a = 1 if `here'",
    )
    assert results[-1].command == "gen a = 1 if ilo_wap == 1"


def test_a_global_is_written_both_ways(people, db_session):
    results = stata.run_script(
        db_session,
        people,
        "global wap ilo_wap == 1\ngen a = 1 if $wap\ngen b = 1 if ${wap}",
    )
    assert results[-2].command == "gen a = 1 if ilo_wap == 1"
    assert results[-1].command == "gen b = 1 if ilo_wap == 1"


def test_a_macro_holds_any_text_not_only_a_condition(people, db_session):
    """Substitution is textual, so a macro can hold a variable list."""
    results = stata.run_script(
        db_session,
        people,
        "local cols pid ilo_wap\nkeep `cols'",
    )
    assert results[-1].command == "keep pid ilo_wap"


# --- what it refuses ---------------------------------------------------------


def test_an_undefined_name_is_refused_by_name(people, db_session):
    """Stata puts nothing there and carries on, which is how a do-file comes
    back with the wrong answer and no error anywhere.

    Asserted on the refusal itself rather than on the name appearing
    somewhere in the message: a failed line is reported with the line as
    typed, so `wapp' is in the text either way and a test reading only that
    passes just as happily when the macro silently expands to nothing.
    """
    with pytest.raises(stata.CommandError) as raised:
        stata.run_script(
            db_session, people, "local ofage ilo_wap == 1\nkeep if `oface'"
        )
    said = str(raised.value)
    assert "is not a local macro this run has defined" in said
    # And says what there was, since there is no session to type `macro list` into.
    assert "Defined: ofage" in said


def test_a_condition_that_silently_empties_is_the_whole_reason(people, db_session):
    """The case above, where expanding to nothing leaves a command that still
    runs. `keep if `poor'` with the name mistyped becomes `keep if`, and
    Stata keeps every row rather than the poor ones - a wrong answer, from a
    script that reported success on every line."""
    with pytest.raises(stata.CommandError) as raised:
        stata.run_script(
            db_session,
            people,
            "local ofage ilo_wap == 1\ngen a = 1 if `oface'\n",
        )
    assert "is not a local macro this run has defined" in str(raised.value)

    # Nothing was written: the run stopped on the name, not later and
    # elsewhere with a message about something else.
    db_session.flush()
    db_session.refresh(people)
    assert not any(v.name == "a" for v in people.variables)


def test_a_macro_can_be_rebuilt_from_its_old_self(people, db_session):
    """`local a `a' == 1` reads the text as it stands and stores the result,
    which is Stata's definition-time expansion and is how a condition gets
    extended a piece at a time."""
    results = stata.run_script(
        db_session, people, "local a ilo_wap\nlocal a `a' == 1\nkeep if `a'"
    )
    assert results[-1].command == "keep if ilo_wap == 1"


def test_a_ring_of_names_cannot_expand_forever():
    """Reached directly rather than through a script, because a script cannot
    build one: expanding at definition time means a name is already literal
    text by the time anything can point back at it. The guard is for the
    expander's own contract, which takes whatever dictionaries it is given."""
    with pytest.raises(stata_macros.MacroError) as raised:
        stata_macros.expand("keep if `a'", {"a": "`b'", "b": "`a'"}, {})
    assert "refers to itself" in str(raised.value)

    with pytest.raises(stata_macros.MacroError):
        stata_macros.expand("keep if `a'", {"a": "`a'"}, {})


def test_a_name_that_is_not_a_name_is_refused(people, db_session):
    with pytest.raises(stata.CommandError) as raised:
        stata.run_script(db_session, people, "local 2wap ilo_wap == 1")
    assert "not a name a macro can have" in str(raised.value)


def test_a_definition_with_nothing_in_it_is_refused(people, db_session):
    with pytest.raises(stata.CommandError) as raised:
        stata.run_script(db_session, people, "local")
    assert "name" in str(raised.value)


# --- after the command box's commands are replayed ---------------------------


def test_a_macro_written_from_another_survives_a_replay(people, db_session):
    """A newer export replaces the data and every recorded command runs again.

    The recorded commands are the expanded ones, so almost none of them needs
    a macro - but a definition written in terms of another was recorded as
    typed, and replaying it on its own failed on a name nothing had defined.
    Each replayed command gets its own Run, the same way the script does, so
    the macros have to be held by the replay.
    """
    stata.run_script(
        db_session,
        people,
        "local wap ilo_wap == 1\nlocal both `wap'\ngen a = 1 if `both'",
    )
    db_session.flush()
    db_session.refresh(people)

    problems = stata.replay(db_session, people)

    # Asserted on the macro rather than on the list being empty: this replays
    # over data that still holds what the first run created, so `gen a`
    # reports the name is taken. That is the replay working - after a real
    # export the variable is gone - and not what this test is about.
    assert not [one for one in problems if "macro" in one], problems


def test_a_macro_standing_for_nothing_can_still_be_written(people, db_session):
    """An empty definition is how a condition gets switched off without
    deleting the lines that use it. Expansion then leaves a leading space,
    which was read as an empty verb and refused a command that was fine."""
    results = stata.run_script(
        db_session, people, "local prefix\n`prefix' gen x = 1"
    )
    assert results[-1].command == "gen x = 1"


def test_a_command_that_is_only_an_empty_macro_says_so(people, db_session):
    """Rather than "'' is not a command this understands", which names
    nothing and points at nothing."""
    with pytest.raises(stata.CommandError) as raised:
        stata.run_script(db_session, people, "local nothing\n`nothing'")
    assert "nothing but macros" in str(raised.value)
