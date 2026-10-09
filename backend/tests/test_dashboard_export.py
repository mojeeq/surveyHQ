"""The dashboard as one HTML file, with its filters still working.

A board is often wanted somewhere the platform is not: on a ministry's own web
host, beside a report, on a laptop taken to a meeting. A picture of it loses
the thing that makes it a dashboard, which is that the reader can narrow it and
watch the numbers move.

So the file carries data rather than pictures. Each widget's numbers are
exported at the grain its filters need - grouped by what it groups on and by
every variable the page's controls name - and the browser adds them back up.
These cover the arithmetic that makes that sound, which is the part that could
be quietly wrong: a sum of counts is a count, and a mean has to be carried as
its total and its number of values rather than averaged again.
"""

from __future__ import annotations

import json
import re

import pandas as pd
import pytest

from tests.test_api_analytics import _stata_bytes, _zip_bytes


def payload_of(html: str) -> dict:
    found = re.search(r'id="board-data">(.*?)</script>', html, re.S)
    assert found, "the file carries no data"
    return json.loads(found.group(1))


def widget_named(payload: dict, title: str) -> dict:
    return next(widget for widget in payload["widgets"] if widget["title"] == title)


@pytest.fixture
def board(client, auth_headers, request) -> dict:
    """Wages in two provinces, so a filtered mean is not the unfiltered one."""
    frame = pd.DataFrame(
        {
            "interview__key": [f"k{i}" for i in range(8)],
            "province": ["Shefa"] * 4 + ["Sanma"] * 4,
            "wage": [100.0, 200.0, 300.0, 400.0, 1000.0, 1000.0, 1000.0, 2000.0],
        }
    )
    name = request.node.name[:40]
    uploaded = client.post(
        "/api/v1/datasets/upload",
        headers=auth_headers,
        files={
            "file": (
                f"{name}.zip",
                _zip_bytes({f"{name}.dta": _stata_bytes(frame)}),
                "application/zip",
            )
        },
    ).json()
    dataset_id = uploaded["datasets"][0]["id"]

    counts = client.post(
        "/api/v1/dashboards/charts",
        headers=auth_headers,
        json={
            "name": "Interviews by province",
            "dataset_id": dataset_id,
            "chart_type": "bar",
            "spec": {
                "query": {
                    "dimensions": [{"variable": "province"}],
                    "measures": [{"agg": "count", "alias": "Interviews"}],
                }
            },
        },
    ).json()
    means = client.post(
        "/api/v1/dashboards/charts",
        headers=auth_headers,
        json={
            "name": "Mean wage by province",
            "dataset_id": dataset_id,
            "chart_type": "bar",
            "spec": {
                "query": {
                    "dimensions": [{"variable": "province"}],
                    "measures": [{"agg": "mean", "variable": "wage", "alias": "Mean wage"}],
                }
            },
        },
    ).json()
    dashboard = client.post(
        "/api/v1/dashboards", headers=auth_headers, json={"name": "Exportable"}
    ).json()
    for chart in (counts, means):
        client.post(
            f"/api/v1/dashboards/{dashboard['id']}/widgets",
            headers=auth_headers,
            json={"title": chart["name"], "widget_type": "chart", "chart_id": chart["id"]},
        )
    client.patch(
        f"/api/v1/dashboards/{dashboard['id']}",
        headers=auth_headers,
        json={
            "filters": [
                {"variable": "province", "dataset_id": dataset_id, "label": "Province", "page": 0}
            ]
        },
    )
    return {"id": dashboard["id"], "dataset_id": dataset_id}


def export(client, auth_headers, board) -> str:
    response = client.get(
        f"/api/v1/dashboards/{board['id']}/export.html", headers=auth_headers
    )
    assert response.status_code == 200, response.text
    assert "text/html" in response.headers["content-type"]
    assert "attachment" in response.headers["content-disposition"]
    return response.text


def test_the_file_stands_on_its_own(client, auth_headers, board):
    """One page, with the data inside it rather than fetched from a server."""
    html = export(client, auth_headers, board)
    assert html.lstrip().startswith("<!doctype html>")
    assert "/api/v1/" not in html
    payload = payload_of(html)
    assert payload["name"] == "Exportable"
    assert [control["variable"] for control in payload["filters"]] == ["province"]
    assert payload["filters"][0]["values"] == ["Sanma", "Shefa"]


