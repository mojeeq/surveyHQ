"""The filters of a downloaded or published board, run as the reader's browser runs them.

A board taken away as a file filters itself: the file carries each widget's
numbers by filter value, and the page's own script keeps the rows that match
what is chosen and adds them back up. Three things made that look broken:

- a tick-all-that-apply chart travelled frozen, so on a board made of them
  choosing a province moved almost nothing;
- a date-range filter was left out of the file altogether;
- a dropdown of numbers or days offered "1.0" and "2026-11-03 00:00:00" while
  the rows held 1 and 2026-11-03, so choosing one emptied every chart.

So these build a board with all three, export it, run the template's own
functions under node for a choice of filters, and hold the file's numbers to
the platform's numbers for the same choice - not to numbers worked out here,
which would only test that two copies of an idea agree.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from app.services import date_ranges
from tests.test_api_analytics import _stata_bytes, _zip_bytes

TEMPLATE = Path(__file__).resolve().parents[1] / "app/services/export_assets/dashboard.html"
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(NODE is None, reason="node is not installed here")

NA = np.nan
FRAME = pd.DataFrame(
    {
        "interview__key": [f"h{i}" for i in range(1, 9)],
        # piped, well, rain, river - h8 was never asked
        "water__1": [1.0, 1.0, 0.0, 0.0, 1.0, 0.0, 1.0, NA],
        "water__2": [0.0, 0.0, 1.0, 0.0, 1.0, 0.0, 0.0, NA],
        "water__3": [1.0, 0.0, 1.0, 1.0, 1.0, 0.0, 1.0, NA],
        "water__4": [0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 1.0, NA],
        "province": ["Northern", "Northern", "Southern", "Southern", "Northern", "Southern",
                     "Eastern", "Eastern"],
        # A number with no labels, stored as Stata stores it: a double.
        "team": [1.0, 2.0, 1.0, 2.0, 1.0, 2.0, 1.0, 2.0],
        "when": pd.to_datetime(
            ["2026-11-01", "2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05",
             "2026-11-06", "2026-11-06", "2026-11-07"]
        ),
    }
)
OPTIONS = ["water__1", "water__2", "water__3", "water__4"]
VIEWS = {
    "Options": {"view": "options"},
    "By province": {"view": "by_group", "by": "province"},
    "Combinations": {"view": "combinations", "top": 2},
    "How many": {"view": "how_many"},
    "Together": {"view": "together"},
}


@pytest.fixture
def board(client, auth_headers, request) -> dict:
    name = request.node.name[:40]
    uploaded = client.post(
        "/api/v1/datasets/upload",
        headers=auth_headers,
        files={
            "file": (f"{name}.zip", _zip_bytes({f"{name}.dta": _stata_bytes(FRAME)}),
                     "application/zip")
        },
    ).json()
    dataset_id = uploaded["datasets"][0]["id"]
    dashboard = client.post(
        "/api/v1/dashboards", headers=auth_headers, json={"name": f"Water {name}"}
    ).json()
    client.patch(
        f"/api/v1/dashboards/{dashboard['id']}",
        headers=auth_headers,
        json={
            "filters": [
                {"variable": "province", "dataset_id": dataset_id, "label": "Province"},
                {"variable": "team", "dataset_id": dataset_id, "label": "Team"},
                {"variable": "when", "dataset_id": dataset_id, "label": "Interview date",
                 "kind": "dates"},
            ]
        },
    )
    charts = {
        "Households": {
            "chart_type": "bar",
            "spec": {
                "query": {
                    "dimensions": [{"variable": "province"}],
                    "measures": [{"agg": "count", "alias": "Households"}],
                }
            },
        },
        **{
            title: {
                "chart_type": "horizontal_bar",
                "spec": {"multiselect": {"columns": OPTIONS, "show": "both", **settings}},
            }
            for title, settings in VIEWS.items()
        },
    }
    for title, chart in charts.items():
        made = client.post(
            "/api/v1/dashboards/charts",
            headers=auth_headers,
            json={"name": title, "dataset_id": dataset_id, **chart},
        )
        assert made.status_code == 201, made.text
        added = client.post(
            f"/api/v1/dashboards/{dashboard['id']}/widgets",
            headers=auth_headers,
            json={"title": title, "widget_type": "chart", "chart_id": made.json()["id"]},
        )
        assert added.status_code == 201, added.text
    html = client.get(f"/api/v1/dashboards/{dashboard['id']}/export.html", headers=auth_headers)
    assert html.status_code == 200, html.text
    found = re.search(r'id="board-data">(.*?)</script>', html.text, re.S)
    assert found, "the file carries no data"
    return {"id": dashboard["id"], "payload": json.loads(found.group(1))}


def lifted(*names: str) -> str:
    """Functions out of the template, by source - never a copy kept here."""
    source = TEMPLATE.read_text(encoding="utf-8")
    out = []
    for name in names:
        found = re.search(rf"\n  function {name}\(.*?\n  \}}\n", source, re.S)
        assert found, f"{name} is no longer a plain function in the export template"
        out.append(found.group(0))
    return "".join(out)


SHARED = ("text", "keeps", "inRange", "dateBounds")


def in_the_file(widget: dict, chosen: dict[str, str]) -> dict:
    """What the exported page draws for this widget with these filters chosen."""
    if widget["kind"] == "multiselect":
        program = lifted(*SHARED, "share", "orderedBy", "combineMultiselect")
        call = f"combineMultiselect({json.dumps(widget['multiselect'])})"
    else:
        program = lifted(*SHARED, "typeOf", "sorted", "topN", "combine")
        call = f"combine({json.dumps(widget['cube'])})"
    program = (
        f"var chosen = {json.dumps(chosen)};\n{program}\n"
        f"process.stdout.write(JSON.stringify({call}))"
    )
    run = subprocess.run([str(NODE), "-e", program], capture_output=True, text=True, check=False)
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


def on_the_board(client, auth_headers, board: dict, chosen: dict[str, str]) -> dict[str, dict]:
    """What the platform shows for each widget with the same filters chosen."""
    conditions: list[dict] = []
    for variable, value in chosen.items():
        if date_ranges.is_selection(value):
            conditions.extend(
                condition.model_dump(mode="json")
                for condition in date_ranges.conditions(variable, value, dt.date.today())
            )
        elif variable == "team":
            conditions.append({"variable": variable, "operator": "eq", "value": float(value)})
        else:
            conditions.append({"variable": variable, "operator": "eq", "value": value})
    rendered = client.post(
        f"/api/v1/dashboards/{board['id']}/data",
        headers=auth_headers,
        json={"op": "and", "conditions": conditions, "groups": []},
    )
    assert rendered.status_code == 200, rendered.text
    by_title = {widget["id"]: widget["title"] for widget in board["payload"]["widgets"]}
    return {
        by_title[widget_id]: payload["result"]
        for widget_id, payload in rendered.json()["widgets"].items()
    }


def same(file_result: dict, live_result: dict, title: str) -> None:
    assert [c["name"] for c in file_result["columns"]] == [
        c["name"] for c in live_result["columns"]
    ], title
    file_rows, live_rows = file_result["rows"], live_result["rows"]
    if title == "Households":
        # An ordinary chart's rows come back in the order the file re-sorts
        # them, which is tested elsewhere; here it is the numbers.
        file_rows, live_rows = sorted(file_rows), sorted(live_rows)
    assert len(file_rows) == len(live_rows), (title, file_rows, live_rows)
    for mine, theirs in zip(file_rows, live_rows, strict=True):
        for a, b in zip(mine, theirs, strict=True):
            if isinstance(a, float | int) and isinstance(b, float | int):
                assert a == pytest.approx(b, abs=0.051), (title, mine, theirs)
            else:
                assert a == b, (title, mine, theirs)


def widget(board: dict, title: str) -> dict:
    return next(one for one in board["payload"]["widgets"] if one["title"] == title)


SELECTIONS = [
    {},
    {"province": "Northern"},
    {"team": "1"},
    {"when": "dates:2026-11-02..2026-11-05"},
    {"province": "Southern", "when": "dates:2026-11-01..2026-11-04"},
    {"province": "Eastern"},
]


@pytest.mark.parametrize("chosen", SELECTIONS, ids=lambda one: json.dumps(one))
def test_the_file_shows_what_the_board_shows_for_the_same_filters(
    client, auth_headers, board, chosen
):
    live = on_the_board(client, auth_headers, board, chosen)
    for title in ["Households", *VIEWS]:
        assert widget(board, title).get("kind") != "snapshot", (
            f"{title} was frozen: {widget(board, title).get('frozen_because')}"
        )
        same(in_the_file(widget(board, title), chosen), live[title], title)


def test_a_tick_all_that_apply_chart_follows_the_filters(board):
    """The fault reported: choosing a province moved none of these."""
    everyone = in_the_file(widget(board, "Options"), {})
    northern = in_the_file(widget(board, "Options"), {"province": "Northern"})
    assert everyone["rows"] != northern["rows"]
    assert {row[0]: row[1] for row in northern["rows"]} == {
        "Option 1": 3, "Option 2": 1, "Option 3": 2, "Option 4": 0
    }


def test_a_dropdown_of_numbers_offers_what_the_rows_hold(board):
    team = next(one for one in board["payload"]["filters"] if one["variable"] == "team")
    assert team["values"] == ["1", "2"]
    first = in_the_file(widget(board, "Households"), {"team": "1"})
    assert sum(row[1] for row in first["rows"]) == 4, "choosing team 1 kept nothing"


def test_a_date_filter_travels_as_a_range(board):
    when = next(one for one in board["payload"]["filters"] if one["variable"] == "when")
    assert when["kind"] == "dates"
    assert (when["min"], when["max"]) == ("2026-11-01", "2026-11-07")
    assert "values" in when and not when["values"], "no dropdown of every day"
    few = in_the_file(widget(board, "Households"), {"when": "dates:2026-11-06..2026-11-07"})
    assert sum(row[1] for row in few["rows"]) == 3


@pytest.mark.parametrize("preset", list(date_ranges.PRESETS))
def test_a_named_range_means_the_same_days_in_the_file(preset):
    """Today, This week, Last month and the rest, worked out in the file by the
    board's own rule - checked against the server's copy of it."""
    for today in (dt.date(2026, 11, 12), dt.date(2026, 3, 1), dt.date(2027, 1, 4)):
        program = lifted("dateBounds") + (
            "process.stdout.write(JSON.stringify(dateBounds("
            f"'dates:{preset}', new Date({today.year}, {today.month - 1}, {today.day}))))"
        )
        run = subprocess.run([str(NODE), "-e", program], capture_output=True, text=True,
                             check=False)
        assert run.returncode == 0, run.stderr
        found = json.loads(run.stdout)
        first, after = date_ranges.bounds(f"dates:{preset}", today)
        assert found == {"first": first.isoformat(), "after": after.isoformat()}, (preset, today)


def test_a_share_rounds_as_the_platform_rounds():
    """Half to even, as Python's round does, so an eighth agrees to the digit."""
    program = lifted("share") + (
        "process.stdout.write(JSON.stringify([share(1, 16), share(3, 16), share(1, 3), "
        "share(2, 3), share(0, 0), share(5, 8)]))"
    )
    run = subprocess.run([str(NODE), "-e", program], capture_output=True, text=True, check=False)
    assert run.returncode == 0, run.stderr
    assert json.loads(run.stdout) == [
        round(100 / 16, 1), round(300 / 16, 1), round(100 / 3, 1), round(200 / 3, 1), None,
        round(500 / 8, 1),
    ]
