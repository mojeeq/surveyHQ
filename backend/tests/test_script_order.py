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


def test_the_overview_says_who_may_change_each_script(client, auth_headers, db_session):
    """Seeing a script and being able to change it are different questions.

    The page lists every project the reader can see, and offers a way into the
    editor. Running a script writes the project's datasets, so that editor
    takes the manager role over that project - which most readers of most of
    these projects do not have.

    Offered to everybody, the button put them back on the project with nothing
    said, which is the fault the page had before it had any button at all. So
    each entry says whether this reader may, and the page offers the way in
    only where there is one.
    """
    from app.core.security import hash_password
    from app.models import ProjectMember, Role, User

    seen = Project(name="Script they may read", slug="script-they-may-read")
    mine = Project(name="Script they may change", slug="script-they-may-change")
    db_session.add_all([seen, mine])
    db_session.flush()
    for project in (seen, mine):
        db_session.add(
            ProjectScript(
                project_id=project.id,
                text="use people",
                last_run_at=dt.datetime(2026, 10, 1, tzinfo=dt.UTC),
            )
        )
    # A manager on the platform: a membership can never exceed the user's own
    # role, so an analyst cannot be a project's manager however they are
    # enrolled, and the pair below would both come back False.
    reader = User(
        email="reader@example.org",
        username="reader",
        full_name="A Reader",
        hashed_password=hash_password("Fieldwork-2026-reader"),
        role=Role.manager,
    )
    db_session.add(reader)
    db_session.flush()
    db_session.add_all(
        [
            ProjectMember(project_id=seen.id, user_id=reader.id, role=Role.viewer),
            ProjectMember(project_id=mine.id, user_id=reader.id, role=Role.manager),
        ]
    )
    db_session.commit()

    token = client.post(
        "/api/v1/auth/login",
        json={"email": "reader@example.org", "password": "Fieldwork-2026-reader"},
    ).json()["access_token"]
    answered = client.get(
        "/api/v1/scripts", headers={"Authorization": f"Bearer {token}"}
    )
    assert answered.status_code == 200, answered.text
    by_name = {place["project_name"]: place for place in answered.json()["places"]}

    # Both are listed: the page is about the order, and a script they cannot
    # change is still one their own has to run after. The global role is the
    # same for both, so what separates them is the membership - which is the
    # question the page was not asking.
    assert by_name["Script they may read"]["can_edit"] is False
    assert by_name["Script they may change"]["can_edit"] is True

    # And an administrator may change either.
    everything = client.get("/api/v1/scripts", headers=auth_headers).json()["places"]
    for place in everything:
        assert place["can_edit"] is True, place["project_name"]


def test_the_overview_reads_memberships_once(client, auth_headers, db_session):
    """However many projects a reader can see.

    Whether somebody may change a script is a question about their membership
    of that project, and the function that answers it reads their memberships
    from the database each time it is asked. Asked once per project, opening
    this page cost a query per project the reader could see - including the
    ones with no script on the page at all.

    Counted rather than reasoned about: the queries are the thing that grows,
    so the test watches for them.
    """
    from sqlalchemy import event

    from app.api.v1.endpoints import scripts as endpoint
    from app.core.security import hash_password
    from app.models import ProjectMember, Role, User

    reader = User(
        email="counts@example.org",
        username="counts",
        full_name="Many Projects",
        hashed_password=hash_password("Fieldwork-2026-counts"),
        role=Role.manager,
    )
    db_session.add(reader)
    db_session.flush()
    for index in range(8):
        project = Project(name=f"Counted {index}", slug=f"counted-{index}")
        db_session.add(project)
        db_session.flush()
        db_session.add_all(
            [
                ProjectScript(
                    project_id=project.id,
                    text="use people",
                    last_run_at=dt.datetime(2026, 10, 1, tzinfo=dt.UTC),
                ),
                ProjectMember(
                    project_id=project.id, user_id=reader.id, role=Role.manager
                ),
            ]
        )
    db_session.commit()

    seen: list[str] = []

    def watch(conn, cursor, statement, parameters, context, executemany):
        if "project_members" in statement:
            seen.append(statement)

    engine = db_session.get_bind()
    event.listen(engine, "before_cursor_execute", watch)
    try:
        answered = endpoint.overview(db_session, reader)
    finally:
        event.remove(engine, "before_cursor_execute", watch)

    assert len(answered.places) >= 8
    assert all(place.can_edit for place in answered.places)
    # One to work out what they can see, one to work out what they may change.
    # Not one per project, which is what this is here to stop coming back.
    assert len(seen) <= 2, f"{len(seen)} membership queries for 8 projects"


