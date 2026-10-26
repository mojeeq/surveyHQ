"""The commands a cleaning do-file reaches for after gen and merge.

recode, by and bysort with _n and _N, duplicates, reshape, tostring, encode
and decode, foreach and forvalues, sort, gsort, order, assert, and the three
that only report: count, summarize and tabulate. Each is pinned to what a
Stata user expects it to mean, because the do-file is the reference: a recode
whose first matching rule wins, a bysort that numbers within the group in the
bracketed order, a reshape that refuses ids that do not identify the rows.
"""

from __future__ import annotations

import math

import pandas as pd
import pytest

from app.services import script_language, stata
from app.services.stata import ScriptError
from tests.test_api_analytics import _stata_bytes, _zip_bytes
from tests.test_project_script_verbs import rows_of, saved, script

PEOPLE = pd.DataFrame(
    {
        "hhid": [1.0, 1.0, 2.0, 2.0, 2.0, 4.0],
        "age": [40.0, 9.0, 33.0, 31.0, 4.0, 25.0],
        "wage": [500.0, 0.0, 300.0, 200.0, 0.0, 100.0],
        "sex": [1.0, 2.0, 2.0, 1.0, 2.0, 1.0],
    }
)
HOUSEHOLDS = pd.DataFrame(
    {
        "hhid": [1.0, 2.0, 3.0],
        "province": ["Northern", "Highland", "Southern"],
        "urban": [1.0, 0.0, 0.0],
    }
)
INCOMES = pd.DataFrame(
    {
        "hhid": [1.0, 2.0, 3.0],
        "inc2019": [10.0, 20.0, 30.0],
        "inc2020": [11.0, 21.0, 31.0],
        "province": ["Northern", "Highland", "Southern"],
    }
)


@pytest.fixture
def project(client, auth_headers, request) -> dict:
    made = client.post(
        "/api/v1/projects", headers=auth_headers, json={"name": f"C {request.node.name[:34]}"}
    ).json()
    uploaded = client.post(
        "/api/v1/datasets/upload",
        headers=auth_headers,
        files={
            "file": (
                "export.zip",
                _zip_bytes(
                    {
                        "people.dta": _stata_bytes(PEOPLE),
                        "households.dta": _stata_bytes(HOUSEHOLDS),
                        "incomes.dta": _stata_bytes(INCOMES),
                    }
                ),
                "application/zip",
            )
        },
        data={"project_id": made["id"]},
    )
    assert uploaded.status_code == 201, uploaded.text
    return {"id": made["id"]}


def built(db_session, project, text: str) -> pd.DataFrame:
    """What the script leaves in memory, saved under a name of its own."""
    project["built"] = project.get("built", 0) + 1
    name = f"built{project['built']}"
    script(db_session, project, f"{text}\nsave as {name}")
    return rows_of(saved(db_session, project, name))


def column(frame: pd.DataFrame, name: str) -> list:
    return [None if isinstance(v, float) and math.isnan(v) else v for v in frame[name].tolist()]


def messages(db_session, project, text: str) -> list[str]:
    return [result.message for result in script(db_session, project, text).results]


# --- by, bysort, _n and _N --------------------------------------------------


def test_bysort_numbers_rows_within_each_group_in_the_bracketed_order(db_session, project):
    data = built(
        db_session,
        project,
        "use people\nbysort hhid (age): gen rank = _n\nby hhid: gen size = _N",
    )
    # Sorted by household, then age within it, and left sorted.
    assert column(data, "age") == [9, 40, 4, 31, 33, 25]
    assert column(data, "rank") == [1, 2, 1, 2, 3, 1]
    assert column(data, "size") == [2, 2, 3, 3, 3, 1]


def test_a_subscript_reads_another_row_of_the_same_group(db_session, project):
    data = built(
        db_session,
        project,
        "use people\nbysort hhid (age): gen younger = age[_n-1]\n"
        "by hhid: gen youngest = age[1]\nby hhid: gen eldest = age[_N]",
    )
    assert column(data, "younger") == [None, 9, None, 4, 31, None]
    assert column(data, "youngest") == [9, 9, 4, 4, 4, 25]
    assert column(data, "eldest") == [40, 40, 33, 33, 33, 25]


def test_keep_the_first_row_of_each_group(db_session, project):
    data = built(db_session, project, "use people\nbysort hhid (age): keep if _n == 1")
    assert column(data, "hhid") == [1, 2, 4]
    assert column(data, "age") == [9, 4, 25]


