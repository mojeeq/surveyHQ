"""API regressions for cross-project reads and project-role write bypasses."""

from uuid import uuid4

import pytest

from app.core.security import create_access_token
from app.models import (
    BoundaryLayer,
    Chart,
    Dashboard,
    Dataset,
    Indicator,
    Project,
    ProjectMember,
    Role,
    User,
    Widget,
)


@pytest.fixture
def scenario(client, auth_headers, db_session):
    db = db_session
    own = Project(name="Own", slug=uuid4().hex)
    foreign = Project(name="Private", slug=uuid4().hex)
    user = User(email=f"{uuid4().hex}@example.com", hashed_password="unused",
                role=Role.manager, restricted_to_projects=True, is_active=True)
    db.add_all([own, foreign, user])
    db.flush()
    member = ProjectMember(project_id=own.id, user_id=user.id, role=Role.manager)
    db.add(member)
    db.commit()
    headers = {"Authorization": f"Bearer {create_access_token(user.id)}"}
    uploaded = client.post(
        "/api/v1/datasets/upload", headers=auth_headers,
        files={"file": ("secret.csv", b"interview__key,secret\nsecret-001,123\n", "text/csv")},
        data={"name": "Private data", "project_id": foreign.id},
    )
    assert uploaded.status_code == 201, uploaded.text
    dataset = db.get(Dataset, uploaded.json()["id"])
    chart = Chart(name="Private chart", dataset_id=dataset.id, spec={})
    indicator = Indicator(name="Private indicator", dataset_id=dataset.id, last_value=123)
    layer = BoundaryLayer(name="Private boundaries", project_id=foreign.id,
                          storage_path="not-read.geojson")
    board = Dashboard(name="Own board", slug=uuid4().hex, project_id=own.id,
                      created_by=user.id, is_public=True, public_token=uuid4().hex)
    db.add_all([chart, indicator, layer, board])
    db.commit()
    return {"db": db, "user": user, "member": member, "own": own, "foreign": foreign,
            "dataset": dataset, "chart": chart, "indicator": indicator, "layer": layer,
            "board": board, "headers": headers}


def widget_input(s, kind):
    if kind == "direct":
        return {"dataset_id": s["dataset"].id}
    if kind == "nested":
        return {"config": {"dataset_id": s["dataset"].id}}
    if kind == "chart":
        return {"chart_id": s["chart"].id}
    if kind == "indicator":
        return {"widget_type": "indicator", "indicator_id": s["indicator"].id}
    if kind == "freshness":
        return {"widget_type": "freshness", "config": {"dataset_ids": [s["dataset"].id]}}
    return {"widget_type": "map", "config": {"boundary_id": s["layer"].id}}


@pytest.mark.parametrize("kind", ["direct", "nested", "chart", "indicator", "freshness", "boundary"])
@pytest.mark.parametrize("route", ["add", "widget_patch", "replace_all"])
def test_foreign_sources_rejected_at_every_widget_write(client, scenario, kind, route):
    s = scenario
    base = f"/api/v1/dashboards/{s['board'].id}"
    payload = widget_input(s, kind)
    assert client.get(f"/api/v1/datasets/{s['dataset'].id}", headers=s["headers"]).status_code == 404
    if route == "add":
        response = client.post(base + "/widgets", headers=s["headers"], json=payload)
    elif route == "replace_all":
        response = client.patch(base, headers=s["headers"], json={"widgets": [payload]})
    else:
        added = client.post(base + "/widgets", headers=s["headers"], json={"widget_type": "text"})
        assert added.status_code == 201, added.text
        identity = added.json()["widgets"][0]["id"]
        response = client.patch(base + f"/widgets/{identity}", headers=s["headers"], json=payload)
    assert response.status_code == 404, response.text
    # The refused transaction must not leave a usable source behind.
    rendered = client.post(base + "/data", headers=s["headers"])
    assert rendered.status_code == 200, rendered.text
    assert "secret-001" not in rendered.text