def test_a_count_is_carried_at_the_grain_its_filter_needs(client, auth_headers, board):
    """The point of the whole exercise: the filter has rows to work on."""
    cube = widget_named(payload_of(export(client, auth_headers, board)), "Interviews by province")["cube"]
    assert cube["dimensions"] == ["province"]
    # Grouped on the filter's variable already, so it is tested against that
    # same column rather than a second copy of it.
    assert cube["filters"] == [{"variable": "province", "column": "province"}]
    counts = {row[0]: row[1] for row in cube["rows"]}
    assert counts == {"Shefa": 4, "Sanma": 4}


def test_a_mean_travels_as_its_total_and_its_count(client, auth_headers, board):
    """An average of averages is not an average.

    Shefa's mean wage is 250 and Sanma's is 1,250; the mean over both is 750,
    which is not the average of 250 and 1,250 unless the groups happen to be
    the same size. Carrying the total and the number of values lets the browser
    divide them again and get the right number for any filter.
    """
    cube = widget_named(payload_of(export(client, auth_headers, board)), "Mean wage by province")["cube"]
    recipe = cube["measures"][0]
    assert recipe["how"] == "mean"
    assert len(recipe["parts"]) == 2
    at = {column["name"]: index for index, column in enumerate(cube["columns"])}
    totals = {row[at["province"]]: row[at[recipe["parts"][0]]] for row in cube["rows"]}
    counts = {row[at["province"]]: row[at[recipe["parts"][1]]] for row in cube["rows"]}
    assert totals == {"Shefa": 1000.0, "Sanma": 5000.0}
    assert counts == {"Shefa": 4, "Sanma": 4}
    # What the browser will work out, checked here where it can be:
    assert totals["Shefa"] / counts["Shefa"] == 250.0
    assert sum(totals.values()) / sum(counts.values()) == 750.0


def test_a_widget_that_cannot_be_recomputed_says_so(client, auth_headers, board):
    """A median of medians is not a median, so the tile is frozen and admits it."""
    chart = client.post(
        "/api/v1/dashboards/charts",
        headers=auth_headers,
        json={
            "name": "Median wage",
            "dataset_id": board["dataset_id"],
            "chart_type": "bar",
            "spec": {
                "query": {
                    "dimensions": [{"variable": "province"}],
                    "measures": [{"agg": "median", "variable": "wage", "alias": "Median"}],
                }
            },
        },
    ).json()
    client.post(
        f"/api/v1/dashboards/{board['id']}/widgets",
        headers=auth_headers,
        json={"title": "Median wage", "widget_type": "chart", "chart_id": chart["id"]},
    )
    widget = widget_named(payload_of(export(client, auth_headers, board)), "Median wage")
    assert widget["kind"] == "snapshot"
    assert "median" in widget["frozen_because"]
    # Still drawn, as it stood: a frozen widget is not a blank one.
    assert widget["snapshot"]["result"]["rows"]


def test_survey_answers_cannot_become_script_on_the_page(client, auth_headers, request):
    """The data goes in as data, whatever an interviewer typed into a field."""
    frame = pd.DataFrame(
        {
            "interview__key": ["k1", "k2"],
            "place": ["</script><script>alert(1)</script>", "Shefa"],
        }
    )
    name = request.node.name[:40]
    dataset_id = client.post(
        "/api/v1/datasets/upload",
        headers=auth_headers,
        files={
            "file": (
                f"{name}.zip",
                _zip_bytes({f"{name}.dta": _stata_bytes(frame)}),
                "application/zip",
            )
        },
    ).json()["datasets"][0]["id"]
    chart = client.post(
        "/api/v1/dashboards/charts",
        headers=auth_headers,
        json={
            "name": "Places",
            "dataset_id": dataset_id,
            "chart_type": "bar",
            "spec": {
                "query": {
                    "dimensions": [{"variable": "place"}],
                    "measures": [{"agg": "count", "alias": "n"}],
                }
            },
        },
    ).json()
    dashboard = client.post(
        "/api/v1/dashboards", headers=auth_headers, json={"name": "Hostile"}
    ).json()
    client.post(
        f"/api/v1/dashboards/{dashboard['id']}/widgets",
        headers=auth_headers,
        json={"title": "Places", "widget_type": "chart", "chart_id": chart["id"]},
    )
    html = client.get(
        f"/api/v1/dashboards/{dashboard['id']}/export.html", headers=auth_headers
    ).text
    # The answer survives as text and cannot close the tag it sits in.
    assert "</script><script>alert(1)</script>" not in html
    payload = payload_of(html)
    rows = payload["widgets"][0]["cube"]["rows"]
    assert any("alert(1)" in str(row[0]) for row in rows)


