"""A value label is found by the code it belongs to.

The codes in the data and the keys of the label set have to be written the
same way or no label is ever found. They were not: Stata's reader hands back
integer keys and SPSS's hands back floats, because SPSS stores every number as
a double - so an imported .sav carried its labels and could not use one of
them. A crosstab of a labelled question printed 1.0, 2.0, 3.0, the labels sat
in the dataset unread, and nothing on the screen said they were there.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from app.services.ingest import code_labels, code_text, read_source

ROOFING = {1: "Corrugated iron", 2: "Pandanus", 3: "Roofing tiles"}


def _frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "interview__key": ["a", "b", "c", "d"],
            "roof": [1.0, 2.0, 1.0, 3.0],
            "hh_size": [4.0, 2.0, 7.0, 1.0],
        }
    )


def _sav(tmp_path) -> Path:
    import pyreadstat

    path = tmp_path / "housing.sav"
    pyreadstat.write_sav(
        _frame(),
        str(path),
        variable_value_labels={"roof": ROOFING},
        column_labels=["Interview key", "Roofing materials", "Household size"],
    )
    return path


def _dta(tmp_path) -> Path:
    path = tmp_path / "housing.dta"
    _frame().to_stata(path, write_index=False, version=118, value_labels={"roof": ROOFING})
    return path


# --- the readers ------------------------------------------------------------


def test_an_spss_file_hands_back_codes_as_the_data_is_read(tmp_path):
    """The fault. Its keys were 1.0, 2.0, 3.0, and nothing looks a code up that way."""
    _, _, values = read_source(_sav(tmp_path))
    assert values["roof"] == {"1": "Corrugated iron", "2": "Pandanus", "3": "Roofing tiles"}


def test_a_stata_file_hands_back_the_same_keys(tmp_path):
    _, _, values = read_source(_dta(tmp_path))
    assert values["roof"] == {"1": "Corrugated iron", "2": "Pandanus", "3": "Roofing tiles"}


def test_a_code_that_is_not_a_whole_number_keeps_its_point():
    assert code_labels({1.5: "Half", 2.0: "Two", "a": "Tagged"}) == {
        "1.5": "Half",
        "2": "Two",
        "a": "Tagged",
    }


def test_the_text_of_a_label_is_left_alone():
    assert code_labels({1.0: "1.0 litres"}) == {"1": "1.0 litres"}


# --- end to end -------------------------------------------------------------


@pytest.fixture
def project(client, auth_headers) -> str:
    made = client.post("/api/v1/projects", headers=auth_headers, json={"name": "Labels"})
    project_id = made.json()["id"]
    yield project_id
    client.delete(
        f"/api/v1/projects/{project_id}", headers=auth_headers, params={"contents": "delete"}
    )


def _upload(client, auth_headers, project, path, name) -> str:
    with open(path, "rb") as handle:
        response = client.post(
            "/api/v1/datasets/upload",
            headers=auth_headers,
            files=[("file", (name, handle.read(), "application/octet-stream"))],
            data={"project_id": project},
        )
    assert response.status_code == 201, response.text
    body = response.json()
    # A single data file becomes one dataset; an archive reports a list of them.
    return (body["datasets"][0] if "datasets" in body else body)["id"]


def _frequency(client, auth_headers, dataset_id, variable) -> dict[str, int]:
    answer = client.get(
        f"/api/v1/analytics/datasets/{dataset_id}/frequency/{variable}", headers=auth_headers
    )
    assert answer.status_code == 200, answer.text
    return {row["label"]: row["count"] for row in answer.json()["rows"]}


def test_an_imported_spss_file_tabulates_under_its_labels(
    client, auth_headers, project, tmp_path
):
    """What the bug report is: a crosstab of a labelled question, in numbers."""
    dataset_id = _upload(client, auth_headers, project, _sav(tmp_path), "housing.sav")
    assert _frequency(client, auth_headers, dataset_id, "roof") == {
        "Corrugated iron": 2,
        "Pandanus": 1,
        "Roofing tiles": 1,
    }


def test_an_imported_spss_file_keeps_its_variable_labels(
    client, auth_headers, project, tmp_path
):
    dataset_id = _upload(client, auth_headers, project, _sav(tmp_path), "housing.sav")
    detail = client.get(f"/api/v1/datasets/{dataset_id}", headers=auth_headers).json()
    labels = {v["name"]: v["label"] for v in detail["variables"]}
    assert labels["roof"] == "Roofing materials"


def test_a_crosstab_of_two_spss_questions_reads_in_labels(
    client, auth_headers, project, tmp_path
):
    dataset_id = _upload(client, auth_headers, project, _sav(tmp_path), "housing.sav")
    answer = client.post(
        "/api/v1/analytics/query",
        headers=auth_headers,
        json={
            "dataset_id": dataset_id,
            "spec": {
                "dimensions": [{"variable": "roof"}],
                "measures": [{"agg": "count", "alias": "n"}],
            },
        },
    )
    assert answer.status_code == 200, answer.text
    axis = [row[0] for row in answer.json()["rows"]]
    assert sorted(axis) == ["Corrugated iron", "Pandanus", "Roofing tiles"]


def test_a_code_typed_by_hand_as_a_decimal_still_reaches_the_data(
    client, auth_headers, project, tmp_path
):
    """The editor shows an unlabelled column as 1.0, so that is what gets typed."""
    path = tmp_path / "plain.csv"
    path.write_text("interview__key,roof\na,1\nb,2\nc,1\n")
    dataset_id = _upload(client, auth_headers, project, path, "plain.csv")
    named = client.patch(
        f"/api/v1/datasets/{dataset_id}/variables/roof",
        headers=auth_headers,
        json={"value_labels": {"1.0": "Corrugated iron", "2.0": "Pandanus"}},
    )
    assert named.status_code == 200, named.text
    assert named.json()["value_labels"] == {"1": "Corrugated iron", "2": "Pandanus"}
    assert _frequency(client, auth_headers, dataset_id, "roof") == {
        "Corrugated iron": 2,
        "Pandanus": 1,
    }


# --- what is already stored -------------------------------------------------


def test_labels_already_stored_against_decimal_codes_are_repaired(tmp_path):
    """A dataset imported before the fix, upgraded in place rather than again."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.db.base import Base
    from app.db.migrations import upgrade
    from app.models import Dataset, DatasetSource, DatasetStatus, Variable, VariableType

    bind = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    Base.metadata.create_all(bind)
    with Session(bind) as db:
        db.add(
            Dataset(
                id="d1",
                name="Housing",
                slug="housing",
                status=DatasetStatus.ready,
                source=DatasetSource.upload,
                meta={
                    "variable_labels": {
                        "roof": {
                            "label": "Roofing materials",
                            "value_labels": {"1.0": "Corrugated iron"},
                        }
                    }
                },
            )
        )
        db.add(
            Variable(
                id="v1",
                dataset_id="d1",
                name="roof",
                label="Roofing materials",
                var_type=VariableType.categorical,
                storage_type="float64",
                position=1,
                value_labels={"1.0": "Corrugated iron", "2.5": "Half a roof"},
            )
        )
        db.commit()

    upgrade(bind)

    with Session(bind) as db:
        stored = db.get(Variable, "v1").value_labels
        meta = db.get(Dataset, "d1").meta
    bind.dispose()
    # Whole numbers rewritten, anything else left exactly as it was.
    assert stored == {"1": "Corrugated iron", "2.5": "Half a roof"}
    assert meta["variable_labels"]["roof"]["value_labels"] == {"1": "Corrugated iron"}


