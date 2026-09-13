"""R runs against a project, not against one dataset.

A script that prepares survey data reads the household file and writes the
person file. Pinning it to one of the two was always a fiction, and it meant a
two-file job had to be written twice or not at all. So the project is the unit:
every dataset in it is readable, anything the script writes becomes a dataset in
it, and the working directory survives between runs.
"""

from __future__ import annotations

import shutil

import pandas as pd
import pytest

from app.core.config import get_settings
from app.services import rproject
from tests.conftest import sign_in
from tests.test_api_analytics import _stata_bytes, _zip_bytes

# Plain Rscript, not the sandbox launcher. This module is about the workspace
# contract - read_dataset, write_dataset, what survives between runs - and that
# is the same contract inside the sandbox or out of it. The launcher is only
# built into the Docker image, so requiring it here would skip every one of
# these tests on a developer's machine and in any CI leg without the image.
# The confinement itself is tested by test_r_sandbox.py, which needs the real
# launcher and a kernel that can enforce it.
pytestmark = pytest.mark.skipif(
    not shutil.which("Rscript"), reason="R is not installed on this machine"
)


@pytest.fixture(autouse=True)
def r_on(monkeypatch):
    """R is off by default; these tests are about what happens when it is on."""
    settings = get_settings()
    monkeypatch.setattr(settings, "r_scripts_enabled", True)
    monkeypatch.setattr(settings, "r_binary", "Rscript")
    monkeypatch.setattr(settings, "r_sandbox_required", False)
    monkeypatch.setattr(rproject, "_sandbox_check", None)
    yield
    rproject._sandbox_check = None


@pytest.fixture
def project(client, auth_headers, request) -> dict:
    """A project with two datasets in it, so "the project" means something."""
    made = client.post(
        "/api/v1/projects",
        headers=auth_headers,
        json={"name": f"R workspace {request.node.name[:20]}"},
    )
    assert made.status_code == 201, made.text
    project_id = made.json()["id"]

    ids = {}
    for label, frame in {
        "household": pd.DataFrame(
            {
                "interview__key": ["a", "b", "c"],
                "province": ["Malampa", "Sanma", "Malampa"],
                "hh_size": [4, 2, 7],
            }
        ),
        "person": pd.DataFrame(
            {
                "interview__key": ["a", "a", "b", "c"],
                "age": [30, 8, 44, 19],
            }
        ),
    }.items():
        name = f"{label}-{request.node.name[:24]}"
        uploaded = client.post(
            "/api/v1/datasets/upload",
            headers=auth_headers,
            data={"project_id": project_id},
            files={
                "file": (
                    f"{name}.zip",
                    _zip_bytes({f"{name}.dta": _stata_bytes(frame)}),
                    "application/zip",
                )
            },
        )
        assert uploaded.status_code in (200, 201), uploaded.text
        body = uploaded.json()
        ids[label] = body["datasets"][0]["id"] if "datasets" in body else body["id"]
        client.patch(
            f"/api/v1/datasets/{ids[label]}",
            headers=auth_headers,
            json={"name": label.title()},
        )
    return {"id": project_id, "datasets": ids}


def run(client, headers, project_id: str, code: str):
    return client.post(
        f"/api/v1/projects/{project_id}/run", headers=headers, json={"code": code}
    )


def test_the_console_lists_the_project_s_datasets(client, auth_headers, project):
    """`datasets` is what tells you what there is to read."""
    done = run(
        client, auth_headers, project["id"], 'cat(paste(sort(datasets$name), collapse="|"))'
    )
    assert done.status_code == 200, done.text
    assert done.json()["output"].strip() == "Household|Person"


def test_a_script_reads_a_dataset_by_name(client, auth_headers, project):
    done = run(client, auth_headers, project["id"], 'cat(nrow(read_dataset("Person")))')
    assert done.status_code == 200, done.text
    assert done.json()["output"].strip() == "4"


def test_a_script_can_read_two_datasets_and_write_a_third(client, auth_headers, project):
    """The whole reason R moved to the project: a job across two files."""
    done = run(
        client,
        auth_headers,
        project["id"],
        """
        h <- read_dataset("Household")
        p <- read_dataset("Person")
        adults <- aggregate(age ~ interview__key, data = p[p$age >= 18, ], FUN = length)
        names(adults)[2] <- "adults"
        joined <- merge(h, adults, by = "interview__key", all.x = TRUE)
        joined$adults[is.na(joined$adults)] <- 0
        write_dataset(joined, "Household with adults")
        """,
    )
    assert done.status_code == 200, done.text
    written = done.json()["written"]
    assert [item["name"] for item in written] == ["Household with adults"]
    assert written[0]["rows"] == 3

    # It is a dataset of this project, queryable like any other.
    listed = client.get(
        "/api/v1/datasets", headers=auth_headers, params={"project_id": project["id"]}
    ).json()["items"]
    assert "Household with adults" in [d["name"] for d in listed]