def test_another_users_dashboard_cannot_be_exported(client, auth_headers, board):
    """The export is a read of the whole board, so it takes the same permission."""
    missing = client.get(
        "/api/v1/dashboards/00000000-0000-0000-0000-000000000000/export.html",
        headers=auth_headers,
    )
    assert missing.status_code == 404


def test_a_table_with_no_cell_values_travels_as_a_table_with_no_cell_values(
    client, auth_headers, board
):
    """The file draws its own tables, so it has to be told there is nothing
    to draw in them.

    Without the flag the browser falls back to the one-way behaviour and
    prints a column of counts headed by the measure's name - which is the
    column the board was set up not to have.
    """
    chart = client.post(
        "/api/v1/dashboards/charts",
        headers=auth_headers,
        json={
            "name": "Provinces",
            "dataset_id": board["dataset_id"],
            "chart_type": "crosstab",
            "spec": {"crosstab": {"row_variable": "province", "measure": None}},
        },
    ).json()
    client.post(
        f"/api/v1/dashboards/{board['id']}/widgets",
        headers=auth_headers,
        json={"title": "Provinces", "widget_type": "chart", "chart_id": chart["id"]},
    )
    widget = widget_named(payload_of(export(client, auth_headers, board)), "Provinces")
    assert widget["crosstab"]["show_values"] is False
    assert widget["crosstab"]["measure_label"] == ""
    # The counts are still carried, because that is how the file knows which
    # categories survive a filter.
    assert {row[0] for row in widget["cube"]["rows"]} == {"Shefa", "Sanma"}


def test_a_counted_table_still_says_so(client, auth_headers, board):
    """The flag must not turn every existing exported table into a list."""
    chart = client.post(
        "/api/v1/dashboards/charts",
        headers=auth_headers,
        json={
            "name": "Counted",
            "dataset_id": board["dataset_id"],
            "chart_type": "crosstab",
            "spec": {"crosstab": {"row_variable": "province"}},
        },
    ).json()
    client.post(
        f"/api/v1/dashboards/{board['id']}/widgets",
        headers=auth_headers,
        json={"title": "Counted", "widget_type": "chart", "chart_id": chart["id"]},
    )
    widget = widget_named(payload_of(export(client, auth_headers, board)), "Counted")
    assert widget["crosstab"]["show_values"] is True
    assert widget["crosstab"]["measure_label"] == "Count"


# --- One province's file ----------------------------------------------------
#
# A view already names a selection somebody wants a report of, so the export
# takes one. The point of these is that the file is narrowed rather than
# preselected: a standalone file is the copy nobody can withdraw, and one that
# quietly carried every other province's numbers would be the wrong thing to
# send to a provincial office.


def _view(client, auth_headers, board, name: str, filters: dict) -> str:
    created = client.post(
        f"/api/v1/dashboards/{board['id']}/views",
        headers=auth_headers,
        json={"name": name, "state": {"filters": filters}},
    )
    assert created.status_code in (200, 201), created.text
    return created.json()["id"]


def _pinned_payload(client, auth_headers, board, view_id: str) -> dict:
    response = client.get(
        f"/api/v1/dashboards/{board['id']}/export.html?view={view_id}", headers=auth_headers
    )
    assert response.status_code == 200, response.text
    return payload_of(response.text)


def test_a_pinned_export_carries_only_that_province(client, auth_headers, board):
    view = _view(client, auth_headers, board, "Shefa", {"province": "Shefa"})
    payload = _pinned_payload(client, auth_headers, board, view)

    everything = json.dumps(payload)
    assert "Shefa" in everything
    # The whole point. Not "Sanma is not selected" but "Sanma is not in here".
    assert "Sanma" not in everything


