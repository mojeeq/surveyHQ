"""Running R over a dataset.

The Stata box covers generating a variable and labelling it. Everything a
survey statistician actually reaches for past that - recoding a battery,
deriving a poverty line, reshaping a roster - is a few lines of R, so the
dataset is handed to R as a data frame and whatever the script leaves in it
becomes the dataset.

Two things have to hold for that to be usable rather than a toy: the change
has to survive the next export replacing the file, in the right order relative
to the Stata commands beside it; and a script that fails has to leave the data
alone rather than half-written.
"""

from __future__ import annotations

import shutil

import pandas as pd
import pytest

from app.core.config import get_settings
from tests.test_api_analytics import _stata_bytes, _zip_bytes

pytestmark = pytest.mark.skipif(
    shutil.which("Rscript") is None, reason="R is not installed on this machine"
)


@pytest.fixture(autouse=True)
def r_enabled(monkeypatch):
    """Switched on for these tests only.

    Off by default everywhere else, which is the point: an R script runs with
    the server's own permissions, so it waits for somebody to say yes.
    """
    settings = get_settings()
    monkeypatch.setattr(settings, "r_scripts_enabled", True, raising=False)
    yield


@pytest.fixture
def workbench(client, auth_headers, request) -> str:
    """A dataset of this test's own, since these scripts change the data."""
    name = request.node.name[:40]
    frame = pd.DataFrame(
        {
            "interview__key": [f"k{i}" for i in range(6)],
            "age": [17.0, 25.0, 40.0, 63.0, 12.0, None],
            "sex": [1.0, 2.0, 1.0, 2.0, 1.0, 2.0],
            "region": ["North", "North", "South", "South", "South", "North"],
            "income": [100.0, 200.0, 300.0, None, 500.0, 600.0],
        }
    )
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
    return uploaded["datasets"][0]["id"]


def run_r(client, auth_headers, dataset_id: str, script: str):
    return client.post(
        f"/api/v1/datasets/{dataset_id}/rscript",
        headers=auth_headers,
        json={"script": script},
    )


def values(client, auth_headers, dataset_id: str, variable: str) -> list:
    preview = client.get(
        f"/api/v1/datasets/{dataset_id}/preview?limit=50", headers=auth_headers
    ).json()
    index = preview["columns"].index(variable)
    return [row[index] for row in preview["rows"]]


