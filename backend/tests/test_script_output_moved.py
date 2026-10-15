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
from app.services import project_script, stata
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
    """Run the source project's script through the service the endpoint uses.

    Not `stata.run_project_script` directly: this is the layer that records
    what the run read and saved against the project's script row, and the
    permission to rebuild a moved output is granted from that record at the
    moment of the move. A test that skipped it would move a dataset nothing
    had claimed and never exercise the grant at all.
    """
    return project_script.run(db_session, chain["source"], text)


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

    again = build(db_session, chain, SCRIPT)
    assert "which now lives in Reader" in again.results[-1].message


# --- what it still refuses ---------------------------------------------------


def test_a_move_nobody_agreed_to_is_refused(db_session, chain):
    """Authorship is not authorisation.

    `owns` is read off what a past run saved. Nobody agreed to it, and the
    source project's manager need never have had any rights over the project
    the output now sits in - so on its own it would let them write there by
    running their own script. The permission is the move, which needs the
    manager role on both sides, and is recorded on the dataset at the time.

    Here the grant is cleared, standing for a dataset that reached the other
    project some other way, or one whose move was undone.
    """
    first = build(db_session, chain, SCRIPT)
    db_session.commit()
    built = first.saved[-1].dataset_id
    move(chain, built)
    db_session.expire_all()

    moved = db_session.get(Dataset, built)
    meta = dict(moved.meta or {})
    meta.pop(project_script.REBUILT_BY, None)
    moved.meta = meta
    db_session.commit()
    before = db_session.get(Dataset, built).updated_at

    with pytest.raises(stata.CommandError) as raised:
        build(db_session, chain, SCRIPT)
    assert "has not agreed" in str(raised.value)

    # And nothing was written to it.
    db_session.rollback()
    db_session.expire_all()
    assert db_session.get(Dataset, built).updated_at == before


def test_an_archived_destination_is_refused(db_session, chain):
    """An archived project keeps its dataset rows and loses their data.
    Rebuilding into one would leave it holding live data again, which is the
    half-unarchived state every other path refuses to create."""
    from app.models import Project

    first = build(db_session, chain, SCRIPT)
    db_session.commit()
    built = first.saved[-1].dataset_id
    move(chain, built)
    db_session.expire_all()

    reader = db_session.get(Project, chain["reader"])
    reader.status = "archived"
    db_session.commit()

    with pytest.raises(stata.CommandError) as raised:
        build(db_session, chain, SCRIPT)
    assert "archived" in str(raised.value)


def test_nothing_changes_when_the_output_never_moved(db_session, chain):
    """The ordinary case, which is almost every script."""
    first = build(db_session, chain, SCRIPT)
    db_session.commit()
    built = first.saved[-1].dataset_id

    again = build(db_session, chain, SCRIPT)
    db_session.flush()

    rows = named(db_session, chain, "linked_people")
    assert len(rows) == 1
    assert rows[0].project_id == chain["source"]
    assert again.saved[-1].dataset_id == built
    assert "which now lives in" not in again.results[-1].message


def test_every_writer_is_granted_not_whichever_came_back_first(db_session, chain):
    """One writer per dataset is not a rule, so one claimant is not an answer.

    `save, replace` writes back over whatever the script opened and claims
    nothing, so two projects' scripts can both hold the same id. Reading one
    claimant out of an unordered query authorises whichever row the database
    yielded, refuses the rest, and can change its mind between runs.
    """
    from app.models import Project, ProjectScript

    first = build(db_session, chain, SCRIPT)
    db_session.commit()
    built = first.saved[-1].dataset_id

    # A second project whose script also wrote it, as `save, replace` allows.
    other = Project(name="Amender", slug="amender-grant")
    db_session.add(other)
    db_session.flush()
    db_session.add(ProjectScript(project_id=other.id, text="use x", reads=[], writes=[built]))
    db_session.commit()

    move(chain, built)
    db_session.expire_all()

    granted = (db_session.get(Dataset, built).meta or {}).get(
        project_script.REBUILT_BY
    )
    assert sorted(granted) == sorted([chain["source"], other.id])
    # And the order is settled rather than whatever came back.
    assert granted == sorted(granted)


def test_releasing_a_dataset_to_the_shared_area_drops_the_grant(
    client, auth_headers, db_session, chain
):
    """Deleting a project without its contents lets its datasets go to the
    shared area. Nobody chose that destination, so nobody granted anything -
    and a grant surviving it would outlive the project it was about."""
    first = build(db_session, chain, SCRIPT)
    db_session.commit()
    built = first.saved[-1].dataset_id
    move(chain, built)
    db_session.expire_all()
    assert (db_session.get(Dataset, built).meta or {}).get(project_script.REBUILT_BY)

    gone = client.delete(
        f"/api/v1/projects/{chain['reader']}", headers=auth_headers
    )
    assert gone.status_code < 300, gone.text
    db_session.expire_all()

    released = db_session.get(Dataset, built)
    assert released.project_id is None
    assert not (released.meta or {}).get(project_script.REBUILT_BY)

    # And the script that built it can no longer write there.
    with pytest.raises(stata.CommandError) as raised:
        build(db_session, chain, SCRIPT)
    assert "has not agreed" in str(raised.value)


def test_seeing_a_project_is_not_grounds_for_running_its_script(
    client, auth_headers, db_session, chain
):
    """A global manager who is only a viewer here could run the script, which
    writes this project's datasets - and now, through a grant, writes into the
    project an output moved to. The role that matters is the one held over
    this project."""
    from app.core.security import hash_password
    from app.models import ProjectMember, Role, User

    viewer = User(
        email="viewer-on-source@example.org",
        full_name="Viewer",
        hashed_password=hash_password("Fieldwork-2026-local"),
        role=Role.manager,
        must_change_password=False,
    )
    db_session.add(viewer)
    db_session.flush()
    db_session.add(
        ProjectMember(project_id=chain["source"], user_id=viewer.id, role=Role.viewer)
    )
    db_session.commit()

    signed_in = client.post(
        "/api/v1/auth/login",
        json={"email": viewer.email, "password": "Fieldwork-2026-local"},
    )
    assert signed_in.status_code == 200, signed_in.text
    headers = {"Authorization": f"Bearer {signed_in.json()['access_token']}"}

    refused = client.post(
        f"/api/v1/projects/{chain['source']}/script/run",
        headers=headers,
        json={"text": SCRIPT},
    )
    assert refused.status_code == 403, refused.text

    # And the same for saving the recipe.
    kept = client.put(
        f"/api/v1/projects/{chain['source']}/script",
        headers=headers,
        json={"text": SCRIPT},
    )
    assert kept.status_code == 403, kept.text


def test_the_grant_is_not_handed_to_everybody_who_can_see_the_dataset(
    client, auth_headers, db_session, chain
):
    """The grant names projects by id. Anybody able to see the project the
    dataset moved to would otherwise be handed ids for projects they cannot
    reach - which the project routes answer 404 rather than 403 to prevent."""
    first = build(db_session, chain, SCRIPT)
    db_session.commit()
    built = first.saved[-1].dataset_id
    move(chain, built)
    db_session.expire_all()

    # It is recorded...
    assert (db_session.get(Dataset, built).meta or {}).get(project_script.REBUILT_BY)

    # ...and not sent out.
    answered = client.get(f"/api/v1/datasets/{built}", headers=auth_headers)
    assert answered.status_code == 200, answered.text
    assert project_script.REBUILT_BY not in (answered.json().get("meta") or {})
