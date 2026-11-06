"""A board's widgets are rendered side by side, and answer as they always did.

Each widget is a query. The first opening of a board after an import - when
every cached answer has just gone stale with its dataset's version - used to
cost the sum of all of them, one after another, so the board was slowest at
the moment it had something new to show.
"""

from __future__ import annotations

import threading
import time

import pytest

from app.api.v1.endpoints import dashboards


@pytest.fixture
def board(client, auth_headers, dataset_id) -> str:
    """Four charts over the session's dataset, each a query of its own."""
    made = client.post(
        "/api/v1/dashboards", headers=auth_headers, json={"name": "Side by side"}
    ).json()
    for name, dimension, agg in [
        ("By region", "region", "count"),
        ("By sex", "sex", "count"),
        ("Age by region", "region", "mean"),
        ("Age by sex", "sex", "mean"),
    ]:
        measure = {"agg": agg, "alias": "v"} | ({"variable": "age"} if agg == "mean" else {})
        chart = client.post(
            "/api/v1/dashboards/charts",
            headers=auth_headers,
            json={
                "name": name,
                "dataset_id": dataset_id,
                "chart_type": "bar",
                "spec": {"query": {"dimensions": [{"variable": dimension}], "measures": [measure]}},
            },
        )
        assert chart.status_code == 201, chart.text
        widget = client.post(
            f"/api/v1/dashboards/{made['id']}/widgets",
            headers=auth_headers,
            json={"title": name, "widget_type": "chart", "chart_id": chart.json()["id"]},
        )
        assert widget.status_code == 201, widget.text
    return made["id"]


def _render(client, auth_headers, board: str) -> dict:
    answered = client.post(f"/api/v1/dashboards/{board}/data", headers=auth_headers, json={})
    assert answered.status_code == 200, answered.text
    return answered.json()


def test_the_answer_is_the_same_side_by_side_as_one_at_a_time(
    client, auth_headers, board, monkeypatch
):
    monkeypatch.setattr(dashboards, "RENDER_WORKERS", 1)
    alone = _render(client, auth_headers, board)
    monkeypatch.setattr(dashboards, "RENDER_WORKERS", 4)
    together = _render(client, auth_headers, board)

    assert list(together["widgets"]) == list(alone["widgets"]), "in the board's own order"
    for key, payload in alone["widgets"].items():
        assert "error" not in payload, payload
        mine = together["widgets"][key]["result"]
        assert mine["rows"] == payload["result"]["rows"]
        assert mine["columns"] == payload["result"]["columns"]


def test_the_widgets_are_rendered_at_the_same_time(client, auth_headers, board, monkeypatch):
    """Four renders of a quarter second each take about a quarter second."""
    threads: set[int] = set()

    def slow(db, widget, filters, drill=None):
        threads.add(threading.get_ident())
        time.sleep(0.25)
        return {"type": "probe", "title": widget.title}

    monkeypatch.setattr(dashboards, "_render_widget", slow)
    started = time.monotonic()
    body = _render(client, auth_headers, board)
    took = time.monotonic() - started

    assert sorted(w["title"] for w in body["widgets"].values()) == [
        "Age by region",
        "Age by sex",
        "By region",
        "By sex",
    ]
    assert len(threads) > 1
    assert took < 0.75, f"took {took:.2f}s - one after another would be a second"


def test_one_widget_failing_does_not_take_the_others_with_it(
    client, auth_headers, board, monkeypatch
):
    from app.services.query_engine import QueryError

    real = dashboards._render_widget

    def flaky(db, widget, filters, drill=None):
        if widget.title == "By sex":
            raise QueryError("no such variable")
        return real(db, widget, filters, drill)

    monkeypatch.setattr(dashboards, "_render_widget", flaky)
    body = _render(client, auth_headers, board)
    errors = [w for w in body["widgets"].values() if "error" in w]
    assert len(errors) == 1 and "no such variable" in errors[0]["error"]
    assert sum(1 for w in body["widgets"].values() if w.get("type") == "chart") == 3
