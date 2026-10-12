"""A board's numbers as a workbook.

The HTML export is the board: its filters work and its charts redraw. Asked
for by somebody who wants the figures instead - to reconcile against another
system, or to put their own arithmetic beside them - and the thing that must
be true of it is that it agrees with the board it came from. The sheets are
rebuilt from the same cube and the same recipes the exported page rebuilds
them from, and these tests are mostly about that arithmetic.
"""

from __future__ import annotations

import io
import zipfile

import pandas as pd
import pytest

from app.services import export_workbook
from tests.test_api_analytics import _stata_bytes, _zip_bytes


def _cube(dimensions, columns, rows, measures, sort=None):
    return {
        "dimensions": dimensions,
        "filters": [],
        "measures": measures,
        "columns": [{"name": name, "label": label, "type": kind, "data_type": "text"}
                    for name, label, kind in columns],
        "rows": rows,
        "top": None,
        "sort": sort or [],
    }


def test_the_finer_grain_a_filter_needs_is_added_back_up():
    """A cube is held at the widget's grouping crossed with the page's filters.

    The page adds that up again to answer a filter; a workbook answers none,
    so it has to be added up here or every row would appear several times.
    """
    cube = _cube(
        ["province"],
        [("province", "Province", "dimension"), ("interviewer", "Interviewer", "dimension"),
         ("value", "Interviews", "measure")],
        [["Shefa", "int1", 4], ["Shefa", "int2", 6], ["Sanma", "int1", 3]],
        [{"name": "value", "label": "Interviews", "how": "sum", "parts": ["value"]}],
    )
    columns, rows = export_workbook.combine(cube)

    assert [column["label"] for column in columns] == ["Province", "Interviews"]
    assert rows == [["Shefa", 10], ["Sanma", 3]]


def test_a_mean_is_rebuilt_from_its_total_and_its_count():
    """Averaging group averages is not the average, which is why the export
    asks for the parts. A workbook that divided twice would disagree with the
    board it came from."""
    cube = _cube(
        ["province"],
        [("province", "Province", "dimension"), ("interviewer", "Interviewer", "dimension"),
         ("__x0_total", "", "measure"), ("__x0_count", "", "measure")],
        [["Shefa", "int1", 100.0, 1], ["Shefa", "int2", 20.0, 3]],
        [{"name": "mean_age", "label": "Mean age", "how": "mean",
          "parts": ["__x0_total", "__x0_count"]}],
    )
    _, rows = export_workbook.combine(cube)

    # 120 over 4 people, not the average of 100 and 6.67.
    assert rows == [["Shefa", 30.0]]


def test_the_youngest_in_a_province_is_the_youngest_of_its_parts():
    """A minimum combines as a minimum, not as a total and not as a maximum."""
    def over(how: str, label: str):
        return _cube(
            ["province"],
            [("province", "Province", "dimension"), ("interviewer", "Interviewer", "dimension"),
             ("value", label, "measure")],
            [["Shefa", "int1", 31], ["Shefa", "int2", 18], ["Shefa", "int3", 44]],
            [{"name": "value", "label": label, "how": how, "parts": ["value"]}],
        )

    assert export_workbook.combine(over("min", "Youngest"))[1] == [["Shefa", 18]]
    assert export_workbook.combine(over("max", "Oldest"))[1] == [["Shefa", 44]]


def test_a_share_is_a_share_of_the_sheet_it_is_on():
    cube = _cube(
        ["status"],
        [("status", "Status", "dimension"), ("value", "Share", "measure")],
        [["Done", 30], ["Open", 10]],
        [{"name": "value", "label": "Share", "how": "share", "parts": ["value"]}],
    )
    _, rows = export_workbook.combine(cube)

    assert rows == [["Done", 75.0], ["Open", 25.0]]


def test_a_sheet_is_in_the_order_the_widget_is():
    cube = _cube(
        ["province"],
        [("province", "Province", "dimension"), ("value", "Interviews", "measure")],
        [["Sanma", 3], ["Shefa", 10], ["Tafea", 7]],
        [{"name": "value", "label": "Interviews", "how": "sum", "parts": ["value"]}],
        sort=[{"field": "value", "direction": "desc"}],
    )
    table = export_workbook.widget_table({"kind": "chart", "cube": cube})

    assert table is not None
    assert [row[0] for row in table[1]] == ["Shefa", "Tafea", "Sanma"]


