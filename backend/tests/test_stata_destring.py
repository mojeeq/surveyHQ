"""destring: text that holds numbers, made into numbers.

An export that writes every column as a string is ordinary, and nothing can
be summed, compared or charted as a quantity until it is converted. What is
worth pinning is Stata's rule for when a variable converts at all - every
value a number, a blank or a missing value - because a looser rule here
would convert a variable the do-file it came from leaves alone, and the two
would then disagree with no error anywhere.
"""

from __future__ import annotations

import math

import pandas as pd
import pytest
from sqlalchemy import select

from app.models import Dataset
from app.services import stata
from app.services.stata import ScriptError
from tests.test_api_analytics import _stata_bytes, _zip_bytes

# Every column is text, as an export that wrote strings throughout has it.
ROSTER = pd.DataFrame(
    {
        "id": [1.0, 2.0, 3.0, 4.0],
        "age": ["34", " 7", "", "."],
        "income": ["1,200", "$350", "90", "."],
        "share": ["50%", "12.5%", "", "100%"],
        "code": ["12", "N/A", "7", "x"],
        # All of these are numbers to DuckDB's cast and none of them to Stata.
        "odd": ["inf", "nan", "1_000", "5"],
        "decimal": ["1,5", "2,25", "3", ""],
        "signed": ["-4", "+2.5", "1e3", ".5"],
    }
)


@pytest.fixture
def project(client, auth_headers, request, db_session) -> dict:
    made = client.post(
        "/api/v1/projects",
        headers=auth_headers,
        json={"name": f"D {request.node.name[:34]}"},
    ).json()
    uploaded = client.post(
        "/api/v1/datasets/upload",
        headers=auth_headers,
        files={
            "file": (
                "export.zip",
                _zip_bytes({"roster.dta": _stata_bytes(ROSTER)}),
                "application/zip",
            )
        },
        data={"project_id": made["id"]},
    )
    assert uploaded.status_code == 201, uploaded.text
    return {"id": made["id"]}


def script(db_session, project: dict, text: str):
    outcome = stata.run_project_script(db_session, project["id"], f"use roster\n{text}\nsave as out")
    db_session.flush()
    return outcome


def out(db_session, project: dict) -> Dataset:
    return db_session.execute(
        select(Dataset).where(Dataset.project_id == project["id"], Dataset.name == "out")
    ).scalars().one()


def values(dataset: Dataset, name: str) -> list:
    return [
        None if (isinstance(v, float) and math.isnan(v)) or v is None else v
        for v in pd.read_parquet(dataset.storage_path)[name].tolist()
    ]


def is_numeric(dataset: Dataset, name: str) -> bool:
    return pd.api.types.is_numeric_dtype(pd.read_parquet(dataset.storage_path)[name])


def messages(outcome) -> str:
    return " | ".join(step.message for step in outcome.results)


def test_replace_makes_a_number_with_blanks_and_dots_missing(db_session, project):
    script(db_session, project, "destring age, replace")
    data = out(db_session, project)
    assert is_numeric(data, "age")
    assert values(data, "age") == [34.0, 7.0, None, None]


def test_the_converted_variable_can_be_used_as_a_number(db_session, project):
    """The reason for the command: arithmetic on it was a type mismatch."""
    with pytest.raises(ScriptError):
        script(db_session, project, "gen next = age + 1")
    script(db_session, project, "destring age, replace\ngen next = age + 1")
    assert values(out(db_session, project), "next") == [35.0, 8.0, None, None]


def test_a_value_that_is_not_a_number_leaves_the_variable_alone_and_says_so(
    db_session, project
):
    """Stata's rule, not an error: the script goes on, and the log names what
    stopped it - which values, so they can be found."""
    outcome = script(db_session, project, "destring code age, replace")
    data = out(db_session, project)
    assert not is_numeric(data, "code")
    assert values(data, "code") == ["12", "N/A", "7", "x"]
    assert is_numeric(data, "age"), "one stubborn variable does not stop the others"
    said = messages(outcome)
    assert "code: contains nonnumeric characters" in said
    assert '"N/A"' in said and "left as text" in said