# --- choosing the order within a step ---------------------------------------
#
# Which script runs before which comes from what they read and write, and that
# part is nobody's to rearrange. Within a step nothing waits on anything, and
# the order there was alphabetical - no order at all for somebody who knows
# which one they do first on a Monday.


def _ordered(client, headers) -> list[str]:
    answered = client.get("/api/v1/scripts", headers=headers)
    assert answered.status_code == 200, answered.text
    return [place["project_name"] for place in answered.json()["places"]]


def _ordered_ids(client, headers) -> list[str]:
    """By id rather than by name: these tests run beside others that make
    projects of their own, and a name is not unique across them."""
    answered = client.get("/api/v1/scripts", headers=headers)
    assert answered.status_code == 200, answered.text
    return [place["project_id"] for place in answered.json()["places"]]


def _step_holding(client, headers, project_id) -> list[str]:
    """Every project in the step this one is in, in the order shown.

    Read from the page rather than assumed: other scripts share these steps,
    and the endpoint wants the whole step - which is what the page has in
    front of it when somebody moves a card.
    """
    places = client.get("/api/v1/scripts", headers=headers).json()["places"]
    mine = next(place for place in places if place["project_id"] == project_id)
    return [
        place["project_id"]
        for place in places
        if place["step"] == mine["step"] and not place["in_a_cycle"]
    ]


def _swapped(order: list[str], first: str, second: str) -> list[str]:
    """The same step with those two exchanged."""
    out = list(order)
    a, b = out.index(first), out.index(second)
    out[a], out[b] = out[b], out[a]
    return out


@pytest.fixture
def two_free(db_session, request) -> dict:
    """Two scripts in one step: neither reads what the other writes.

    Named per test: the slug is unique across the database, and these run
    more than once.
    """
    tag = request.node.name[-12:].replace("_", "-")
    first = Project(name="Alpha free", slug=f"alpha-free-{tag}")
    second = Project(name="Beta free", slug=f"beta-free-{tag}")
    db_session.add_all([first, second])
    db_session.flush()
    for project in (first, second):
        db_session.add(
            ProjectScript(
                project_id=project.id,
                text="use people",
                last_run_at=dt.datetime(2026, 10, 1, tzinfo=dt.UTC),
            )
        )
    db_session.commit()
    return {"first": first.id, "second": second.id}


def test_a_step_can_be_put_in_the_order_somebody_wants(
    client, auth_headers, db_session, two_free
):
    """The fault this exists for: alphabetical, and no way to say otherwise."""
    order = _ordered_ids(client, auth_headers)
    assert order.index(two_free["first"]) < order.index(two_free["second"])

    step = _step_holding(client, auth_headers, two_free["first"])
    moved = client.put(
        "/api/v1/scripts/order",
        headers=auth_headers,
        json={
            "project_ids": _swapped(step, two_free["first"], two_free["second"])
        },
    )
    assert moved.status_code == 200, moved.text

    order = _ordered_ids(client, auth_headers)
    assert order.index(two_free["second"]) < order.index(two_free["first"])


def test_the_chosen_order_survives_a_reload(
    client, auth_headers, db_session, two_free
):
    """Kept against the script rather than in the page."""
    step = _step_holding(client, auth_headers, two_free["first"])
    client.put(
        "/api/v1/scripts/order",
        headers=auth_headers,
        json={
            "project_ids": _swapped(step, two_free["first"], two_free["second"])
        },
    )
    db_session.expire_all()
    order = _ordered_ids(client, auth_headers)
    assert order.index(two_free["second"]) < order.index(two_free["first"])


def test_a_script_cannot_be_moved_past_what_it_waits_for(
    client, auth_headers, db_session
):
    """The half of the order that is not anybody's to choose.

    One writes the file the other reads, so the second cannot go first, and a
    rank that said otherwise would be stored and then silently ignored by the
    sort. Refused instead, naming what fixes them.
    """
    from app.models import Dataset

    writer = Project(name="Writes it", slug="writes-it")
    reader = Project(name="Reads it", slug="reads-it")
    db_session.add_all([writer, reader])
    db_session.flush()
    shared = Dataset(name="handover", slug="handover", project_id=writer.id)
    db_session.add(shared)
    db_session.flush()
    db_session.add_all(
        [
            ProjectScript(
                project_id=writer.id,
                text="save as handover",
                writes=[shared.id],
                last_run_at=dt.datetime(2026, 10, 1, tzinfo=dt.UTC),
            ),
            ProjectScript(
                project_id=reader.id,
                text="use handover",
                reads=[shared.id],
                last_run_at=dt.datetime(2026, 10, 1, tzinfo=dt.UTC),
            ),
        ]
    )
    db_session.commit()

    refused = client.put(
        "/api/v1/scripts/order",
        headers=auth_headers,
        json={"project_ids": [reader.id, writer.id]},
    )
    assert refused.status_code == 422, refused.text
    said = refused.json()["detail"]
    assert "Reads it" in said and "Writes it" in said, said
    # And the order is unchanged: nothing was half applied.
    names = _ordered(client, auth_headers)
    assert names.index("Writes it") < names.index("Reads it")


