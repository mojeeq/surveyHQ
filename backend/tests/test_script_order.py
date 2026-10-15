"""Which script has to run before which, and how that is known.

A script belongs to a project and is edited there. A survey office runs
several projects, and the scripts are not independent: one writes a cleaned
person file, that file is moved to the project that reports on it, and the
second script reads it. Run them the other way round and the second builds on
last week's data, silently, because nothing fails.

Nothing writes that order down. It is read off what each run actually opened
and saved - the same record the automatic re-run chain uses - rather than out
of the script text, which would mean resolving names the way `use` does and
would count a line that never ran.

The step is the point of it. Three scripts that wait on nobody are not first,
second and third; they are all first, and a page that numbers them 1, 2, 3
tells somebody to do sequentially what they could do at once.
"""

from __future__ import annotations

import datetime as dt

import pytest
from slugify import slugify

from app.models import Project, ProjectScript
from app.services.project_script import running_order


@pytest.fixture
def workshop(client, db_session):
    """Projects to hang scripts on, made as needed by name.

    Takes `client` because that fixture starts the application, which is what
    creates the tables; a test that only ever touches the session finds none.
    """
    made: dict[str, Project] = {}

    def project(name: str) -> Project:
        if name not in made:
            found = Project(name=name, slug=slugify(name))
            db_session.add(found)
            db_session.flush()
            made[name] = found
        return made[name]

    return project


def script(db_session, project, name: str, reads: list[str], writes: list[str]):
    row = ProjectScript(
        project_id=project(name).id,
        text="use something",
        reads=reads,
        writes=writes,
        last_run_at=dt.datetime(2026, 10, 1, tzinfo=dt.UTC),
    )
    db_session.add(row)
    db_session.flush()
    return row


def order(db_session, rows):
    return {place.project_name: place for place in running_order(db_session, rows)}


# --- the chain ---------------------------------------------------------------


def test_a_script_waits_for_the_one_that_writes_what_it_reads(db_session, workshop):
    cleaning = script(db_session, workshop, "Cleaning", ["raw"], ["clean"])
    reporting = script(db_session, workshop, "Reporting", ["clean"], ["table"])

    places = order(db_session, [reporting, cleaning])

    assert places["Cleaning"].step == 0
    assert places["Reporting"].step == 1
    assert places["Reporting"].waits_for == ["Cleaning"]
    assert places["Cleaning"].waits_for == []


def test_the_order_is_independent_of_the_order_they_came_in(db_session, workshop):
    """Sorted by name within a step, so the page does not reshuffle itself."""
    cleaning = script(db_session, workshop, "Cleaning", ["raw"], ["clean"])
    reporting = script(db_session, workshop, "Reporting", ["clean"], [])

    one = [place.project_name for place in running_order(db_session, [cleaning, reporting])]
    two = [place.project_name for place in running_order(db_session, [reporting, cleaning])]
    assert one == two == ["Cleaning", "Reporting"]


def test_a_chain_of_three_counts_up(db_session, workshop):
    first = script(db_session, workshop, "Import", ["raw"], ["clean"])
    second = script(db_session, workshop, "Join", ["clean"], ["joined"])
    third = script(db_session, workshop, "Publish", ["joined"], [])

    places = order(db_session, [third, second, first])
    assert [places[n].step for n in ("Import", "Join", "Publish")] == [0, 1, 2]


# --- what a step means -------------------------------------------------------


def test_scripts_that_wait_on_nobody_share_the_first_step(db_session, workshop):
    """Not first, second and third. All first, which is the useful fact: they
    can be run in any order, or at the same time."""
    rows = [
        script(db_session, workshop, "Alpha", ["a"], []),
        script(db_session, workshop, "Bravo", ["b"], []),
        script(db_session, workshop, "Charlie", ["c"], []),
    ]
    places = order(db_session, rows)
    assert {places[n].step for n in ("Alpha", "Bravo", "Charlie")} == {0}


def test_two_scripts_waiting_on_one_share_the_second_step(db_session, workshop):
    source = script(db_session, workshop, "Source", [], ["clean"])
    left = script(db_session, workshop, "Left", ["clean"], [])
    right = script(db_session, workshop, "Right", ["clean"], [])

    places = order(db_session, [left, right, source])
    assert places["Source"].step == 0
    assert places["Left"].step == places["Right"].step == 1


def test_a_step_counts_the_longest_wait_not_the_shortest(db_session, workshop):
    """A script reading from both ends of a chain waits for the far end."""
    first = script(db_session, workshop, "Import", ["raw"], ["clean"])
    middle = script(db_session, workshop, "Join", ["clean"], ["joined"])
    last = script(db_session, workshop, "Publish", ["clean", "joined"], [])

    places = order(db_session, [last, middle, first])
    assert places["Publish"].step == 2, "not 1, which reading only 'clean' would give"


# --- what it refuses to invent -----------------------------------------------