def test_a_pinned_export_drops_the_control_rather_than_presetting_it(
    client, auth_headers, board
):
    view = _view(client, auth_headers, board, "Shefa", {"province": "Shefa"})
    payload = _pinned_payload(client, auth_headers, board, view)

    # No picker: there is nothing left to choose, and a dropdown offering one
    # option is furniture.
    assert [control["variable"] for control in payload["filters"]] == []
    # And the file says what it is of, or Shefa's printout and Sanma's are
    # indistinguishable on a desk.
    assert payload["pinned"] == [
        {"variable": "province", "label": "Province", "value": "Shefa"}
    ]


def test_a_pinned_export_reports_that_province_s_own_numbers(client, auth_headers, board):
    """Shefa's wages are 100, 200, 300, 400; the country's mean is not Shefa's."""
    view = _view(client, auth_headers, board, "Shefa", {"province": "Shefa"})
    payload = _pinned_payload(client, auth_headers, board, view)

    counts = widget_named(payload, "Interviews by province")
    assert [row[-1] for row in counts["cube"]["rows"]] == [4]

    means = widget_named(payload, "Mean wage by province")
    # Carried as a total and a count so the browser can re-average; 1000/4.
    row = means["cube"]["rows"][0]
    assert row[1:] == [1000.0, 4]


def test_an_unpinned_export_is_unchanged(client, auth_headers, board):
    """The ordinary export still carries both provinces and its picker."""
    payload = payload_of(export(client, auth_headers, board))
    assert payload["pinned"] == []
    assert [control["variable"] for control in payload["filters"]] == ["province"]
    counts = widget_named(payload, "Interviews by province")
    assert sorted(row[-1] for row in counts["cube"]["rows"]) == [4, 4]


def test_a_view_from_another_dashboard_cannot_narrow_this_one(
    client, auth_headers, board
):
    other = client.post(
        "/api/v1/dashboards", headers=auth_headers, json={"name": "Somebody else's"}
    ).json()
    stray = client.post(
        f"/api/v1/dashboards/{other['id']}/views",
        headers=auth_headers,
        json={"name": "Theirs", "state": {"filters": {"province": "Sanma"}}},
    ).json()["id"]
    response = client.get(
        f"/api/v1/dashboards/{board['id']}/export.html?view={stray}", headers=auth_headers
    )
    assert response.status_code == 404, response.text


def test_an_unknown_view_is_refused_rather_than_ignored(client, auth_headers, board):
    # Silently exporting the whole country when the view id is wrong is how a
    # national file ends up filed as a provincial one.
    response = client.get(
        f"/api/v1/dashboards/{board['id']}/export.html?view=nope", headers=auth_headers
    )
    assert response.status_code == 404, response.text


def test_pinning_narrows_a_widget_whose_own_filter_is_an_any_of(
    client, auth_headers, board
):
    """The case where appending the pinned condition would widen, not narrow.

    A chart saved with "any of these" holds an OR. Adding `province = Shefa`
    beside those conditions makes it a third alternative, so the widget would
    report every row matching the original OR plus every row in Shefa, which
    is more than it started with and includes the provinces the file is
    supposed to exclude. Nesting the saved group under an AND is the only
    arrangement that narrows whatever shape it happens to be.

    Shefa holds one wage of 100; Sanma holds three of 1000. Pinned to Shefa,
    "wage is 100 or 1000" is one row. Appended, it is seven.
    """
    either = client.post(
        "/api/v1/dashboards/charts",
        headers=auth_headers,
        json={
            "name": "Either wage",
            "dataset_id": board["dataset_id"],
            "chart_type": "bar",
            "spec": {
                "query": {
                    "dimensions": [{"variable": "province"}],
                    "measures": [{"agg": "count", "alias": "n"}],
                    "filters": {
                        "op": "or",
                        "conditions": [
                            {"variable": "wage", "operator": "eq", "value": 100},
                            {"variable": "wage", "operator": "eq", "value": 1000},
                        ],
                        "groups": [],
                    },
                }
            },
        },
    ).json()
    client.post(
        f"/api/v1/dashboards/{board['id']}/widgets",
        headers=auth_headers,
        json={"title": "Either wage", "widget_type": "chart", "chart_id": either["id"]},
    )

    view = _view(client, auth_headers, board, "Shefa", {"province": "Shefa"})
    payload = _pinned_payload(client, auth_headers, board, view)

    widget = widget_named(payload, "Either wage")
    assert [row[-1] for row in widget["cube"]["rows"]] == [1]
    assert "Sanma" not in json.dumps(payload)


