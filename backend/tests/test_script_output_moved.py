"""A script keeps the output it built, after somebody moves it.

A script reads from its own project and writes into it. So the only way one
project's script feeds another's is to move the output across afterwards:
clean the person file in one project, move the result to the project that
reports on it, and let that project's script read it. That is the arrangement
the Scripts page shows an order for.

The move quietly broke it. `save as clean_people` looked for the name among
its own project's datasets, found nothing where there had been something, and
made a *second* clean_people back where the script lives. Measured on a real
chain before this was fixed:

    Saved 3 row(s) as a new dataset, clean_people
      690b05c6  project: Cleaning the person file   <- new, from the re-run
      780fc6c3  project: Reporting on adults        <- what the reader still reads

Every line reported success. The reader went on reading the copy that moved,
which nothing updated again - so the table it published stopped changing and
said nothing about it. That is the silent staleness the whole re-run chain
exists to prevent, reached by following it.

What a script may write over is unchanged: only what its last run built,
which is what `owns` holds. A dataset it did not build is still refused,
wherever that dataset lives.
"""

from __future__ import annotations

import pandas as pd
import pytest
from sqlalchemy import select

from app.models import Dataset
from app.services import stata
from tests.test_api_analytics import _stata_bytes, _zip_bytes

PEOPLE = pd.DataFrame({"pid": [1.0, 2.0, 3.0], "age": [20.0, 40.0, 9.0]})


@pytest.fixture
def chain(client, auth_headers, request, db_session) -> dict:
    """Two projects: one holding a raw file, one to move the output into."""
    name = request.node.name[:28]
    source = client.post(
        "/api/v1/projects", headers=auth_headers, json={"name": f"Source {name}"}
    ).json()
    reader = client.post(
        "/api/v1/projects", headers=auth_headers, json={"name": f"Reader {name}"}
    ).json()
    uploaded = client.post(
        "/api/v1/datasets/upload",
        headers=auth_headers,
        files={
            "file": (
                "chain.zip",
                _zip_bytes({"chain_raw.dta": _stata_bytes(PEOPLE)}),
                "application/zip",
            )
        },
        data={"project_id": source["id"]},
    )
    assert uploaded.status_code == 201, uploaded.text
    return {"source": source["id"], "reader": reader["id"], "client": client,
            "headers": auth_headers}


def build(db_session, chain: dict, text: str):
    """Run the source project's script the way the endpoint does, carrying
    what the last run built so a re-run may rebuild it."""
    return stata.run_project_script(
        db_session,
        chain["source"],
        text,
        owns=set(chain.get("owns") or ()),
    )


def move(chain: dict, dataset_id: str) -> None:
    moved = chain["client"].put(
        f"/api/v1/projects/assign/dataset/{dataset_id}",
        headers=chain["headers"],
        json={"project_id": chain["reader"]},
    )
    assert moved.status_code == 200, moved.text


def named(db_session, chain: dict, name: str) -> list[Dataset]:
    """Scoped to this chain's two projects. Every test here builds a dataset
    of the same name, so a search by name alone picks up the others."""
    return list(
        db_session.execute(
            select(Dataset).where(
                Dataset.name == name,
                Dataset.project_id.in_([chain["source"], chain["reader"]]),
            )
        )
        .scalars()
        .all()
    )


SCRIPT = 'use chain_raw\ngen adult = 1 if age >= 18\nsave as "linked_people"'


# --- the arrangement the page shows an order for -----------------------------


def test_a_moved_output_is_rebuilt_rather_than_duplicated(db_session, chain):
    first = build(db_session, chain, SCRIPT)
    # Committed rather than flushed: the move goes through the API, which has
    # its own session and cannot see a row this one is still holding.
    db_session.commit()
    built = first.saved[-1].dataset_id
    move(chain, built)
    db_session.expire_all()

    chain["owns"] = {built}
    again = build(db_session, chain, SCRIPT + "\n")
    db_session.flush()

    # One dataset, the same one, still where it was moved to.
    rows = named(db_session, chain, "linked_people")
    assert len(rows) == 1, [one.project_id for one in rows]
    assert rows[0].id == built
    assert rows[0].project_id == chain["reader"]
    assert again.saved[-1].dataset_id == built
    assert again.saved[-1].created is False


def test_the_reader_sees_what_the_rebuild_wrote(db_session, chain):
    """The whole point: a second run reaches the copy the reader reads."""
    first = build(db_session, chain, SCRIPT)
    # Committed rather than flushed: the move goes through the API, which has
    # its own session and cannot see a row this one is still holding.
    db_session.commit()
    built = first.saved[-1].dataset_id
    move(chain, built)
    db_session.expire_all()

    chain["owns"] = {built}
    build(db_session, chain, SCRIPT.replace("save as", 'gen round = 2\nsave as'))
    db_session.flush()
    db_session.expire_all()

    rebuilt = db_session.get(Dataset, built)
    assert "round" in {one.name for one in rebuilt.variables}


def test_the_log_says_where_the_write_landed(db_session, chain):
    """A script writing into another project is right here, and is not what
    the line appears to say. The log mentions it rather than leaving it to be
    found out later."""
    first = build(db_session, chain, SCRIPT)
    # Committed rather than flushed: the move goes through the API, which has
    # its own session and cannot see a row this one is still holding.
    db_session.commit()
    built = first.saved[-1].dataset_id
    move(chain, built)
    db_session.expire_all()

    chain["owns"] = {built}
    again = build(db_session, chain, SCRIPT)
    assert "which now lives in Reader" in again.results[-1].message


# --- what it still refuses ---------------------------------------------------


def test_a_script_cannot_reach_a_dataset_it_did_not_build(db_session, chain):
    """`owns` is the whole permission, and it is only what the last run
    built. Moving does not widen it.

    With nothing claimed - a script that has not run before, or one rewritten
    since - the moved dataset is left alone and a new one is made in the
    script's own project. That is the old behaviour, kept for the case it was
    right for: this is not the script that built the moved copy.
    """
    first = build(db_session, chain, SCRIPT)
    db_session.commit()
    built = first.saved[-1].dataset_id
    move(chain, built)
    db_session.expire_all()

    before = db_session.get(Dataset, built).updated_at

    chain["owns"] = set()
    again = build(db_session, chain, SCRIPT)
    db_session.commit()
    db_session.expire_all()

    assert again.saved[-1].created is True, "a new dataset, not a takeover"
    assert again.saved[-1].dataset_id != built
    made = db_session.get(Dataset, again.saved[-1].dataset_id)
    assert made.project_id == chain["source"]
    # And the one it does not own was not touched.
    assert db_session.get(Dataset, built).updated_at == before


def test_nothing_changes_when_the_output_never_moved(db_session, chain):
    """The ordinary case, which is almost every script."""
    first = build(db_session, chain, SCRIPT)
    db_session.commit()
    built = first.saved[-1].dataset_id

    chain["owns"] = {built}
    again = build(db_session, chain, SCRIPT)
    db_session.flush()

    rows = named(db_session, chain, "linked_people")
    assert len(rows) == 1
    assert rows[0].project_id == chain["source"]
    assert again.saved[-1].dataset_id == built
    assert "which now lives in" not in again.results[-1].message
