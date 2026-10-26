"""A dashboard's date-range filter.

Dates were left out of a dashboard's filters, so a fieldwork board could not
show today's interviews or this week's. A date variable gets a range control
now; these fix what each choice means, that the query engine reads a date
whether it is kept as a date or as text, and that a saved view's range narrows
an exported file and is said under its title.

The cases in RANGES are the same ones frontend/src/lib/__tests__/
date-range.test.ts checks, because the browser works the live page's ranges
out and the server works out a file's, and the two must agree.
"""

from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from app.services import date_ranges
from tests.test_api_analytics import _stata_bytes, _zip_bytes

THURSDAY = dt.date(2026, 11, 12)

# (choice, today, first day, first day after)
RANGES = [
    ("dates:today", THURSDAY, "2026-11-12", "2026-11-13"),
    ("dates:yesterday", THURSDAY, "2026-11-11", "2026-11-12"),
    ("dates:last_7", THURSDAY, "2026-11-06", "2026-11-13"),
    ("dates:last_30", THURSDAY, "2026-10-14", "2026-11-13"),
    ("dates:this_week", THURSDAY, "2026-11-09", "2026-11-13"),
    ("dates:this_month", THURSDAY, "2026-11-01", "2026-11-13"),
    ("dates:last_month", THURSDAY, "2026-10-01", "2026-11-01"),
    ("dates:last_month", dt.date(2026, 1, 5), "2025-12-01", "2026-01-01"),
    ("dates:2026-11-01..2026-11-15", THURSDAY, "2026-11-01", "2026-11-16"),
    ("dates:..2026-11-15", THURSDAY, None, "2026-11-16"),
    ("dates:2026-11-01..", THURSDAY, "2026-11-01", None),
]


@pytest.mark.parametrize(("choice", "today", "first", "after"), RANGES)
def test_each_choice_is_the_days_it_says(choice, today, first, after):
    start, end = date_ranges.bounds(choice, today)
    assert (start.isoformat() if start else None) == first
    assert (end.isoformat() if end else None) == after


def test_a_choice_in_words():
    assert date_ranges.describe("dates:last_7", THURSDAY) == "Last 7 days (6 Nov 2026 to 12 Nov 2026)"
    assert date_ranges.describe("dates:today", THURSDAY) == "Today (12 Nov 2026)"
    assert date_ranges.describe("dates:2026-11-01..", THURSDAY) == "from 1 Nov 2026"


@pytest.fixture
def dated(client, auth_headers, request) -> str:
    """Six interviews over a week, their date kept twice: as text the way an
    export writes it, and as a real date."""
    days = ["2026-11-01", "2026-11-03", "2026-11-05", "2026-11-05", "2026-11-07", "2026-11-09"]
    frame = pd.DataFrame(
        {
            "interview__key": [f"k{i}" for i in range(6)],
            "when_text": [f"{day}T10:30:00" for day in days],
            "when": pd.to_datetime([f"{day} 17:45" for day in days]),
        }
    )
    name = request.node.name[:40]
    uploaded = client.post(
        "/api/v1/datasets/upload",
        headers=auth_headers,
        files={"file": (f"{name}.zip", _zip_bytes({f"{name}.dta": _stata_bytes(frame)}),
                        "application/zip")},
    ).json()
    return uploaded["datasets"][0]["id"]


def counted(client, auth_headers, dataset_id: str, variable: str, choice: str) -> int:
    conditions = [
        condition.model_dump(mode="json")
        for condition in date_ranges.conditions(variable, choice, THURSDAY)
    ]
    response = client.post(
        "/api/v1/analytics/query",
        headers=auth_headers,
        json={
            "dataset_id": dataset_id,
            "spec": {
                "measures": [{"agg": "count", "alias": "n"}],
                "filters": {"op": "and", "conditions": conditions, "groups": []},
            },
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["rows"][0][0]


@pytest.mark.parametrize("variable", ["when", "when_text"])
def test_a_range_counts_the_whole_of_its_last_day(client, auth_headers, dated, variable):
    # The 3rd to the 5th: three interviews, both of the 5th's included though
    # one was at a quarter to six in the evening.
    assert counted(client, auth_headers, dated, variable, "dates:2026-11-03..2026-11-05") == 3


@pytest.mark.parametrize("variable", ["when", "when_text"])
def test_a_named_range_against_today(client, auth_headers, dated, variable):
    # Last 7 days on the 12th: the 6th to the 12th, so the 7th and the 9th.
    assert counted(client, auth_headers, dated, variable, "dates:last_7") == 2
    assert counted(client, auth_headers, dated, variable, "dates:2026-11-06..") == 2


def test_a_file_from_a_view_is_narrowed_to_its_range(client, auth_headers, dated, db_session):
    from app.models import Dashboard
    from app.services import static_export

    board = client.post(
        "/api/v1/dashboards", headers=auth_headers, json={"name": "Fieldwork week"}
    ).json()
    client.patch(
        f"/api/v1/dashboards/{board['id']}",
        headers=auth_headers,
        json={"filters": [{"variable": "when", "dataset_id": dated, "label": "Interview date",
                           "kind": "dates"}]},
    )
    db_session.expire_all()
    dashboard = db_session.get(Dashboard, board["id"])
    # No dropdown of every timestamp in the file.
    assert static_export._filters_for(dashboard) == []
    payload = static_export.build_payload(
        db_session, dashboard, render=lambda widget, filters: {},
        pinned={"when": "dates:2026-11-03..2026-11-05"},
    )
    assert payload["pinned"] == [
        {"variable": "when", "label": "Interview date", "value": "3 Nov 2026 to 5 Nov 2026"}
    ]
    narrowed = static_export.pinned_filters({"when": "dates:2026-11-03..2026-11-05"})
    assert [(c.operator.value, c.value) for c in narrowed.conditions] == [
        ("on_or_after", "2026-11-03"),
        ("before", "2026-11-06"),
    ]