def test_the_repair_keeps_the_spelling_the_data_is_read_by(tmp_path):
    """A set holding both "1" and "1.0" is one code, and "1" is the one that works."""
    import importlib.util
    from pathlib import Path

    path = (
        Path(__file__).resolve().parents[1]
        / "migrations/versions/20261010_12_code_keyed_labels.py"
    )
    spec = importlib.util.spec_from_file_location("code_keyed_labels", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module._normalised({"1.0": "Decimal", "1": "Whole"}) == {"1": "Whole"}
    assert module._normalised({"a": "Tagged", "2.0": "Two"}) == {"a": "Tagged", "2": "Two"}


def test_code_text_is_what_both_of_them_agree_on():
    assert code_text(1.0) == "1"
    assert code_text(1) == "1"
    assert code_text(1.5) == "1.5"
    assert code_text("a") == "a"


def test_a_text_column_keeps_the_spelling_its_values_have(tmp_path):
    """Where "1.0" is the value rather than a way of writing 1."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.db.base import Base
    from app.db.migrations import upgrade
    from app.models import Dataset, DatasetSource, DatasetStatus, Variable, VariableType

    bind = create_engine(f"sqlite:///{tmp_path / 'text.db'}")
    Base.metadata.create_all(bind)
    with Session(bind) as db:
        db.add(
            Dataset(
                id="d2",
                name="Readings",
                slug="readings",
                status=DatasetStatus.ready,
                source=DatasetSource.upload,
            )
        )
        db.add(
            Variable(
                id="v2",
                dataset_id="d2",
                name="dose",
                var_type=VariableType.text,
                storage_type="object",
                position=1,
                value_labels={"1.0": "One millilitre"},
            )
        )
        db.commit()
    upgrade(bind)
    with Session(bind) as db:
        assert db.get(Variable, "v2").value_labels == {"1.0": "One millilitre"}
    bind.dispose()


def test_a_code_typed_against_a_text_column_is_left_as_typed(
    client, auth_headers, project, tmp_path
):
    """There "1.0" is the value, not a way of writing 1."""
    path = tmp_path / "text.csv"
    path.write_text("interview__key,dose\na,1.0\nb,2.0\nc,unknown\n")
    dataset_id = _upload(client, auth_headers, project, path, "doses.csv")
    detail = client.get(f"/api/v1/datasets/{dataset_id}", headers=auth_headers).json()
    kinds = {v["name"]: str(v["storage_type"]).lower() for v in detail["variables"]}
    assert "object" in kinds["dose"], kinds
    named = client.patch(
        f"/api/v1/datasets/{dataset_id}/variables/dose",
        headers=auth_headers,
        json={"value_labels": {"1.0": "One millilitre"}},
    )
    assert named.status_code == 200, named.text
    assert named.json()["value_labels"] == {"1.0": "One millilitre"}
    assert _frequency(client, auth_headers, dataset_id, "dose")["One millilitre"] == 1


def test_a_label_set_defined_with_a_decimal_code_still_finds_its_values(
    client, auth_headers, project, tmp_path
):
    """`label define yn 1.0 "Yes"` is a label for the value 1."""
    path = tmp_path / "plain.csv"
    path.write_text("interview__key,owns\na,1\nb,0\nc,1\n")
    dataset_id = _upload(client, auth_headers, project, path, "owning.csv")
    ran = client.post(
        f"/api/v1/datasets/{dataset_id}/command",
        headers=auth_headers,
        json={"command": 'label define yn 1.0 "Yes" 0.0 "No"\nlabel values owns yn'},
    )
    assert ran.status_code == 200, ran.text
    assert _frequency(client, auth_headers, dataset_id, "owns") == {"Yes": 2, "No": 1}


def test_a_variable_row_is_written_with_codes_as_the_data_reads_them():
    """The one place every variable row is written, whatever produced it."""
    from app.db.session import SessionLocal
    from app.models import Dataset, DatasetSource, DatasetStatus
    from app.services.datasets import _apply_ingest
    from app.services.ingest import IngestResult, VariableMeta

    with SessionLocal() as db:
        dataset = Dataset(
            name="Written by hand",
            slug=f"written-{id(db)}",
            status=DatasetStatus.ready,
            source=DatasetSource.upload,
        )
        db.add(dataset)
        db.flush()
        _apply_ingest(
            db,
            dataset,
            IngestResult(
                parquet_path=Path("/nonexistent/data.parquet"),
                row_count=0,
                column_count=1,
                file_size=0,
                variables=[
                    VariableMeta(
                        name="roof",
                        label="Roofing materials",
                        var_type="categorical",
                        storage_type="float64",
                        position=0,
                        n_missing=0,
                        n_unique=1,
                        # As a producer that has not normalised them hands
                        # them over: JSON would store this key as "1.0".
                        value_labels={1.0: "Corrugated iron"},
                    )
                ],
            ),
        )
        db.flush()
        assert [v.value_labels for v in dataset.variables] == [{"1": "Corrugated iron"}]
        db.rollback()
