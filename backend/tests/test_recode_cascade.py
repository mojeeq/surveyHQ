"""A real recode cascade, run as it was written.

This is the ILO employment classification from a labour force survey, pasted in
the shape it is actually kept in: tab indented, trailing `//` comments, a
`label define` broken over lines with `///`, and a last rule that catches
everything the earlier ones did not.

It is here because it was wrong. Every line ran and reported success, and the
final rule

    replace ilo_lfs_emp = 3 if !inlist(ilo_lfs_emp, 1, 2) & ilo_wap == 1

matched no rows, because SQL answers `NOT (NULL IN (1, 2))` with NULL and a
WHERE clause reads NULL as no. Nobody came out as "not in employment". A
published unemployment figure would have been short by exactly the people the
rule existed to count.

So this test is the whole feature end to end rather than a unit: the script as
typed, through the parser, the translator and DuckDB, and then the nine people
read back out and checked one at a time against what Stata gives.
"""

from __future__ import annotations

import pandas as pd
import pytest
from sqlalchemy import select

from app.models import Dataset
from app.services import stata
from tests.test_api_analytics import _stata_bytes, _zip_bytes

# Nine people, one for each way through the cascade.
PEOPLE = pd.DataFrame(
    {
        "pid": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0],
        "ilo_wap": [1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 0.0],
        "main_activity": [1.0, 3.0, 2.0, 2.0, 9.0, 9.0, 9.0, 9.0, 1.0],
        "prod_purpose": [0.0, 0.0, 1.0, 9.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        "inc_2nd_activity": [0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0],
        "additional_work": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        "help_family": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        "reason_absent": [0.0, 0.0, 0.0, 0.0, 0.0, 2.0, 0.0, 0.0, 0.0],
        "return_work": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0],
        "continue_income": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
    }
)

# What Stata makes of each of them.
#   1, 2  employed, by their main activity
#   3     employed, farming for sale
#   5     employed, by a second activity
#   6, 7  employed but temporarily absent
#   4, 8  of working age and nothing else matched, so not in employment
#   9     not of working age, so the variable stays missing
STATA_SAYS = {1: 1, 2: 1, 3: 1, 4: 3, 5: 1, 6: 2, 7: 2, 8: 3, 9: None}

# The tabs are written as escapes rather than typed, so that the file itself
# holds no mixed indentation while the script still reaches the parser with the
# tabs a pasted do-file really carries.
SCRIPT = "\n".join(
    [
        "gen ilo_lfs_emp=.",
        "\treplace ilo_lfs_emp=1 if (main_activity==1 | main_activity==3 |"
        " inc_2nd_activity==1 | additional_work==1 | help_family==1)"
        " & ilo_wap==1\t\t// Employed",
        "\t\treplace ilo_lfs_emp=1 if main_activity==2 & inlist(prod_purpose,1,2)"
        " & ilo_wap==1 // Employed: Farming activities",
        "\t\treplace ilo_lfs_emp=2 if (inlist(reason_absent,1,2,3,4) | return_work==1"
        " | continue_income==1) & ilo_wap==1 // Employed: temporary absent (reasons)",
        "\t  replace ilo_lfs_emp=3 if !inlist(ilo_lfs_emp,1,2)"
        " & ilo_wap==1\t\t\t\t// Not in employment",
        "\t\t\tlabel define ilo_lfs_emp1 \t\t\t///",
        '\t\t\t\t\t1 "1 - Employed Person" \t\t///',
        '\t\t\t\t\t2 "2 - Employed but temporary absent" \t///',
        '\t\t\t\t\t3 "3 - Not in employment"',
        "\t\t\tlabel value ilo_lfs_emp ilo_lfs_emp1",
        '\t\t\tlabel var ilo_lfs_emp "Employment"',
    ]
)


@pytest.fixture
def people(client, auth_headers, request, db_session) -> Dataset:
    made = client.post(
        "/api/v1/projects",
        headers=auth_headers,
        json={"name": f"LFS {request.node.name[:30]}"},
    ).json()
    uploaded = client.post(
        "/api/v1/datasets/upload",
        headers=auth_headers,
        files={
            "file": (
                "lfs.zip",
                _zip_bytes({"recode_people.dta": _stata_bytes(PEOPLE)}),
                "application/zip",
            )
        },
        data={"project_id": made["id"]},
    )
    assert uploaded.status_code == 201, uploaded.text
    found = (
        db_session.execute(
            select(Dataset).where(
                Dataset.project_id == made["id"], Dataset.name == "recode_people"
            )
        )
        .scalars()
        .first()
    )
    assert found is not None
    return found


def classification(dataset: Dataset) -> dict[int, int | None]:
    import duckdb

    rows = duckdb.connect().execute(
        "select pid, ilo_lfs_emp from read_parquet(?) order by pid",
        [dataset.storage_path],
    ).fetchall()
    return {int(row[0]): row[1] for row in rows}


def test_the_cascade_classifies_everybody_the_way_stata_does(people, db_session):
    stata.run_script(db_session, people, SCRIPT)
    db_session.flush()
    db_session.refresh(people)

    assert classification(people) == STATA_SAYS


def test_the_last_rule_catches_the_people_nothing_else_did(people, db_session):
    """The line this was all about, counted rather than inferred.

    `replace` reports how many rows it changed, and the bug showed up there
    first: 0 where it should have been 2. Reading the count keeps the test
    honest about which rule did the work, rather than letting an earlier rule
    happen to produce the right totals.
    """
    results = stata.run_script(db_session, people, SCRIPT)
    db_session.flush()

    catch_all = next(
        one for one in results if one.command.startswith("replace ilo_lfs_emp=3")
    )
    assert "2 row(s)" in catch_all.message


def test_somebody_outside_working_age_is_left_missing(people, db_session):
    """Every rule is conditioned on ilo_wap, so a child is none of the three.

    Worth its own test: the fix makes missing values match more conditions, and
    the failure it could cause is over-reach - sweeping people into category 3
    who were deliberately left out.
    """
    stata.run_script(db_session, people, SCRIPT)
    db_session.flush()
    db_session.refresh(people)

    assert classification(people)[9] is None


def test_the_labels_survive_the_script(people, db_session):
    stata.run_script(db_session, people, SCRIPT)
    db_session.flush()
    db_session.refresh(people)

    built = next(one for one in people.variables if one.name == "ilo_lfs_emp")
    assert built.label == "Employment"
    assert built.value_labels == {
        "1": "1 - Employed Person",
        "2": "2 - Employed but temporary absent",
        "3": "3 - Not in employment",
    }