@pytest.mark.parametrize("create", [False, True])
def test_filter_reference_is_checked(client, scenario, create):
    s = scenario
    filters = [{"variable": "interview__key", "dataset_id": s["dataset"].id}]
    if create:
        response = client.post("/api/v1/dashboards", headers=s["headers"], json={
            "name": "Bad filter", "project_id": s["own"].id, "filters": filters,
        })
    else:
        response = client.patch(f"/api/v1/dashboards/{s['board'].id}",
                                headers=s["headers"], json={"filters": filters})
    assert response.status_code == 404, response.text


@pytest.mark.parametrize("kind", ["direct", "nested", "chart", "indicator", "freshness", "boundary", "filter"])
def test_old_unapproved_sources_cannot_render_or_export(client, scenario, kind):
    s = scenario
    board = s["board"]
    if kind == "filter":
        board.filters = [{"variable": "interview__key", "dataset_id": s["dataset"].id}]
    else:
        s["db"].add(Widget(dashboard_id=board.id, **widget_input(s, kind)))
    s["db"].commit()
    base = f"/api/v1/dashboards/{board.id}"
    assert client.post(base + "/data", headers=s["headers"]).status_code == 404
    assert client.post(f"/api/v1/public/dashboards/{board.public_token}/data").status_code == 404
    assert client.get(base + "/export.html", headers=s["headers"]).status_code == 404
    if kind == "filter":
        assert client.get(f"/api/v1/public/dashboards/{board.public_token}/filter-values/interview__key").status_code == 404
    if kind == "boundary":
        assert client.get(f"/api/v1/public/dashboards/{board.public_token}/boundaries/{s['layer'].id}").status_code == 404


def test_approved_cross_project_sharing_and_revocation(client, scenario):
    s = scenario
    membership = ProjectMember(project_id=s["foreign"].id, user_id=s["user"].id, role=Role.viewer)
    s["db"].add(membership)
    s["db"].commit()
    base = f"/api/v1/dashboards/{s['board'].id}"
    response = client.post(base + "/widgets", headers=s["headers"], json={
        "dataset_id": s["dataset"].id,
        "config": {"query": {"dimensions": [{"variable": "interview__key"}], "measures": [{"agg": "count"}]}},
    })
    assert response.status_code == 201, response.text
    public = f"/api/v1/public/dashboards/{s['board'].public_token}/data"
    rendered = client.post(public)
    assert rendered.status_code == 200 and "secret-001" in rendered.text
    s["db"].delete(membership)
    s["db"].commit()
    assert client.post(public).status_code == 404
    assert client.get(base + "/export.html", headers=s["headers"]).status_code == 404


def test_moving_approved_source_invalidates_grant(client, scenario, auth_headers):
    s = scenario
    base = f"/api/v1/dashboards/{s['board'].id}"
    response = client.post(base + "/widgets", headers=auth_headers,
                           json={"dataset_id": s["dataset"].id})
    assert response.status_code == 201
    s["dataset"].project_id = s["own"].id
    s["db"].commit()
    assert client.post(base + "/data", headers=s["headers"]).status_code == 404


@pytest.mark.parametrize("method,suffix,body", [
    ("patch", "", {"is_public": True}),
    ("delete", "", None),
    ("post", "/widgets", {"widget_type": "text"}),
    ("post", "/duplicate", None),
    ("post", "/share-links", {"name": "Leak"}),
    ("delete", "/background", None),
    ("delete", "/logo", None),
])
def test_project_viewer_cannot_change_dashboard(client, scenario, method, suffix, body):
    s = scenario
    s["member"].role = Role.viewer
    s["db"].commit()
    base = f"/api/v1/dashboards/{s['board'].id}"
    assert client.get(base, headers=s["headers"]).status_code == 200
    response = getattr(client, method)(base + suffix, headers=s["headers"],
                                       **({"json": body} if body is not None else {}))
    assert response.status_code == 404, response.text
    assert client.get(base, headers=s["headers"]).status_code == 200


