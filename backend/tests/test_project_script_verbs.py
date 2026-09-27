"""Putting datasets together: merge, append, collapse and contract.

These are the reason a script works at project level rather than on one file.
What is worth pinning is not that a join happens but that it means what a
Stata user expects it to mean: `_merge` counted the way they count it, a `1:1`
that is not one refusing rather than quietly multiplying rows, an append
lining up on names rather than positions, and a collapse replacing what is in
memory instead of adding to it.
"""

from __future__ import annotations

import pandas as pd
import pytest
from sqlalchemy import select

from app.models import Dataset
from app.services import stata
from app.services.stata import ScriptError
from tests.test_api_analytics import _stata_bytes, _zip_bytes

# Three households, six people. hhid is unique in HOUSEHOLDS and repeats in
# PEOPLE, which is the shape every survey export has.
HOUSEHOLDS = pd.DataFrame(
    {
        "hhid": [1.0, 2.0, 3.0],
        "province": ["Shefa", "Sanma", "Tafea"],
        "urban": [1.0, 0.0, 0.0],
    }
)
PEOPLE = pd.DataFrame(
    {
        "hhid": [1.0, 1.0, 2.0, 2.0, 2.0, 4.0],
        "age": [40.0, 9.0, 33.0, 31.0, 4.0, 25.0],
        "wage": [500.0, 0.0, 300.0, 200.0, 0.0, 100.0],
    }
)
# A second round, with a question the first did not have.
ROUND2 = pd.DataFrame(
    {"hhid": [5.0, 6.0], "province": ["Torba", "Penama"], "phone": [1.0, 0.0]}
)


@pytest.fixture
def project(client, auth_headers, request, db_session) -> dict:
    made = client.post(
        "/api/v1/projects",
        headers=auth_headers,
        json={"name": f"P {request.node.name[:34]}"},
    ).json()
    uploaded = client.post(
        "/api/v1/datasets/upload",
        headers=auth_headers,
        files={
            "file": (
                "export.zip",
                _zip_bytes(
                    {
                        "households.dta": _stata_bytes(HOUSEHOLDS),
                        "people.dta": _stata_bytes(PEOPLE),
                        "round2.dta": _stata_bytes(ROUND2),
                    }
                ),
                "application/zip",
            )
        },
        data={"project_id": made["id"]},
    )
    assert uploaded.status_code == 201, uploaded.text
    return {"id": made["id"]}


def script(db_session, project: dict, text: str):
    outcome = stata.run_project_script(db_session, project["id"], text)
    db_session.flush()
    return outcome


def saved(db_session, project: dict, name: str) -> Dataset:
    found = (
        db_session.execute(
            select(Dataset).where(
                Dataset.project_id == project["id"], Dataset.name == name
            )
        )
        .scalars()
        .first()
    )
    assert found is not None, f"the script did not save '{name}'"
    return found


def rows_of(dataset: Dataset) -> pd.DataFrame:
    return pd.read_parquet(dataset.storage_path)


def columns_of(dataset: Dataset) -> set[str]:
    return {variable.name for variable in dataset.variables}


# --- merge ------------------------------------------------------------------


def test_merge_keeps_all_three_kinds_of_row_and_says_which(db_session, project):
    """Stata's merge before anything narrows it, and its codes."""
    script(
        db_session,
        project,
        "use people\nmerge m:1 hhid using households\nsave as joined",
    )
    data = rows_of(saved(db_session, project, "joined"))

    # 5 people in households 1 and 2 matched; person in household 4 matched
    # nothing; household 3 has nobody.
    assert sorted(data["_merge"].tolist()) == [1, 2, 3, 3, 3, 3, 3]
    assert set(data.loc[data["_merge"] == 1, "hhid"]) == {4.0}
    assert set(data.loc[data["_merge"] == 2, "hhid"]) == {3.0}


def test_a_using_only_row_keeps_its_key(db_session, project):
    """Every master column is null on that row, so a null key would lose it."""
    script(db_session, project, "use people\nmerge m:1 hhid using households\nsave as j")
    data = rows_of(saved(db_session, project, "j"))
    only_there = data[data["_merge"] == 2]
    assert not only_there["hhid"].isna().any()
    assert only_there["province"].tolist() == ["Tafea"]


def test_the_other_datasets_columns_come_across(db_session, project):
    script(db_session, project, "use people\nmerge m:1 hhid using households\nsave as j")
    assert {"age", "wage", "province", "urban", "_merge"} <= columns_of(
        saved(db_session, project, "j")
    )


def test_a_one_to_one_that_is_not_one_is_refused(db_session, project):
    """The whole value of writing the shape down.

    A 1:1 meeting a repeated key quietly becomes a one-to-many and multiplies
    rows, which is noticed weeks later when a total is too big.
    """
    with pytest.raises(ScriptError) as raised:
        script(db_session, project, "use households\nmerge 1:1 hhid using people")
    assert "not a 1:1 merge" in str(raised.value)
    assert "appearing more than once" in str(raised.value)