def test_part_of_a_step_is_refused(client, auth_headers, db_session, two_free):
    """Half a step leaves the rest at a rank nobody chose."""
    refused = client.put(
        "/api/v1/scripts/order",
        headers=auth_headers,
        json={"project_ids": [two_free["first"]]},
    )
    assert refused.status_code == 422, refused.text


def test_reordering_needs_the_manager_role_on_every_script_moved(
    client, auth_headers, db_session, two_free
):
    """Moving one script past another changes where both of them run."""
    from app.core.security import hash_password
    from app.models import ProjectMember, Role, User

    half = User(
        email="half@example.org",
        username="half",
        full_name="Half A Manager",
        hashed_password=hash_password("Fieldwork-2026-half"),
        role=Role.manager,
    )
    db_session.add(half)
    db_session.flush()
    db_session.add_all(
        [
            ProjectMember(
                project_id=two_free["first"], user_id=half.id, role=Role.manager
            ),
            ProjectMember(
                project_id=two_free["second"], user_id=half.id, role=Role.viewer
            ),
        ]
    )
    db_session.commit()

    token = client.post(
        "/api/v1/auth/login",
        json={"email": "half@example.org", "password": "Fieldwork-2026-half"},
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    # Their own view of the step: they see only the two they belong to.
    step = _step_holding(client, headers, two_free["first"])
    refused = client.put(
        "/api/v1/scripts/order",
        headers=headers,
        json={
            "project_ids": _swapped(step, two_free["first"], two_free["second"])
        },
    )
    assert refused.status_code == 403, refused.text
    assert "Beta free" in refused.json()["detail"]


def test_a_ring_elsewhere_does_not_block_reordering_a_step(
    client, auth_headers, db_session, two_free
):
    """A ring sits at step 0 and is marked as having no order, and the page
    draws it in a section of its own. The check for "the whole step" counted
    it anyway, so one tangled pair anywhere made every step-0 group
    unreorderable - refused with "Give the whole step" over a list that was
    the whole step.
    """
    from app.models import Dataset

    left = Project(name="Ring left", slug="ring-left")
    right = Project(name="Ring right", slug="ring-right")
    db_session.add_all([left, right])
    db_session.flush()
    theirs = Dataset(name="ring_a", slug="ring-a", project_id=left.id)
    mine = Dataset(name="ring_b", slug="ring-b", project_id=right.id)
    db_session.add_all([theirs, mine])
    db_session.flush()
    # Each reads what the other writes.
    db_session.add_all(
        [
            ProjectScript(
                project_id=left.id,
                text="use ring_b\nsave as ring_a",
                reads=[mine.id],
                writes=[theirs.id],
                last_run_at=dt.datetime(2026, 10, 1, tzinfo=dt.UTC),
            ),
            ProjectScript(
                project_id=right.id,
                text="use ring_a\nsave as ring_b",
                reads=[theirs.id],
                writes=[mine.id],
                last_run_at=dt.datetime(2026, 10, 1, tzinfo=dt.UTC),
            ),
        ]
    )
    db_session.commit()

    places = client.get("/api/v1/scripts", headers=auth_headers).json()["places"]
    tangled = [one["project_name"] for one in places if one["in_a_cycle"]]
    assert "Ring left" in tangled, "the ring has to be a ring for this to prove anything"

    step = _step_holding(client, auth_headers, two_free["first"])
    moved = client.put(
        "/api/v1/scripts/order",
        headers=auth_headers,
        json={
            "project_ids": _swapped(step, two_free["first"], two_free["second"])
        },
    )
    assert moved.status_code == 200, moved.text
    order = _ordered_ids(client, auth_headers)
    assert order.index(two_free["second"]) < order.index(two_free["first"])