def test_writing_the_same_name_twice_replaces_rather_than_duplicates(
    client, auth_headers, project
):
    """A script run twice must not leave two copies, or every chart on it breaks."""
    code = 'write_dataset(read_dataset("Household"), "Copy of household")'
    run(client, auth_headers, project["id"], code)
    second = run(client, auth_headers, project["id"], code)
    assert second.status_code == 200, second.text

    listed = client.get(
        "/api/v1/datasets", headers=auth_headers, params={"project_id": project["id"]}
    ).json()["items"]
    named = [d for d in listed if d["name"] == "Copy of household"]
    assert len(named) == 1


def test_the_workspace_survives_between_runs(client, auth_headers, project):
    """A project is an environment: what a script leaves is there next time."""
    first = run(
        client,
        auth_headers,
        project["id"],
        'saveRDS(list(seen = 41), "state.rds"); cat("saved")',
    )
    assert first.status_code == 200, first.text
    second = run(
        client, auth_headers, project["id"], 'cat(readRDS("state.rds")$seen + 1)'
    )
    assert second.status_code == 200, second.text
    assert second.json()["output"].strip() == "42"


def test_the_workspace_listing_shows_what_was_left(client, auth_headers, project):
    run(client, auth_headers, project["id"], 'writeLines("hello", "notes.txt")')
    listed = client.get(
        f"/api/v1/projects/{project['id']}/workspace", headers=auth_headers
    )
    assert listed.status_code == 200, listed.text
    assert "notes.txt" in [f["path"] for f in listed.json()["files"]]


def test_the_listing_hides_the_platform_s_own_plumbing(client, auth_headers, project):
    """The CSVs the platform writes are not the user's files."""
    run(client, auth_headers, project["id"], 'invisible(read_dataset("Household"))')
    files = client.get(
        f"/api/v1/projects/{project['id']}/workspace", headers=auth_headers
    ).json()["files"]
    assert not [f for f in files if f["path"].startswith("data/")]
    assert not [f for f in files if f["path"] == rproject.SCRIPT]


def test_clearing_the_workspace_leaves_the_datasets_alone(client, auth_headers, project):
    run(client, auth_headers, project["id"], 'writeLines("hello", "notes.txt")')
    cleared = client.delete(
        f"/api/v1/projects/{project['id']}/workspace", headers=auth_headers
    )
    assert cleared.status_code == 200, cleared.text
    files = client.get(
        f"/api/v1/projects/{project['id']}/workspace", headers=auth_headers
    ).json()["files"]
    assert files == []
    still = client.get(
        "/api/v1/datasets", headers=auth_headers, params={"project_id": project["id"]}
    ).json()["items"]
    assert "Household" in [d["name"] for d in still]


def test_a_broken_script_changes_nothing_and_says_why(client, auth_headers, project):
    done = run(client, auth_headers, project["id"], 'stop("not today")')
    assert done.status_code == 422
    assert "not today" in done.json()["detail"]


def test_reading_a_dataset_that_is_not_here_names_the_ones_that_are(
    client, auth_headers, project
):
    done = run(client, auth_headers, project["id"], 'read_dataset("Nowhere")')
    assert done.status_code == 422
    assert "Household" in done.json()["detail"]


def test_a_saved_script_records_how_its_last_run_went(client, auth_headers, project):
    made = client.post(
        f"/api/v1/projects/{project['id']}/scripts",
        headers=auth_headers,
        json={"name": "Count the people", "code": 'cat(nrow(read_dataset("Person")))'},
    )
    assert made.status_code == 201, made.text
    script_id = made.json()["id"]

    done = client.post(
        f"/api/v1/projects/{project['id']}/scripts/{script_id}/run", headers=auth_headers
    )
    assert done.status_code == 200, done.text

    listed = client.get(
        f"/api/v1/projects/{project['id']}/scripts", headers=auth_headers
    ).json()
    saved = next(s for s in listed if s["id"] == script_id)
    assert saved["last_ok"] is True
    assert saved["last_run_at"]
    assert "4" in saved["last_output"]


def test_a_failing_saved_script_records_the_failure(client, auth_headers, project):
    made = client.post(
        f"/api/v1/projects/{project['id']}/scripts",
        headers=auth_headers,
        json={"name": "Broken", "code": 'stop("nope")'},
    ).json()
    failed = client.post(
        f"/api/v1/projects/{project['id']}/scripts/{made['id']}/run", headers=auth_headers
    )
    assert failed.status_code == 422

    saved = next(
        s
        for s in client.get(
            f"/api/v1/projects/{project['id']}/scripts", headers=auth_headers
        ).json()
        if s["id"] == made["id"]
    )
    assert saved["last_ok"] is False
    assert "nope" in saved["last_output"]