def test_a_reader_waits_for_every_writer_not_the_first(db_session, workshop):
    """One writer per dataset looked like a rule and is not.

    `save as` refuses a dataset another script owns, which is where that idea
    came from. But `save, replace` writes back over whatever the script
    opened and claims nothing, so a second project's script can write a
    dataset the first still lists from the run that made it. Keeping only the
    first writer put the reader after one and before the other - the stale
    read this page exists to prevent, arrived at by following it.
    """
    maker = script(db_session, workshop, "Maker", ["raw"], ["shared"])
    amender = script(db_session, workshop, "Amender", ["shared"], ["shared"])
    reader = script(db_session, workshop, "Reader", ["shared"], [])

    places = order(db_session, [reader, amender, maker])

    assert places["Reader"].waits_for == ["Amender", "Maker"]
    assert places["Reader"].step > max(places["Maker"].step, places["Amender"].step)


def test_a_ring_is_reported_rather_than_ordered(db_session, workshop):
    """Each reads what the other writes. There is no order, and the page says
    so rather than picking one and being wrong about it."""
    one = script(db_session, workshop, "Eggs", ["chicken"], ["egg"])
    two = script(db_session, workshop, "Chickens", ["egg"], ["chicken"])

    places = order(db_session, [one, two])
    assert places["Eggs"].in_a_cycle and places["Chickens"].in_a_cycle


def test_a_ring_does_not_take_the_rest_of_the_list_with_it(db_session, workshop):
    one = script(db_session, workshop, "Eggs", ["chicken"], ["egg"])
    two = script(db_session, workshop, "Chickens", ["egg"], ["chicken"])
    fine = script(db_session, workshop, "Apples", ["orchard"], [])

    places = order(db_session, [one, two, fine])
    assert not places["Apples"].in_a_cycle
    assert places["Apples"].step == 0


def test_a_script_reading_what_it_writes_is_not_a_ring(db_session, workshop):
    """`use people` then `save, replace` is the commonest script there is."""
    row = script(db_session, workshop, "In place", ["people"], ["people"])

    places = order(db_session, [row])
    assert not places["In place"].in_a_cycle
    assert places["In place"].step == 0
    assert places["In place"].waits_for == []


def test_a_script_that_has_never_run_has_no_place_to_claim(db_session, workshop):
    """Nothing is recorded, so nothing is known about what it will touch. It
    sits with everything else that waits on nobody rather than being guessed
    at from its text."""
    never = ProjectScript(project_id=workshop("Draft").id, text="use people", reads=[], writes=[])
    db_session.add(never)
    db_session.flush()

    places = order(db_session, [never])
    assert places["Draft"].step == 0
    assert places["Draft"].waits_for == []


# --- the endpoint ------------------------------------------------------------


def test_the_overview_names_datasets_rather_than_ids(client, auth_headers, db_session):
    """Whoever reads this is looking at a page, not a database."""
    from app.models import Dataset

    owner = Project(name="Names not ids", slug="names-not-ids")
    db_session.add(owner)
    db_session.flush()
    file = Dataset(name="cleaned_people", slug="cleaned-people", project_id=owner.id)
    db_session.add(file)
    db_session.flush()
    db_session.add(
        ProjectScript(
            project_id=owner.id,
            text="use cleaned_people",
            reads=[file.id],
            writes=[file.id],
            last_run_at=dt.datetime(2026, 10, 1, tzinfo=dt.UTC),
        )
    )
    db_session.commit()

    answered = client.get("/api/v1/scripts", headers=auth_headers)
    assert answered.status_code == 200
    mine = next(
        place
        for place in answered.json()["places"]
        if place["project_name"] == "Names not ids"
    )
    assert mine["reads"] == ["cleaned_people"]
    assert mine["writes"] == ["cleaned_people"]
    assert file.id not in mine["reads"]


def test_the_overview_leaves_out_a_script_nobody_has_written(
    client, auth_headers, db_session
):
    """A row is made the first time anybody opens the script tab, so most
    projects have one and almost none of them is a script."""
    empty = Project(name="No script here", slug="no-script-here")
    db_session.add(empty)
    db_session.flush()
    db_session.add(ProjectScript(project_id=empty.id, text="", reads=[], writes=[]))
    db_session.commit()

    answered = client.get("/api/v1/scripts", headers=auth_headers)
    names = [place["project_name"] for place in answered.json()["places"]]
    assert "No script here" not in names


def test_the_overview_keeps_a_script_that_ran_without_being_saved(
    client, auth_headers, db_session
):
    """Running is deliberately separate from saving - a script is tried before
    it is kept - so an empty text with a run behind it is a real script."""
    tried = Project(name="Tried not kept", slug="tried-not-kept")
    db_session.add(tried)
    db_session.flush()
    db_session.add(
        ProjectScript(
            project_id=tried.id,
            text="",
            reads=[],
            writes=[],
            last_run_at=dt.datetime(2026, 10, 1, tzinfo=dt.UTC),
        )
    )
    db_session.commit()

    answered = client.get("/api/v1/scripts", headers=auth_headers)
    names = [place["project_name"] for place in answered.json()["places"]]
    assert "Tried not kept" in names