def test_force_makes_what_is_not_a_number_missing(db_session, project):
    outcome = script(db_session, project, "destring code, replace force")
    assert values(out(db_session, project), "code") == [12.0, None, 7.0, None]
    assert "2 nonnumeric value(s) made missing" in messages(outcome)


def test_what_duckdb_would_cast_and_stata_would_not_stays_text(db_session, project):
    """inf, nan and 1_000 all cast to DOUBLE. Converting them would make a
    variable numeric here that is a string in the do-file."""
    script(db_session, project, "destring odd, replace")
    assert not is_numeric(out(db_session, project), "odd")


def test_signs_exponents_and_a_leading_point_are_numbers(db_session, project):
    script(db_session, project, "destring signed, replace")
    assert values(out(db_session, project), "signed") == [-4.0, 2.5, 1000.0, 0.5]


def test_ignore_removes_the_characters_named(db_session, project):
    script(db_session, project, 'destring income, replace ignore(",$")')
    assert values(out(db_session, project), "income") == [1200.0, 350.0, 90.0, None]


def test_percent_removes_the_sign_and_divides_by_a_hundred(db_session, project):
    script(db_session, project, "destring share, replace percent")
    assert values(out(db_session, project), "share") == [0.5, 0.125, None, 1.0]


def test_dpcomma_reads_a_comma_as_the_decimal_point(db_session, project):
    script(db_session, project, "destring decimal, replace dpcomma")
    assert values(out(db_session, project), "decimal") == [1.5, 2.25, 3.0, None]


def test_generate_keeps_the_text_and_carries_its_label(db_session, project):
    script(
        db_session,
        project,
        'label variable age "Age in years"\ndestring age, generate(age_n)',
    )
    data = out(db_session, project)
    assert values(data, "age") == ["34", " 7", "", "."]
    assert values(data, "age_n") == [34.0, 7.0, None, None]
    labels = {variable.name: variable.label for variable in data.variables}
    assert labels["age_n"] == "Age in years"


def test_no_variables_means_every_variable(db_session, project):
    """And the ones that will not convert are passed over, not refused."""
    script(db_session, project, "destring, replace")
    data = out(db_session, project)
    assert is_numeric(data, "age") and is_numeric(data, "signed")
    assert not is_numeric(data, "code") and not is_numeric(data, "odd")
    assert values(data, "id") == [1.0, 2.0, 3.0, 4.0]


def test_a_variable_already_numeric_is_passed_over(db_session, project):
    outcome = script(db_session, project, "destring id, replace")
    assert "id: already numeric" in messages(outcome)


@pytest.mark.parametrize(
    "command,complaint",
    [
        ("destring age", "either replace or generate()"),
        ("destring age, replace generate(a2)", "either replace or generate()"),
        ("destring age income, generate(a2)", "one new name for each variable"),
        ("destring age, generate(id)", "already exists"),
        ("destring age, replace float", "'float' is not an option"),
        ("destring nosuch, replace", "not a variable"),
        ("destring income, replace ignore(,)", "ignore() takes the characters in quotes"),
    ],
)
def test_a_command_that_cannot_run_says_why(db_session, project, command, complaint):
    with pytest.raises(ScriptError) as raised:
        script(db_session, project, command)
    assert complaint in str(raised.value)


def test_it_is_replayed_from_the_dataset_command_box(db_session, project):
    """The box records what it ran; destring has to be one of the things a
    newer export gets put back."""
    roster = db_session.execute(
        select(Dataset).where(Dataset.project_id == project["id"], Dataset.name == "roster")
    ).scalars().one()
    stata.run(db_session, roster, "destring age, replace")
    assert stata.entries(roster)[-1] == "destring age, replace"
    assert values(roster, "age") == [34.0, 7.0, None, None]