def test_the_file_is_named_after_the_view(client, auth_headers, board):
    view = _view(client, auth_headers, board, "Shefa", {"province": "Shefa"})
    response = client.get(
        f"/api/v1/dashboards/{board['id']}/export.html?view={view}", headers=auth_headers
    )
    # A folder of fourteen files all called exportable.html is not a set of
    # provincial reports.
    assert "exportable-shefa.html" in response.headers["content-disposition"]


# --- A report for every province, in one run --------------------------------


def test_the_burst_writes_one_report_per_value_and_each_holds_only_its_own(
    client, auth_headers, board, tmp_path, monkeypatch
):
    """The whole feature, end to end, without the worker.

    The job runs on Celery in a deployment; here the service is called
    directly, which is the part worth testing - the task around it only moves
    a status along.
    """
    import zipfile

    from app.api.v1.endpoints.dashboards import _render_widget
    from app.models import Dashboard
    from app.services import reports

    with_session = client.app.dependency_overrides
    assert with_session is not None  # the app is wired; the session comes below

    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        dashboard = db.get(Dashboard, board["id"])
        out = tmp_path / "reports.zip"
        summary = reports.burst(
            db,
            dashboard,
            "province",
            render=lambda widget: _render_widget(db, widget, None),
            destination=out,
        )
    finally:
        db.close()

    assert sorted(summary["written"]) == ["Sanma", "Shefa"]
    assert summary["skipped"] == []
    assert out.exists()

    with zipfile.ZipFile(out) as bundle:
        names = sorted(bundle.namelist())
        assert names == ["exportable-sanma.html", "exportable-shefa.html"]
        for name, mine, theirs in (
            ("exportable-shefa.html", "Shefa", "Sanma"),
            ("exportable-sanma.html", "Sanma", "Shefa"),
        ):
            html = bundle.read(name).decode()
            # Against the data rather than the file text: the template's own
            # source travels in every export, so a province named in a comment
            # there would read as a leak when it is nothing of the kind. Asked
            # the first time this test was written, by a comment that did.
            carried = json.dumps(payload_of(html))
            assert mine in carried
            assert payload_of(html)["pinned"][0]["value"] == mine
            # Each file is forwardable on its own, which it would not be if it
            # carried the province next door.
            assert theirs not in carried, f"{name} carries {theirs}"


def test_the_burst_reports_progress_as_it_goes(client, auth_headers, board, tmp_path):
    """A bar that only moves at the end is not a bar."""
    from app.api.v1.endpoints.dashboards import _render_widget
    from app.db.session import SessionLocal
    from app.models import Dashboard
    from app.services import reports

    seen: list[tuple[int, int]] = []
    db = SessionLocal()
    try:
        reports.burst(
            db,
            db.get(Dashboard, board["id"]),
            "province",
            render=lambda widget: _render_widget(db, widget, None),
            destination=tmp_path / "r.zip",
            on_progress=lambda done, total: seen.append((done, total)),
        )
    finally:
        db.close()
    assert seen == [(1, 2), (2, 2)]


def test_one_failing_value_is_skipped_and_the_rest_still_arrive(
    client, auth_headers, board, tmp_path, monkeypatch
):
    """Thirteen provinces and a note about the fourteenth beats nothing at all.

    And the note has to say which one, or the only way to find out is to open
    all of them.
    """
    from app.api.v1.endpoints.dashboards import _render_widget
    from app.db.session import SessionLocal
    from app.models import Dashboard
    from app.services import reports, static_export

    real = static_export.build_payload

    def sometimes(db, dashboard, render, pinned=None):
        if (pinned or {}).get("province") == "Sanma":
            raise RuntimeError("its dataset went away")
        return real(db, dashboard, render, pinned=pinned)

    monkeypatch.setattr(reports.static_export, "build_payload", sometimes)

    db = SessionLocal()
    try:
        summary = reports.burst(
            db,
            db.get(Dashboard, board["id"]),
            "province",
            render=lambda widget: _render_widget(db, widget, None),
            destination=tmp_path / "partial.zip",
        )
    finally:
        db.close()

    assert summary["written"] == ["Shefa"]
    assert summary["skipped"] == [
        {"value": "Sanma", "error": "its dataset went away"}
    ]
    # And the zip is a real one holding the report that did build.
    import zipfile

    with zipfile.ZipFile(tmp_path / "partial.zip") as bundle:
        assert bundle.namelist() == ["exportable-shefa.html"]