def test_n_without_a_prefix_counts_the_whole_data(db_session, project):
    data = built(db_session, project, "use people\ngen n = _n\ngen total = _N")
    assert column(data, "n") == [1, 2, 3, 4, 5, 6]
    assert column(data, "total") == [6] * 6


def test_by_refuses_a_command_that_cannot_run_in_groups(db_session, project):
    with pytest.raises(ScriptError, match="by works with"):
        script(db_session, project, "use people\nby hhid: collapse (mean) age")


# --- sort, gsort, order -----------------------------------------------------


def test_sort_and_gsort(db_session, project):
    assert column(built(db_session, project, "use people\ngsort -age"), "age") == [
        40, 33, 31, 25, 9, 4
    ]
    data = built(db_session, project, "use people\ngsort hhid -wage")
    assert column(data, "wage") == [500, 0, 300, 200, 0, 100]
    data = built(db_session, project, "use people\nsort sex age")
    assert column(data, "age") == [25, 31, 40, 4, 9, 33]


def test_order_moves_columns(db_session, project):
    script(db_session, project, "use people\norder sex age\nsave as out")
    names = [v.name for v in saved(db_session, project, "out").variables]
    assert names[:2] == ["sex", "age"]
    script(db_session, project, "use people\norder hhid, last\nsave as out2")
    names = [v.name for v in saved(db_session, project, "out2").variables]
    assert names[-1] == "hhid"
    script(db_session, project, "use people\norder sex, after(hhid)\nsave as out3")
    names = [v.name for v in saved(db_session, project, "out3").variables]
    assert names[:2] == ["hhid", "sex"]


# --- assert, count, summarize, tabulate -------------------------------------


def test_an_assertion_that_holds_lets_the_script_go_on(db_session, project):
    said = messages(db_session, project, "use people\nassert age >= 0\nbysort hhid: assert _N <= 3")
    assert said[1] == "Assertion is true in all 6 row(s)"


def test_an_assertion_that_fails_stops_the_script_and_says_where(db_session, project):
    with pytest.raises(ScriptError) as stopped:
        script(db_session, project, "use people\nassert age < 35\nsave as never")
    assert stopped.value.line_number == 2
    assert "Assertion is false in 1 of 6 row(s): age < 35. First at row 1" in str(stopped.value)


def test_count(db_session, project):
    said = messages(db_session, project, "use people\ncount\ncount if age > 30")
    assert said[1:] == ["6 row(s)", "3 of 6 row(s) where age > 30"]


def test_summarize_lays_out_the_numbers(db_session, project):
    said = messages(db_session, project, "use people\nsummarize age\nsu age wage, detail")
    lines = said[1].splitlines()
    assert lines[0].split() == ["Variable", "|", "Obs", "Mean", "Std.", "dev.", "Min", "Max"]
    assert lines[2].split() == ["age", "|", "6", "23.67", "14.22", "4", "40"]
    assert "Median" in said[2]


def test_tabulate_one_way_with_labels(db_session, project):
    said = messages(
        db_session,
        project,
        'use people\nlabel define sexes 1 "Male" 2 "Female"\nlabel values sex sexes\ntab sex',
    )
    table = said[-1].splitlines()
    assert table[0].split() == ["sex", "|", "Freq.", "Percent", "Cum."]
    assert table[2].split() == ["Male", "|", "3", "50.00", "50.00"]
    assert table[3].split() == ["Female", "|", "3", "50.00", "100.00"]
    assert table[-1].split() == ["Total", "|", "6", "100.00"]


def test_tabulate_two_way(db_session, project):
    table = messages(db_session, project, "use people\ntab hhid sex")[-1].splitlines()
    assert table[0].strip() == "| sex"
    assert table[1].split() == ["hhid", "|", "1", "2", "|", "Total"]
    assert table[3].split() == ["1", "|", "1", "1", "|", "2"]
    assert table[-1].split() == ["Total", "|", "3", "3", "|", "6"]


def test_a_report_writes_nothing_back_and_is_not_replayed(db_session, project):
    from sqlalchemy import select

    from app.models import Dataset

    people = db_session.execute(
        select(Dataset).where(Dataset.project_id == project["id"], Dataset.name == "people")
    ).scalar_one()
    before = people.storage_path
    stata.run_script(db_session, people, "count\nsummarize\ntab sex\nassert age > 0")
    assert people.storage_path == before
    assert stata.entries(people) == []


# --- duplicates -------------------------------------------------------------


def test_duplicates_report_and_tag(db_session, project):
    said = messages(db_session, project, "use people\nduplicates report hhid")
    report = said[1].splitlines()
    assert report[0] == "Duplicates in terms of hhid"
    assert [line.split() for line in report[4:]] == [
        ["1", "|", "1", "0"], ["2", "|", "2", "1"], ["3", "|", "3", "2"]
    ]
    data = built(db_session, project, "use people\nduplicates tag hhid, generate(dup)")
    assert column(data, "dup") == [1, 1, 2, 2, 2, 0]