def test_the_shape_is_checked_on_the_side_that_claims_to_be_unique(db_session, project):
    """m:1 asks nothing of the data in memory, so this one is allowed."""
    outcome = script(db_session, project, "use people\nmerge m:1 hhid using households")
    assert "Merged households" in outcome.results[-1].message


def test_a_missing_key_matches_nothing_rather_than_everything(db_session, project):
    """Stata pairs missings up. Here that would be a large accident."""
    script(
        db_session,
        project,
        "use people\nreplace hhid = . if age == 25\n"
        "merge m:1 hhid using households\nsave as j",
    )
    data = rows_of(saved(db_session, project, "j"))
    blank = data[data["hhid"].isna()]
    assert len(blank) == 1, "the missing key multiplied out"
    assert blank["_merge"].tolist() == [1]


def test_keepusing_narrows_what_crosses_over(db_session, project):
    script(
        db_session,
        project,
        "use people\nmerge m:1 hhid using households, keepusing(province)\nsave as j",
    )
    columns = columns_of(saved(db_session, project, "j"))
    assert "province" in columns
    assert "urban" not in columns


def test_keep_narrows_which_rows_survive(db_session, project):
    script(
        db_session,
        project,
        "use people\nmerge m:1 hhid using households, keep(match)\nsave as j",
    )
    data = rows_of(saved(db_session, project, "j"))
    assert set(data["_merge"]) == {3}
    assert len(data) == 5


def test_nogen_leaves_no_merge_column(db_session, project):
    script(
        db_session,
        project,
        "use people\nmerge m:1 hhid using households, nogen\nsave as j",
    )
    assert "_merge" not in columns_of(saved(db_session, project, "j"))


def test_a_variable_on_both_sides_is_kept_from_the_data_in_memory(db_session, project):
    """Stata's rule. Keeping both under invented names leaves somebody to work
    out afterwards which one their analysis should have used."""
    script(
        db_session,
        project,
        "use people\ngen province = \"typed here\"\n"
        "merge m:1 hhid using households\nsave as j",
    )
    data = rows_of(saved(db_session, project, "j"))
    matched = data[data["_merge"] == 3]
    assert set(matched["province"]) == {"typed here"}


def test_merging_twice_without_dropping_merge_says_so(db_session, project):
    with pytest.raises(ScriptError) as raised:
        script(
            db_session,
            project,
            "use people\nmerge m:1 hhid using households\n"
            "merge m:1 hhid using households",
        )
    assert "_merge is already there" in str(raised.value)


def test_a_shape_that_is_not_a_shape_says_what_the_shapes_are(db_session, project):
    with pytest.raises(ScriptError) as raised:
        script(db_session, project, "use people\nmerge hhid using households")
    assert "merge 1:1" in str(raised.value)


def test_many_to_many_is_not_offered(db_session, project):
    with pytest.raises(ScriptError) as raised:
        script(db_session, project, "use people\nmerge m:m hhid using households")
    assert "'m:m' is not a merge" in str(raised.value)


def test_a_key_the_other_side_lacks_says_which(db_session, project):
    with pytest.raises(ScriptError) as raised:
        script(db_session, project, "use people\nmerge m:1 wage using households")
    assert "no variable(s) called: wage" in str(raised.value)


def test_merged_data_will_not_be_saved_over_what_it_was_loaded_from(db_session, project):
    """It is no longer that dataset, so a bare save has nothing to write over."""
    with pytest.raises(ScriptError) as raised:
        script(
            db_session,
            project,
            "use people\nmerge m:1 hhid using households\nsave, replace",
        )
    assert "did not come from a single dataset" in str(raised.value)


# --- append -----------------------------------------------------------------


def test_append_stacks_rows_and_lines_up_on_names(db_session, project):
    script(db_session, project, "use households\nappend using round2\nsave as both")
    data = rows_of(saved(db_session, project, "both"))
    assert len(data) == 5
    assert sorted(data["hhid"].tolist()) == [1.0, 2.0, 3.0, 5.0, 6.0]


def test_a_variable_only_one_side_has_is_missing_on_the_others_rows(db_session, project):
    """Which is what makes appending two rounds safe when a question was added."""
    script(db_session, project, "use households\nappend using round2\nsave as both")
    data = rows_of(saved(db_session, project, "both"))
    assert data.loc[data["hhid"] == 1.0, "phone"].isna().all()
    assert data.loc[data["hhid"] == 5.0, "urban"].isna().all()
    assert data.loc[data["hhid"] == 5.0, "phone"].tolist() == [1.0]


def test_text_stacked_on_a_number_is_refused_rather_than_coerced(db_session, project):
    with pytest.raises(ScriptError) as raised:
        script(
            db_session,
            project,
            "use households\ngen phone = \"yes\"\nappend using round2",
        )
    assert "is text here and a number in 'round2'" in str(raised.value)


def test_append_needs_a_dataset(db_session, project):
    with pytest.raises(ScriptError) as raised:
        script(db_session, project, "use households\nappend")
    assert "append using" in str(raised.value)


# --- collapse ---------------------------------------------------------------