def test_a_script_adds_a_column_and_the_dataset_keeps_it(client, auth_headers, workbench):
    """The whole point: base R, no packages, and the data frame is the dataset."""
    response = run_r(
        client, auth_headers, workbench, "data$adult <- ifelse(data$age >= 18, 1, 0)"
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["variables_added"] == ["adult"]
    assert body["rows"] == 6
    assert values(client, auth_headers, workbench, "adult") == [0, 1, 1, 1, 0, None]


def test_the_script_can_drop_rows_and_columns(client, auth_headers, workbench):
    response = run_r(
        client,
        auth_headers,
        workbench,
        "data <- data[!is.na(data$age) & data$age >= 18, ]\ndata$income <- NULL",
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["rows"] == 3
    assert body["variables_removed"] == ["income"]


def test_what_the_script_prints_comes_back(client, auth_headers, workbench):
    """A script is debugged by printing, so the printing has to reach the person."""
    response = run_r(
        client, auth_headers, workbench, 'cat("rows seen:", nrow(data), "\\n")'
    )
    assert response.status_code == 200, response.text
    assert "rows seen: 6" in response.json()["output"]


def test_a_broken_script_changes_nothing(client, auth_headers, workbench):
    """It fails before anything is written, so the dataset is as it was."""
    response = run_r(client, auth_headers, workbench, "data$oops <- no_such_function(1)")
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "no_such_function" in detail

    dataset = client.get(f"/api/v1/datasets/{workbench}", headers=auth_headers).json()
    assert dataset["row_count"] == 6
    assert "oops" not in {variable["name"] for variable in dataset["variables"]}


def test_a_script_that_throws_away_the_frame_is_refused(client, auth_headers, workbench):
    response = run_r(client, auth_headers, workbench, "data <- 42")
    assert response.status_code == 422
    assert "data frame" in response.json()["detail"]


def test_labels_survive_a_script_that_keeps_the_column(client, auth_headers, workbench):
    """A label is not in the data frame, so it has to be put back afterwards."""
    client.patch(
        f"/api/v1/datasets/{workbench}/variables/region",
        headers=auth_headers,
        json={"label": "Region of residence"},
    )
    assert run_r(client, auth_headers, workbench, "data$one <- 1").status_code == 200
    dataset = client.get(f"/api/v1/datasets/{workbench}", headers=auth_headers).json()
    labels = {v["name"]: v["label"] for v in dataset["variables"]}
    assert labels["region"] == "Region of residence"


def test_the_script_is_recorded_beside_the_stata_commands_in_order(
    client, auth_headers, workbench
):
    """Order is the point: an R script reading a generated column runs after it."""
    client.post(
        f"/api/v1/datasets/{workbench}/command",
        headers=auth_headers,
        json={"command": "gen decade = int(age / 10)"},
    )
    assert run_r(
        client, auth_headers, workbench, "data$decade_x2 <- data$decade * 2"
    ).status_code == 200

    history = client.get(
        f"/api/v1/datasets/{workbench}/commands", headers=auth_headers
    ).json()
    assert [entry["kind"] for entry in history] == ["stata", "r"]
    assert history[1]["text"] == "data$decade_x2 <- data$decade * 2"


def test_a_script_survives_the_next_export_replacing_the_file(
    client, auth_headers
):
    """The reason it is recorded at all: a recode is not in the next export."""
    project = client.post(
        "/api/v1/projects", headers=auth_headers, json={"name": "Replayed R"}
    ).json()

    def archive(rows: int):
        return _zip_bytes(
            {
                "replayed_r.dta": _stata_bytes(
                    pd.DataFrame(
                        {
                            "interview__key": [f"k{i}" for i in range(rows)],
                            "age": [20.0 + i for i in range(rows)],
                        }
                    )
                )
            }
        )

    first = client.post(
        "/api/v1/datasets/upload",
        headers=auth_headers,
        files={"file": ("first.zip", archive(3), "application/zip")},
        data={"project_id": project["id"]},
    ).json()
    dataset_id = first["datasets"][0]["id"]

    client.post(
        f"/api/v1/datasets/{dataset_id}/command",
        headers=auth_headers,
        json={"command": "gen decade = int(age / 10)"},
    )
    assert run_r(
        client, auth_headers, dataset_id, "data$age_next <- data$age + 1"
    ).status_code == 200

    later = client.post(
        "/api/v1/datasets/upload",
        headers=auth_headers,
        files={"file": ("later.zip", archive(5), "application/zip")},
        data={"project_id": project["id"], "mode": "replace"},
    )
    assert later.status_code in (200, 201), later.text

    dataset = client.get(f"/api/v1/datasets/{dataset_id}", headers=auth_headers).json()
    assert dataset["row_count"] == 5
    names = {variable["name"] for variable in dataset["variables"]}
    # Both languages replayed, and the one that needed the other's column worked.
    assert "decade" in names
    assert "age_next" in names
    assert values(client, auth_headers, dataset_id, "age_next") == [21, 22, 23, 24, 25]


def test_it_is_refused_when_the_setting_is_off(client, auth_headers, workbench, monkeypatch):
    """Off is the default, and off has to mean the route says so rather than runs."""
    monkeypatch.setattr(get_settings(), "r_scripts_enabled", False, raising=False)
    response = run_r(client, auth_headers, workbench, "data$one <- 1")
    assert response.status_code == 422
    assert "R_SCRIPTS_ENABLED" in response.json()["detail"]


def test_a_runaway_script_is_stopped(client, auth_headers, workbench, monkeypatch):
    """A script that never finishes must not hold a worker for ever."""
    monkeypatch.setattr(get_settings(), "r_timeout_seconds", 5, raising=False)
    response = run_r(client, auth_headers, workbench, "while (TRUE) {}")
    assert response.status_code == 422
    assert "still running" in response.json()["detail"]

    dataset = client.get(f"/api/v1/datasets/{workbench}", headers=auth_headers).json()
    assert dataset["row_count"] == 6


def test_the_tools_endpoint_says_whether_r_can_be_run(client, auth_headers):
    """Asked before the box is drawn, so a server without R offers no R tab."""
    body = client.get("/api/v1/datasets/tools", headers=auth_headers).json()
    assert body["r"]["enabled"] is True
    assert body["r"]["reason"] == ""