def test_scripts_run_again_when_a_new_export_lands(
    client, auth_headers, project, request
):
    """A derived variable is not in the file that arrives, so it is rebuilt.

    Two scripts, because the order matters: they build on each other, and "run
    them all again" only means something if it means "in this order".
    """
    for name, code in [
        ("One", 'writeLines("one", "order.txt")'),
        ("Two", 'writeLines(c(readLines("order.txt"), "two"), "order.txt")'),
    ]:
        made = client.post(
            f"/api/v1/projects/{project['id']}/scripts",
            headers=auth_headers,
            json={"name": name, "code": code, "run_on_import": True},
        )
        assert made.status_code == 201, made.text

    label = f"extra-{request.node.name[:20]}"
    uploaded = client.post(
        "/api/v1/datasets/upload",
        headers=auth_headers,
        data={"project_id": project["id"]},
        files={
            "file": (
                f"{label}.zip",
                _zip_bytes(
                    {f"{label}.dta": _stata_bytes(pd.DataFrame({"n": [1, 2, 3]}))}
                ),
                "application/zip",
            )
        },
    )
    assert uploaded.status_code in (200, 201), uploaded.text
    # The import reports what it re-ran rather than doing it silently.
    assert any("One" in w for w in uploaded.json()["warnings"])

    # And in order: the second script appended to what the first wrote.
    room = rproject.workspace(project["id"])
    assert (room / "order.txt").read_text().split() == ["one", "two"]


def test_the_tools_route_says_what_is_available(client, auth_headers, project):
    tools = client.get(f"/api/v1/projects/{project['id']}/tools", headers=auth_headers)
    assert tools.status_code == 200, tools.text
    body = tools.json()
    assert body["r"]["enabled"] is True
    assert sorted(d["name"] for d in body["datasets"]) == ["Household", "Person"]


def test_a_viewer_cannot_run_r(client, auth_headers, project):
    """An R script runs with the server's permissions; that is a manager's route."""
    email = "r-reader@example.com"
    password = "r-reader-password-12"
    created = client.post(
        "/api/v1/users",
        headers=auth_headers,
        json={"email": email, "role": "viewer", "password": password},
    )
    assert created.status_code in (201, 409), created.text
    reader = sign_in(client, email, password)
    refused = run(client, reader, project["id"], 'cat("hello")')
    assert refused.status_code in (403, 404)


# --- what a plain write.csv() does -----------------------------------------
#
# write_dataset() is the explicit way in and it names the dataset itself. The
# other way is the one somebody coming from RStudio writes without thinking,
# and it used to leave a file in the working directory and nothing else.


def test_a_plain_write_csv_becomes_a_dataset(client, auth_headers, project):
    done = run(
        client,
        auth_headers,
        project["id"],
        """
        h <- read_dataset("Household")
        write.csv(h[h$hh_size > 3, ], "large-households.csv", row.names = FALSE)
        """,
    )
    assert done.status_code == 200, done.text
    written = done.json()["written"]
    assert [item["name"] for item in written] == ["large-households"]
    assert written[0]["rows"] == 2

    # A dataset of this project like any other, not merely a row somewhere.
    listed = client.get(
        f"/api/v1/datasets?project_id={project['id']}", headers=auth_headers
    ).json()
    rows = listed["items"] if isinstance(listed, dict) else listed
    assert "large-households" in [d["name"] for d in rows]


def test_a_data_file_in_a_subdirectory_is_adopted_too(client, auth_headers, project):
    done = run(
        client,
        auth_headers,
        project["id"],
        """
        dir.create("clean", showWarnings = FALSE)
        write.csv(read_dataset("Person"), "clean/people.csv", row.names = FALSE)
        """,
    )
    assert done.status_code == 200, done.text
    assert [item["name"] for item in done.json()["written"]] == ["people"]


def test_writing_the_same_file_twice_replaces_the_dataset(client, auth_headers, project):
    first = run(
        client,
        auth_headers,
        project["id"],
        'write.csv(read_dataset("Household"), "snapshot.csv", row.names = FALSE)',
    )
    assert first.status_code == 200, first.text
    second = run(
        client,
        auth_headers,
        project["id"],
        'write.csv(read_dataset("Person"), "snapshot.csv", row.names = FALSE)',
    )
    assert second.status_code == 200, second.text
    assert second.json()["written"][0]["rows"] == 4

    rows = client.get(
        f"/api/v1/datasets?project_id={project['id']}", headers=auth_headers
    ).json()
    rows = rows["items"] if isinstance(rows, dict) else rows
    assert [d["name"] for d in rows].count("snapshot") == 1