def test_a_widget_with_no_numbers_is_named_rather_than_dropped():
    """A reader has to be able to see that nothing went missing."""
    payload = {
        "name": "Fieldwork",
        "generated_at": "2026-10-12T00:00:00+00:00",
        "pages": [{"name": "Home"}],
        "widgets": [
            {"title": "Where the work is", "type": "map", "page": 0, "kind": "snapshot"},
            {"title": "Notes", "type": "text", "page": 0, "kind": "snapshot"},
        ],
    }
    book = export_workbook.workbook(payload)

    assert zipfile.ZipFile(io.BytesIO(book)).namelist(), "a real xlsx"
    sheets = pd.read_excel(io.BytesIO(book), sheet_name=None)
    assert list(sheets) == ["About"], "nothing to put on a sheet of its own"
    about = sheets["About"].astype(str).to_string()
    assert "Where the work is" in about and "a map of locations" in about
    assert "Notes" in about and "a text box" in about


def test_the_workbook_says_what_board_and_what_it_was_narrowed_to():
    payload = {
        "name": "Cook Islands Census 2026",
        "description": "Fieldwork monitoring",
        "generated_at": "2026-10-12T09:30:00+00:00",
        "pages": [{"name": "Home"}],
        "pinned": [{"variable": "island", "label": "Island", "value": "Pukapuka"}],
        "widgets": [],
    }
    about = pd.read_excel(io.BytesIO(export_workbook.workbook(payload)), sheet_name="About")

    text = about.astype(str).to_string() + " ".join(about.columns.astype(str))
    assert "Cook Islands Census 2026" in text
    assert "Fieldwork monitoring" in text
    assert "Island" in text and "Pukapuka" in text
    # Written the way a person writes a date: the cover is read by whoever the
    # file was sent to, not by a machine.
    assert "12 October 2026, 09:30 UTC" in text


def test_the_board_and_its_workbook_hold_the_same_figures(client, auth_headers):
    """End to end against a real board: the sheet matches what the API answers."""
    frame = pd.DataFrame(
        {
            "interview__key": [f"k{i}" for i in range(10)],
            "province": ["Shefa"] * 6 + ["Sanma"] * 4,
            "age": [20.0, 30.0, 40.0, 50.0, 60.0, 10.0, 25.0, 35.0, 45.0, 55.0],
        }
    )
    uploaded = client.post(
        "/api/v1/datasets/upload",
        headers=auth_headers,
        files={"file": ("workbook.zip", _zip_bytes({"workbook.dta": _stata_bytes(frame)}),
                        "application/zip")},
    )
    assert uploaded.status_code == 201, uploaded.text
    dataset_id = uploaded.json()["datasets"][0]["id"]

    board = client.post(
        "/api/v1/dashboards", headers=auth_headers, json={"name": "Workbook board"}
    ).json()
    chart = client.post(
        "/api/v1/dashboards/charts",
        headers=auth_headers,
        json={
            "name": "Mean age by province",
            "dataset_id": dataset_id,
            "chart_type": "bar",
            "spec": {"query": {
                "dimensions": [{"variable": "province"}],
                "measures": [{"agg": "mean", "variable": "age"}],
            }},
        },
    ).json()
    placed = client.post(
        f"/api/v1/dashboards/{board['id']}/widgets",
        headers=auth_headers,
        json={"title": "Mean age by province", "widget_type": "chart", "chart_id": chart["id"]},
    )
    assert placed.status_code == 201, placed.text

    downloaded = client.get(
        f"/api/v1/dashboards/{board['id']}/export.xlsx", headers=auth_headers
    )
    assert downloaded.status_code == 200, downloaded.text
    assert downloaded.headers["content-disposition"].endswith('workbook-board.xlsx"')

    sheets = pd.read_excel(io.BytesIO(downloaded.content), sheet_name=None)
    assert "Mean age by province" in sheets
    sheet = sheets["Mean age by province"].set_index(sheets["Mean age by province"].columns[0])
    means = sheet[sheet.columns[0]]
    assert means["Shefa"] == pytest.approx(frame[frame.province == "Shefa"]["age"].mean())
    assert means["Sanma"] == pytest.approx(frame[frame.province == "Sanma"]["age"].mean())