def test_dropping_on_some_variables_needs_force(db_session, project):
    with pytest.raises(ScriptError, match="Add force"):
        script(db_session, project, "use people\nduplicates drop hhid")
    data = built(db_session, project, "use people\nduplicates drop hhid, force")
    assert column(data, "hhid") == [1, 2, 4]
    assert column(data, "age") == [40, 33, 25]


def test_dropping_exact_duplicates(db_session, project):
    data = built(db_session, project, "use people\nappend using people\nduplicates drop")
    assert len(data) == 6


# --- recode -----------------------------------------------------------------


def test_recode_into_a_new_variable_with_labels(db_session, project):
    script(
        db_session,
        project,
        'use people\nrecode age (min/17 = 0 "Child") (18/max = 1 "Adult, grown"), gen(adult)'
        "\nsave as out",
    )
    dataset = saved(db_session, project, "out")
    assert column(rows_of(dataset), "adult") == [1, 0, 1, 1, 0, 1]
    adult = next(v for v in dataset.variables if v.name == "adult")
    assert adult.value_labels == {"0": "Child", "1": "Adult, grown"}
    assert adult.label == "RECODE of age"


def test_recode_in_place_takes_the_first_rule_that_fits(db_session, project):
    said = messages(db_session, project, "use people\nrecode wage (0 = .) (0/250 = 1)")
    assert said[1] == "Recoded wage (4 change(s))"
    data = built(db_session, project, "use people\nrecode wage (0 = .) (0/250 = 1)")
    assert column(data, "wage") == [500, None, 300, 1, None, 1]


def test_recode_else_missing_and_if(db_session, project):
    data = built(db_session, project, "use people\nrecode hhid (1 = 10) (else = 0), gen(h)")
    assert column(data, "h") == [10, 10, 0, 0, 0, 0]
    data = built(
        db_session,
        project,
        "use people\nreplace wage = . if wage == 0\nrecode wage (missing = -1), gen(w)",
    )
    assert column(data, "w") == [500, -1, 300, 200, -1, 100]
    data = built(db_session, project, "use people\nrecode age (0/17 = 0) if hhid == 2, gen(x)")
    assert column(data, "x") == [None, None, 33, 31, 0, None]


def test_recode_refuses_text_and_rules_out_of_order(db_session, project):
    with pytest.raises(ScriptError, match="recode works on numbers"):
        script(db_session, project, "use households\nrecode province (1 = 2)")
    with pytest.raises(ScriptError, match="else catches every value left"):
        script(db_session, project, "use people\nrecode age (else = 0) (1 = 2)")


# --- tostring, encode, decode -----------------------------------------------


def test_encode_numbers_text_alphabetically_and_decode_brings_it_back(db_session, project):
    script(
        db_session,
        project,
        "use households\nencode province, gen(pcode)\ndecode pcode, gen(pname)\nsave as out",
    )
    dataset = saved(db_session, project, "out")
    data = rows_of(dataset)
    assert column(data, "pcode") == [2, 1, 3]
    assert column(data, "pname") == column(data, "province")
    pcode = next(v for v in dataset.variables if v.name == "pcode")
    assert pcode.value_labels == {"1": "Highland", "2": "Northern", "3": "Southern"}


def test_encode_with_a_label_set_keeps_its_codes(db_session, project):
    data = built(
        db_session,
        project,
        'use households\nlabel define places 7 "Southern"\n'
        "encode province, gen(pcode) label(places)",
    )
    # Southern keeps 7; the others are numbered after it, alphabetically.
    assert column(data, "pcode") == [9, 8, 7]


def test_tostring_writes_whole_numbers_without_a_point(db_session, project):
    data = built(db_session, project, "use households\ntostring hhid, replace\ntostring urban, gen(u)")
    assert column(data, "hhid") == ["1", "2", "3"]
    assert column(data, "u") == ["1", "0", "0"]


# --- reshape ----------------------------------------------------------------


def test_reshape_long_and_back_to_wide(db_session, project):
    long = built(db_session, project, "use incomes\nreshape long inc, i(hhid) j(year)")
    assert column(long, "hhid") == [1, 1, 2, 2, 3, 3]
    assert column(long, "year") == [2019, 2020] * 3
    assert column(long, "inc") == [10, 11, 20, 21, 30, 31]
    assert column(long, "province")[:2] == ["Northern", "Northern"]

    wide = built(
        db_session,
        project,
        "use incomes\nreshape long inc, i(hhid) j(year)\nreshape wide inc, i(hhid) j(year)",
    )
    assert column(wide, "inc2019") == [10, 20, 30]
    assert column(wide, "inc2020") == [11, 21, 31]
    assert column(wide, "province") == ["Northern", "Highland", "Southern"]