def test_collapse_makes_one_row_per_group(db_session, project):
    script(
        db_session,
        project,
        "use people\nmerge m:1 hhid using households, keep(match)\n"
        "collapse (mean) wage (count) age, by(province)\nsave as by_province",
    )
    data = rows_of(saved(db_session, project, "by_province"))
    assert sorted(data["province"].tolist()) == ["Sanma", "Shefa"]
    shefa = data[data["province"] == "Shefa"].iloc[0]
    assert shefa["wage"] == pytest.approx(250.0)
    assert shefa["age"] == 2


def test_a_bare_varlist_means_the_mean(db_session, project):
    script(db_session, project, "use people\ncollapse wage, by(hhid)\nsave as m")
    data = rows_of(saved(db_session, project, "m"))
    assert data[data["hhid"] == 1.0]["wage"].tolist() == [250.0]


def test_collapse_with_no_by_gives_one_row(db_session, project):
    script(db_session, project, "use people\ncollapse (sum) wage\nsave as total")
    data = rows_of(saved(db_session, project, "total"))
    assert len(data) == 1
    assert data["wage"].tolist() == [1100.0]


def test_collapse_replaces_what_is_in_memory(db_session, project):
    """A person-level file becomes a province-level one, as in Stata."""
    script(db_session, project, "use people\ncollapse (sum) wage, by(hhid)\nsave as s")
    columns = columns_of(saved(db_session, project, "s"))
    assert columns == {"hhid", "wage"}, "age survived a collapse that never named it"


def test_collapsing_the_variable_the_rows_are_grouped_by_is_refused(db_session, project):
    with pytest.raises(ScriptError) as raised:
        script(db_session, project, "use people\ncollapse (mean) hhid, by(hhid)")
    assert "cannot" in str(raised.value)


def test_a_statistic_that_is_not_one_is_read_as_a_variable_and_says_so(
    db_session, project
):
    with pytest.raises(ScriptError) as raised:
        script(db_session, project, "use people\ncollapse (nonsense) wage, by(hhid)")
    assert "not a variable" in str(raised.value)


def test_a_comparison_is_stored_as_a_number_so_it_can_be_summed(db_session, project):
    """Stata has no boolean, and everything downstream assumes that.

    DuckDB answers `age >= 18` with a BOOLEAN, and refuses `sum(BOOLEAN)`
    outright, so a column left that way cannot be counted, averaged into a
    proportion, or charted as anything but true and false. The preview hands
    back 0/1 whichever it is stored as, so this has to be checked by summing
    it rather than by looking at it.
    """
    script(
        db_session,
        project,
        "use people\ngen adult = age >= 18\ncollapse (sum) adult, by(hhid)\nsave as counted",
    )
    data = rows_of(saved(db_session, project, "counted"))
    assert dict(zip(data["hhid"], data["adult"], strict=False)) == {1.0: 1, 2.0: 2, 4.0: 1}


# --- contract ---------------------------------------------------------------


def test_contract_counts_each_combination(db_session, project):
    script(db_session, project, "use people\ncontract hhid\nsave as counts")
    data = rows_of(saved(db_session, project, "counts"))
    assert dict(zip(data["hhid"], data["_freq"], strict=False)) == {1.0: 2, 2.0: 3, 4.0: 1}


def test_contract_over_two_variables(db_session, project):
    script(
        db_session,
        project,
        "use people\nmerge m:1 hhid using households, keep(match)\n"
        "contract province hhid\nsave as counts",
    )
    data = rows_of(saved(db_session, project, "counts"))
    assert set(data.columns) == {"province", "hhid", "_freq"}
    assert int(data["_freq"].sum()) == 5


# --- the whole thing together -----------------------------------------------


def test_a_script_that_reads_two_files_and_writes_a_third(db_session, project):
    """What the project-level engine exists for, start to finish."""
    outcome = script(
        db_session,
        project,
        """
        use people
        merge m:1 hhid using households, keep(match)
        gen adult = age >= 18
        collapse (sum) adult (count) age, by(province)
        label variable adult "Adults in the province"
        save as province_summary
        """,
    )
    assert [entry.name for entry in outcome.created] == ["province_summary"]

    made = saved(db_session, project, "province_summary")
    data = rows_of(made)
    assert sorted(data["province"].tolist()) == ["Sanma", "Shefa"]
    assert data[data["province"] == "Shefa"]["adult"].tolist() == [1]
    assert data[data["province"] == "Sanma"]["adult"].tolist() == [2]

    label = {v.name: v.label for v in made.variables}
    assert label["adult"] == "Adults in the province"

    # And the two it read are exactly as they were: same rows, and none of the
    # variables the script built along the way.
    people = saved(db_session, project, "people")
    assert len(rows_of(people)) == len(PEOPLE)
    assert "adult" not in columns_of(people)
    assert "_merge" not in columns_of(people)
    households = saved(db_session, project, "households")
    assert len(rows_of(households)) == len(HOUSEHOLDS)
    assert "_merge" not in columns_of(households)