def test_the_service_refuses_too_many_values_even_if_the_route_did_not(
    client, auth_headers, board, tmp_path, monkeypatch
):
    """The endpoint checks first, but it is not the only way in.

    The worker reads a variable out of job params written earlier, and a board
    whose filter has grown since should not start hours of work on the
    strength of a check made before it did.
    """
    from app.api.v1.endpoints.dashboards import _render_widget
    from app.db.session import SessionLocal
    from app.models import Dashboard
    from app.services import reports

    monkeypatch.setattr(reports, "MAX_REPORTS", 1)
    db = SessionLocal()
    try:
        with pytest.raises(reports.TooMany, match="limit is 1"):
            reports.burst(
                db,
                db.get(Dashboard, board["id"]),
                "province",
                render=lambda widget: _render_widget(db, widget, None),
                destination=tmp_path / "never.zip",
            )
    finally:
        db.close()
    # Refused before anything was written, not halfway through.
    assert not (tmp_path / "never.zip").exists()


def test_a_burst_over_a_variable_with_no_filter_is_refused(client, auth_headers, board):
    response = client.post(
        f"/api/v1/dashboards/{board['id']}/reports",
        headers=auth_headers,
        json={"variable": "wage"},
    )
    # The board has no wage control, so there is nothing to enumerate and
    # nothing sensible to produce.
    assert response.status_code == 404, response.text


def test_the_values_a_burst_would_cover_can_be_asked_for_first(
    client, auth_headers, board
):
    response = client.get(
        f"/api/v1/dashboards/{board['id']}/report-values?variable=province",
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert sorted(body["values"]) == ["Sanma", "Shefa"]
    # So the dialog can say "2 reports" and refuse before anybody waits.
    assert body["limit"] >= 2


def test_too_many_values_is_refused_before_the_work_starts(
    client, auth_headers, board, monkeypatch
):
    """A burst over an interviewer id is hours of work and hundreds of files."""
    from app.services import reports

    monkeypatch.setattr(reports, "MAX_REPORTS", 1)
    response = client.post(
        f"/api/v1/dashboards/{board['id']}/reports",
        headers=auth_headers,
        json={"variable": "province"},
    )
    assert response.status_code == 400, response.text
    assert "limit is 1" in response.json()["detail"]


def test_a_finished_run_is_downloaded_and_an_unfinished_one_is_not(
    client, auth_headers, board, db_session
):
    from app.models import Job, JobStatus, JobType

    job = Job(
        job_type=JobType.export,
        status=JobStatus.running,
        params={"dashboard_id": board["id"], "variable": "province"},
    )
    db_session.add(job)
    db_session.commit()

    waiting = client.get(
        f"/api/v1/dashboards/{board['id']}/reports/{job.id}.zip", headers=auth_headers
    )
    assert waiting.status_code == 409, waiting.text

    job.status = JobStatus.success
    job.result = {"path": "/nowhere/gone.zip"}
    db_session.commit()
    missing = client.get(
        f"/api/v1/dashboards/{board['id']}/reports/{job.id}.zip", headers=auth_headers
    )
    # The row outliving its file says so, rather than serving an empty zip.
    assert missing.status_code == 410, missing.text

    db_session.delete(job)
    db_session.commit()


def test_one_board_s_run_cannot_be_downloaded_through_another(
    client, auth_headers, board, db_session, tmp_path
):
    from app.models import Job, JobStatus, JobType

    other = client.post(
        "/api/v1/dashboards", headers=auth_headers, json={"name": "Somebody else's"}
    ).json()
    zipped = tmp_path / "theirs.zip"
    zipped.write_bytes(b"PK\x05\x06" + b"\x00" * 18)
    job = Job(
        job_type=JobType.export,
        status=JobStatus.success,
        params={"dashboard_id": board["id"], "variable": "province"},
        result={"path": str(zipped)},
    )
    db_session.add(job)
    db_session.commit()

    response = client.get(
        f"/api/v1/dashboards/{other['id']}/reports/{job.id}.zip", headers=auth_headers
    )
    assert response.status_code == 404, response.text

    db_session.delete(job)
    db_session.commit()