def test_reshape_refuses_ids_that_do_not_identify_the_rows(db_session, project):
    with pytest.raises(ScriptError, match="does not identify the rows"):
        script(db_session, project, "use people\nrename age age1\nreshape long age, i(hhid) j(k)")


def test_reshape_wide_refuses_a_variable_that_varies_within_an_id(db_session, project):
    with pytest.raises(ScriptError, match="wage is not constant within hhid"):
        script(
            db_session,
            project,
            "use people\nbysort hhid: gen line = _n\nreshape wide age, i(hhid) j(line)",
        )


# --- loops ------------------------------------------------------------------


def test_foreach_over_a_varlist_and_forvalues(db_session, project):
    data = built(
        db_session,
        project,
        "use people\n"
        "foreach v of varlist age wage {\n"
        "    gen `v'_twice = `v' * 2\n"
        "}\n"
        "forvalues i = 1/2 {\n"
        "    gen in`i' = hhid == `i'\n"
        "}",
    )
    assert column(data, "age_twice") == [80, 18, 66, 62, 8, 50]
    assert column(data, "wage_twice")[0] == 1000
    assert column(data, "in1") == [1, 1, 0, 0, 0, 0]
    assert column(data, "in2") == [0, 0, 1, 1, 1, 0]


def test_nested_loops_and_lists_in_words_and_macros(db_session, project):
    data = built(
        db_session,
        project,
        "use people\n"
        "local cuts 10 30\n"
        "foreach c of local cuts {\n"
        "    foreach s in 1 2 {\n"
        "        gen a`c'_`s' = age > `c' & sex == `s'\n"
        "    }\n"
        "}\n"
        "foreach n of numlist 5(5)10 {\n"
        "    gen plus`n' = age + `n'\n"
        "}",
    )
    assert column(data, "a30_1") == [1, 0, 0, 1, 0, 0]
    assert column(data, "a10_2") == [0, 0, 1, 0, 0, 0]
    assert column(data, "plus10")[0] == 50


def test_a_failure_inside_a_loop_names_its_line_and_the_turn(db_session, project):
    text = "use people\nforeach v in age height {\n    replace `v' = `v' + 1\n}"
    with pytest.raises(ScriptError) as stopped:
        script(db_session, project, text)
    assert stopped.value.line_number == 3
    assert str(stopped.value).startswith("Line 3 (replace `v' = `v' + 1): ")
    assert str(stopped.value).endswith("(where v is height)")
    # The turn before it ran.
    assert [r.command for r in stopped.value.done] == ["use people", "replace age = age + 1"]


def test_a_loop_has_to_be_closed_and_a_brace_has_to_close_one(db_session, project):
    with pytest.raises(ScriptError, match="never closed"):
        script(db_session, project, "use people\nforeach v in age {\n  gen x = 1")
    with pytest.raises(ScriptError, match="closes nothing"):
        script(db_session, project, "use people\n}")
    with pytest.raises(ScriptError, match="up to a }"):
        script(db_session, project, "use people\nforeach v in age")
    with pytest.raises(ScriptError, match="at most 1,000"):
        script(db_session, project, "use people\nforvalues i = 1/5000 {\n  count\n}")


def test_the_dataset_box_unrolls_a_loop_and_records_what_ran(db_session, project):
    from sqlalchemy import select

    from app.models import Dataset

    people = db_session.execute(
        select(Dataset).where(Dataset.project_id == project["id"], Dataset.name == "people")
    ).scalar_one()
    stata.run_script(db_session, people, "foreach v of varlist age wage {\n  replace `v' = 0\n}")
    assert stata.entries(people) == ["replace age = 0", "replace wage = 0"]


# --- the pieces around them -------------------------------------------------


def test_options_after_a_bracket_with_a_comma_in_it(db_session, project):
    data = built(db_session, project, "use people\negen both = rowtotal(age, wage)")
    assert column(data, "both")[0] == 540


def test_the_editor_is_told_about_the_new_vocabulary():
    served = script_language.language()
    assert {"long", "wide"} == {one["name"] for one in served["subcommands"]["reshape"]}
    assert {"_n", "_N"} == {one["name"] for one in served["row_names"]}
    assert "assert" in served["by_able"]