def test_a_file_from_an_earlier_run_is_not_adopted_again(client, auth_headers, project):
    """The workspace survives, so every run would otherwise re-save everything."""
    run(
        client,
        auth_headers,
        project["id"],
        'write.csv(read_dataset("Household"), "once.csv", row.names = FALSE)',
    )
    again = run(client, auth_headers, project["id"], 'cat("nothing to do")')
    assert again.status_code == 200, again.text
    assert again.json()["written"] == []


def test_a_text_file_is_left_alone(client, auth_headers, project):
    """A script writing a log wrote a log, not a dataset."""
    done = run(client, auth_headers, project["id"], 'writeLines("done", "run.log.txt")')
    assert done.status_code == 200, done.text
    assert done.json()["written"] == []


def test_a_csv_that_is_not_a_table_stays_a_file(client, auth_headers, project):
    """Unreadable as data is a file, not a failed run."""
    done = run(client, auth_headers, project["id"], 'writeLines("", "empty.csv")')
    assert done.status_code == 200, done.text
    assert done.json()["written"] == []
    files = client.get(
        f"/api/v1/projects/{project['id']}/workspace", headers=auth_headers
    ).json()["files"]
    assert "empty.csv" in [f["path"] for f in files]


# --- the environment pane ---------------------------------------------------


def test_the_run_reports_what_it_left_in_the_environment(client, auth_headers, project):
    done = run(
        client,
        auth_headers,
        project["id"],
        """
        h <- read_dataset("Household")
        total <- sum(h$hh_size)
        tidy <- function(frame, drop = TRUE) frame
        """,
    )
    assert done.status_code == 200, done.text
    objects = {item["name"]: item for item in done.json()["environment"]}
    assert set(objects) == {"h", "total", "tidy"}

    assert objects["h"]["kind"] == "data"
    assert objects["h"]["shape"] == "3 obs. of 4 variables"
    assert "province" in objects["h"]["preview"]

    assert objects["total"]["kind"] == "value"
    assert objects["total"]["preview"] == "13"

    # The signature, which is what the pane shows for a function.
    assert objects["tidy"]["kind"] == "function"
    assert objects["tidy"]["preview"] == "function (frame, drop = TRUE)"


def test_the_environment_hides_the_workspace_s_own_vocabulary(
    client, auth_headers, project
):
    """`datasets` and the two functions are the platform's, not the script's."""
    done = run(client, auth_headers, project["id"], "x <- 1")
    assert [item["name"] for item in done.json()["environment"]] == ["x"]


def test_the_environment_survives_a_reload(client, auth_headers, project):
    """Read from the workspace, so the pane is not empty after a refresh."""
    run(client, auth_headers, project["id"], "kept <- c('a', 'b', 'c')")
    body = client.get(
        f"/api/v1/projects/{project['id']}/workspace", headers=auth_headers
    ).json()
    objects = {item["name"]: item for item in body["environment"]}
    assert objects["kept"]["shape"] == "length 3"
    assert objects["kept"]["preview"] == "a b c"


def test_a_failed_run_leaves_no_environment(client, auth_headers, project):
    run(client, auth_headers, project["id"], "kept <- 1")
    broken = run(client, auth_headers, project["id"], 'stop("no")')
    assert broken.status_code == 422, broken.text
    body = client.get(
        f"/api/v1/projects/{project['id']}/workspace", headers=auth_headers
    ).json()
    assert body["environment"] == []


def test_the_workspace_listing_shows_the_project_s_datasets(
    client, auth_headers, project
):
    """The datasets are part of the working directory picture, not apart from it."""
    body = client.get(
        f"/api/v1/projects/{project['id']}/workspace", headers=auth_headers
    ).json()
    named = {d["name"]: d for d in body["datasets"]}
    assert set(named) == {"Household", "Person"}
    assert named["Person"]["rows"] == 4
    assert named["Person"]["path"] == f"{rproject.DATA_DIR}/{named['Person']['slug']}.csv"


def test_a_file_that_became_a_dataset_says_so(client, auth_headers, project):
    run(
        client,
        auth_headers,
        project["id"],
        """
        write.csv(read_dataset("Household"), "adults.csv", row.names = FALSE)
        writeLines("note", "adults.txt")
        """,
    )
    files = {
        f["path"]: f
        for f in client.get(
            f"/api/v1/projects/{project['id']}/workspace", headers=auth_headers
        ).json()["files"]
    }
    assert files["adults.csv"]["dataset"] is True
    assert files["adults.txt"]["dataset"] is False
