"""Does a dataset survive the trip out to R and back?

PROTOTYPE. This is the question the R runner exists to answer, and the one that
would sink it quietly: Parquet has no standard place for variable and value
labels, and this platform leans on them everywhere - axis titles, legends,
cross-tab headers, filter dropdowns. A round trip that drops them would look
like it worked and strip the question wording off every chart built on the
result.

The harness is run directly rather than in its container, because neither this
sandbox nor CI has a Docker daemon. That tests the translation, which is the
part that can be wrong; it does not test the isolation, which is declared in
docker-compose.yml and has to be checked on a real host. The README says so.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pandas as pd
import pytest

from app.services import sandbox

HARNESS = Path(__file__).resolve().parents[2] / "runner/r/harness.R"


def r_is_ready() -> tuple[bool, str]:
    """R, with the four packages the harness imports."""
    if shutil.which("Rscript") is None:
        return False, "Rscript is not installed"
    probe = subprocess.run(
        ["Rscript", "-e", 'library(arrow); library(labelled); library(jsonlite); cat("ok")'],
        capture_output=True,
        text=True,
    )
    if probe.returncode != 0 or "ok" not in probe.stdout:
        return False, f"R is missing a package the harness needs: {probe.stderr.strip()[:200]}"
    return True, ""


READY, WHY = r_is_ready()
needs_r = pytest.mark.skipif(not READY, reason=WHY or "R is not available")


@pytest.fixture
def census(tmp_path: Path) -> tuple[Path, dict, dict]:
    """A small file shaped like one roster level of a census export."""
    frame = pd.DataFrame(
        {
            "interview__key": [f"k{i:03d}" for i in range(6)],
            "age": [4, 17, 18, 33, 70, 12],
            "sex": [1, 2, 2, 1, 2, 1],
            "province": ["Central", "Western", "Central", "Northern", "Central", "Western"],
        }
    )
    path = tmp_path / "source.parquet"
    frame.to_parquet(path, index=False)
    variable_labels = {
        "age": "Age of respondent in completed years",
        "sex": "Sex of respondent",
        "province": "Division",
    }
    value_labels = {"sex": {"1": "Male", "2": "Female"}}
    return path, variable_labels, value_labels


def run(job: Path) -> subprocess.CompletedProcess:
    """Stand in for the container: the same harness, the same job directory."""
    return subprocess.run(
        ["Rscript", str(HARNESS), str(job)], capture_output=True, text=True, timeout=180
    )


@needs_r
def test_a_dataset_survives_the_trip_with_its_labels(tmp_path, census):
    """The whole question. Data out, data back, nothing silently lost."""
    source, variable_labels, value_labels = census
    job = sandbox.submit(
        tmp_path / "work",
        script="data$adult <- as.integer(data$age >= 18)\n"
        'labelled::var_label(data$adult) <- "Aged 18 or over"\n',
        data_path=source,
        variable_labels=variable_labels,
        value_labels=value_labels,
    )
    run(job)
    result = sandbox.collect(job, wait=5)

    assert result.ok, f"{result.error}\n{result.log}"
    assert result.rows == 6
    assert result.columns == 5  # the four it was given, plus adult

    back = pd.read_parquet(result.data_path)
    assert list(back["adult"]) == [0, 0, 1, 1, 1, 0]

    # The labels it was given came back.
    assert result.variable_labels["age"] == "Age of respondent in completed years"
    assert result.variable_labels["province"] == "Division"
    # And the one the script wrote.
    assert result.variable_labels["adult"] == "Aged 18 or over"
    # Value labels too, which is the harder half: the codes are numeric in the
    # column and text in JSON, so a careless round trip drops them.
    assert result.value_labels["sex"] == {"1": "Male", "2": "Female"}


@needs_r
def test_a_dropped_variable_does_not_leave_its_label_behind(tmp_path, census):
    """Labels are read off what the script produced, not carried forward.

    Carrying the input's labels through would reattach 'Sex of respondent' to
    whatever happened to be called sex next time, which is how a chart ends up
    captioned with the wrong question.
    """
    source, variable_labels, value_labels = census
    job = sandbox.submit(
        tmp_path / "work",
        script="data$sex <- NULL\n",
        data_path=source,
        variable_labels=variable_labels,
        value_labels=value_labels,
    )
    run(job)
    result = sandbox.collect(job, wait=5)

    assert result.ok, f"{result.error}\n{result.log}"
    assert "sex" not in pd.read_parquet(result.data_path).columns
    assert "sex" not in result.variable_labels
    assert "sex" not in result.value_labels


@needs_r
def test_a_rename_carries_the_label_to_the_new_name(tmp_path, census):
    source, variable_labels, value_labels = census
    job = sandbox.submit(
        tmp_path / "work",
        script='names(data)[names(data) == "province"] <- "division"\n',
        data_path=source,
        variable_labels=variable_labels,
        value_labels=value_labels,
    )
    run(job)
    result = sandbox.collect(job, wait=5)

    assert result.ok, f"{result.error}\n{result.log}"
    assert result.variable_labels.get("division") == "Division"
    assert "province" not in result.variable_labels


@needs_r
def test_dplyr_is_there_because_that_is_why_somebody_wants_r(tmp_path, census):
    """A collapse written the way an analyst would actually write it."""
    source, variable_labels, value_labels = census
    job = sandbox.submit(
        tmp_path / "work",
        script="suppressPackageStartupMessages(library(dplyr))\n"
        "data <- data |> group_by(province) |> "
        "summarise(people = n(), mean_age = mean(age)) |> as.data.frame()\n",
        data_path=source,
        variable_labels=variable_labels,
        value_labels=value_labels,
    )
    run(job)
    result = sandbox.collect(job, wait=5)

    assert result.ok, f"{result.error}\n{result.log}"
    back = pd.read_parquet(result.data_path).sort_values("province")
    assert list(back["province"]) == ["Central", "Northern", "Western"]
    assert list(back["people"]) == [3, 1, 2]


@needs_r
def test_a_script_that_fails_says_why_rather_than_hanging(tmp_path, census):
    """The log and the message both have to come back, or a failing script is
    a spinner - which is the whole lesson of this evening."""
    source, variable_labels, value_labels = census
    job = sandbox.submit(
        tmp_path / "work",
        script='stop("this province does not exist")\n',
        data_path=source,
        variable_labels=variable_labels,
        value_labels=value_labels,
    )
    run(job)
    result = sandbox.collect(job, wait=5)

    assert not result.ok
    assert "this province does not exist" in result.error
    assert result.data_path is None


@needs_r
def test_a_script_that_leaves_something_that_is_not_a_table_is_refused(tmp_path, census):
    source, variable_labels, value_labels = census
    job = sandbox.submit(
        tmp_path / "work",
        script="data <- 42\n",
        data_path=source,
        variable_labels=variable_labels,
        value_labels=value_labels,
    )
    run(job)
    result = sandbox.collect(job, wait=5)

    assert not result.ok
    assert "not a table" in result.error


def test_the_job_is_only_marked_ready_once_it_is_complete(tmp_path, census):
    """Runs without R: the handshake is the platform's half of the protocol.

    The runner looks for READY and nothing else, so anything written after it
    could be read half-made.
    """
    source, variable_labels, value_labels = census
    job = sandbox.submit(
        tmp_path / "work",
        script="# nothing\n",
        data_path=source,
        variable_labels=variable_labels,
        value_labels=value_labels,
    )
    assert (job / "READY").exists()
    for needed in ("script.R", "in/data.parquet", "in/labels.json"):
        path = job / needed
        assert path.exists(), f"{needed} is missing but the job says READY"
        assert path.stat().st_mtime <= (job / "READY").stat().st_mtime + 1

    sent = json.loads((job / "in" / "labels.json").read_text())
    assert sent["variable_labels"]["age"].startswith("Age of")
    assert sent["value_labels"]["sex"]["1"] == "Male"


def test_waiting_on_a_runner_that_never_answers_says_so(tmp_path, census):
    """Without this the platform waits for ever on a runner that is not up,
    which is exactly the failure that wasted an evening on the import path."""
    source, _, _ = census
    job = sandbox.submit(tmp_path / "work", script="# nothing\n", data_path=source)
    with pytest.raises(sandbox.SandboxError, match="did not answer"):
        sandbox.collect(job, wait=0.2, poll=0.05)
