"""What the script editor is told the language understands.

The editor colours a script and offers what can come next, from lists this
serves. Each of them is a fact about the engine, so each is held here to the
engine's own table: a command, option or function added there without a line
in `script_language` fails here, rather than working while the editor colours
it as a mistake and never offers it.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.services import script_language, stata, stata_expr
from tests.conftest import sign_in
from tests.test_project_script import project  # noqa: F401 - a fixture


def test_every_command_the_engine_runs_is_described():
    assert set(script_language.COMMANDS) == set(stata.verb_names())


def test_every_spelling_of_a_command_is_offered_under_it():
    described = script_language.language()["commands"]
    spellings = {name for one in described for name in [one["name"], *one["aliases"]]}
    assert spellings == set(stata.verbs())
    gen = next(one for one in described if one["name"] == "gen")
    assert {"g", "generate"} <= set(gen["aliases"])


def test_every_option_a_command_takes_is_described():
    for command, options in stata.OPTIONS.items():
        assert command in stata.verbs(), command
        assert set(script_language.OPTION_NOTES[command]) == set(options), command


def test_the_options_checked_are_the_options_offered():
    """Every check of a command's options reads the one table.

    A literal list at a check is the drift this is against: the editor would
    go on offering what the table says while the command refused it.
    """
    source = Path(stata.__file__).read_text()
    for call in re.findall(r"_reject_unknown_options\(\s*options,\s*([^\n]+)", source):
        assert call.startswith(("OPTIONS[", "tuple(one for one in OPTIONS[", "()")), call


def test_every_function_the_expression_language_takes_is_described():
    expected = set(stata_expr.FUNCTIONS) | stata_expr.SPECIAL
    assert set(script_language.FUNCTIONS) == expected
    served = {one["name"] for one in script_language.language()["functions"]}
    assert served == expected


def test_every_egen_function_and_collapse_statistic_is_described():
    assert set(script_language.EGEN) == (
        set(stata.EGEN_AGGREGATES) | stata.EGEN_ROWWISE | {"group", "tag"}
    )
    assert set(script_language.COLLAPSE) == set(stata.COLLAPSE_STATS)


def test_the_language_is_served_to_anyone_signed_in(client, auth_headers):
    answer = client.get("/api/v1/scripts/language", headers=auth_headers)
    assert answer.status_code == 200, answer.text
    body = answer.json()
    merge = next(one for one in body["commands"] if one["name"] == "merge")
    assert {"keep", "keepusing", "nogen"} <= {one["name"] for one in merge["options"]}
    assert body["merge_shapes"] == ["1:1", "m:1", "1:m"]
    assert client.get("/api/v1/scripts/language").status_code == 401


def test_a_project_names_its_datasets_and_their_variables(
    client, auth_headers, project  # noqa: F811
):
    answer = client.get(f"/api/v1/projects/{project['id']}/script/names", headers=auth_headers)
    assert answer.status_code == 200, answer.text
    (members,) = answer.json()["datasets"]
    assert members["name"] == "members"
    assert members["rows"] == 6
    # In the dataset's own order, which is the order a reader knows them in.
    assert [one["name"] for one in members["variables"]][:4] == [
        "interview__key", "hhid", "age", "wage"
    ]


def test_names_are_only_told_to_somebody_who_can_see_the_project(
    client, auth_headers, project  # noqa: F811
):
    email, password = "names-outsider@example.com", "names-outsider-password-1"
    made = client.post(
        "/api/v1/users",
        headers=auth_headers,
        json={"email": email, "full_name": "Outsider", "role": "viewer", "password": password},
    )
    assert made.status_code in (201, 409), made.text
    outsider = sign_in(client, email, password)
    answer = client.get(f"/api/v1/projects/{project['id']}/script/names", headers=outsider)
    assert answer.status_code == 404