@pytest.mark.parametrize("method,suffix", [("patch", ""), ("delete", ""), ("post", "/replace"), ("post", "/append")])
def test_project_viewer_cannot_modify_dataset(client, scenario, method, suffix):
    s = scenario
    s["db"].add(ProjectMember(project_id=s["foreign"].id, user_id=s["user"].id, role=Role.viewer))
    s["db"].commit()
    base = f"/api/v1/datasets/{s['dataset'].id}"
    assert client.get(base, headers=s["headers"]).status_code == 200
    kwargs = {"files": {"file": ("edit.csv", b"secret\n999\n", "text/csv")}} if suffix else {}
    if method == "patch":
        kwargs = {"json": {"name": "Tampered"}}
    response = getattr(client, method)(base + suffix, headers=s["headers"], **kwargs)
    assert response.status_code == 404, response.text
    assert client.get(base, headers=s["headers"]).json()["name"] == "Private data"


def test_grants_cannot_be_supplied_by_client(client, scenario):
    s = scenario
    response = client.patch(f"/api/v1/dashboards/{s['board'].id}", headers=s["headers"], json={
        "source_grants": {f"datasets:{s['dataset'].id}": {"project_id": s["foreign"].id, "user_id": s["user"].id}},
    })
    assert response.status_code == 200
    s["db"].refresh(s["board"])
    assert s["board"].source_grants == {}


@pytest.mark.parametrize("resource,method", [
    ("chart", "patch"), ("chart", "delete"),
    ("indicator", "patch"), ("indicator", "delete"),
    ("layer", "patch"), ("layer", "delete"),
])
def test_project_viewer_cannot_change_related_resources(client, scenario, resource, method):
    s = scenario
    s["db"].add(ProjectMember(project_id=s["foreign"].id, user_id=s["user"].id, role=Role.viewer))
    s["db"].commit()
    paths = {"chart": "dashboards/charts", "indicator": "monitoring/indicators", "layer": "boundaries"}
    url = f"/api/v1/{paths[resource]}/{s[resource].id}"
    response = getattr(client, method)(url, headers=s["headers"],
                                       **({"json": {"name": "Tampered"}} if method == "patch" else {}))
    assert response.status_code == 404, response.text
    s["db"].refresh(s[resource])
    assert s[resource].name.startswith("Private")


def test_project_viewer_can_keep_private_views_but_not_publish_them(client, scenario):
    s = scenario
    s["member"].role = Role.viewer
    s["db"].commit()
    base = f"/api/v1/dashboards/{s['board'].id}/views"
    response = client.post(base, headers=s["headers"], json={
        "name": "Personal", "is_shared": True, "is_default": True,
    })
    assert response.status_code == 201, response.text
    assert not response.json()["is_shared"] and not response.json()["is_default"]


def test_legitimate_same_project_sources_work(client, scenario):
    s = scenario
    s["dataset"].project_id = s["own"].id
    s["db"].commit()
    base = f"/api/v1/dashboards/{s['board'].id}"
    added = client.post(base + "/widgets", headers=s["headers"], json={
        "dataset_id": s["dataset"].id, "config": {
            "query": {"dimensions": [{"variable": "interview__key"}], "measures": [{"agg": "count"}]},
        },
    })
    assert added.status_code == 201, added.text
    rendered = client.post(base + "/data", headers=s["headers"])
    assert rendered.status_code == 200 and "secret-001" in rendered.text


    # A pre-upgrade same-project board needs no manual reapproval.
    s["db"].refresh(s["board"])
    s["board"].source_grants = {}
    s["db"].commit()
    rendered = client.post(base + "/data", headers=s["headers"])
    assert rendered.status_code == 200 and "secret-001" in rendered.text


def test_existing_database_gets_server_owned_grants(tmp_path):
    from sqlalchemy import create_engine, inspect, text
    from sqlalchemy.orm import Session

    from app.db.base import Base
    from app.db.migrations import require_current, upgrade

    engine = create_engine(f"sqlite:///{tmp_path / 'before-access-fix.db'}")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        board = Dashboard(name="Existing board", slug="existing-board")
        db.add(board)
        db.commit()
        identity = board.id
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE dashboards DROP COLUMN source_grants"))
    upgrade(engine)
    require_current(engine)
    assert "source_grants" in {column["name"] for column in inspect(engine).get_columns("dashboards")}
    with Session(engine) as db:
        assert db.get(Dashboard, identity).source_grants == {}
        assert db.get(Dashboard, identity).name == "Existing board"
    upgrade(engine)
    engine.dispose()
