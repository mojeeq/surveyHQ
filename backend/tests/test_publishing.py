"""Publishing a dashboard to GitHub Pages, or to a web server over SFTP or FTP.

The board that goes online is the HTML export - its filters working, the
numbers behind each widget and none of the rows - so this platform can sit on
an office network while the board is read on a public website. What is pinned
here is the part that is easy to get wrong and expensive when it is: what
lands where, that it stays current, that it comes down when it should, and
that nothing this platform did not write is ever overwritten or deleted.
"""

from __future__ import annotations

import io

import pandas as pd
import paramiko
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from sqlalchemy import select

from app.models import Publication, PublishTarget
from tests.publishing_servers import (
    FTP_PASSWORD,
    FTP_USER,
    GOOD_TOKEN,
    SFTP_PASSWORD,
    SFTP_USER,
    FakeGitHub,
    FtpServer,
    SftpServer,
    mock_github,
)
from tests.test_api_analytics import _stata_bytes, _zip_bytes

MARKER = b'<meta name="generator" content="SurveyHQ">'

FIRST = pd.DataFrame(
    {"hhid": [1.0, 2.0, 3.0], "province": ["Northern", "Highland", "Southern"]}
)
SECOND = pd.DataFrame(
    {"hhid": [1.0, 2.0, 3.0, 4.0], "province": ["Northern", "Highland", "Southern", "Western"]}
)


def archive(frame: pd.DataFrame) -> bytes:
    return _zip_bytes({"households.dta": _stata_bytes(frame)})


@pytest.fixture
def board(client, auth_headers, request) -> dict:
    """A project with an export in it and a board counting households by province."""
    name = request.node.name[:40]
    project = client.post(
        "/api/v1/projects", headers=auth_headers, json={"name": f"Pub {name}"}
    ).json()
    uploaded = client.post(
        "/api/v1/datasets/upload",
        headers=auth_headers,
        files={"file": ("export.zip", archive(FIRST), "application/zip")},
        data={"project_id": project["id"]},
    )
    assert uploaded.status_code == 201, uploaded.text
    dataset_id = uploaded.json()["datasets"][0]["id"]
    chart = client.post(
        "/api/v1/dashboards/charts",
        headers=auth_headers,
        json={
            "name": "Households by province",
            "dataset_id": dataset_id,
            "chart_type": "bar",
            "spec": {
                "query": {
                    "dimensions": [{"variable": "province"}],
                    "measures": [{"agg": "count", "alias": "Households"}],
                }
            },
        },
    ).json()
    dashboard = client.post(
        "/api/v1/dashboards",
        headers=auth_headers,
        json={"name": f"Census {name}", "project_id": project["id"]},
    ).json()
    added = client.post(
        f"/api/v1/dashboards/{dashboard['id']}/widgets",
        headers=auth_headers,
        json={"title": "Households", "widget_type": "chart", "chart_id": chart["id"]},
    )
    assert added.status_code == 201, added.text
    return {"id": dashboard["id"], "name": dashboard["name"], "project_id": project["id"]}


def make_target(client, auth_headers, kind: str, settings: dict, **secret) -> dict:
    response = client.post(
        "/api/v1/publishing/targets",
        headers=auth_headers,
        json={"name": f"{kind} site", "kind": kind, "settings": settings, **secret},
    )
    assert response.status_code == 201, response.text
    return response.json()


def publish(client, auth_headers, board: dict, target: dict, **body):
    return client.post(
        f"/api/v1/dashboards/{board['id']}/publications",
        headers=auth_headers,
        json={"target_id": target["id"], **body},
    )


@pytest.fixture
def github():
    fake = FakeGitHub()
    with mock_github(fake):
        yield fake


@pytest.fixture
def github_target(client, auth_headers, github, request) -> dict:
    settings = {"owner": github.owner, "repo": github.repo}
    settings.update(getattr(request, "param", {}))
    return make_target(client, auth_headers, "github", settings, token=GOOD_TOKEN)


# --- GitHub Pages ---------------------------------------------------------------


def test_a_board_is_committed_to_the_pages_branch_and_pages_switched_on(
    client, auth_headers, board, github, github_target
):
    published = publish(client, auth_headers, board, github_target, path="census")
    assert published.status_code == 201, published.text
    body = published.json()
    assert body["status"] == "published"
    assert body["url"] == "https://statsoffice.github.io/dashboards/census/"
    assert any("switched on" in note for note in body["notes"])

    files = github.files("gh-pages")
    page = files["census/index.html"]
    assert MARKER in page and b"Households" in page
    # The branch was new, so it was started without Jekyll; main is untouched.
    assert ".nojekyll" in files
    assert set(github.files("main")) == {"README.md"}
    assert github.pages["source"] == {"branch": "gh-pages", "path": "/"}


def test_the_page_carries_the_numbers_not_the_rows(client, auth_headers, board, github, github_target):
    """What goes online is the export: counts by province, never a household."""
    publish(client, auth_headers, board, github_target, path="census")
    page = github.files()["census/index.html"]
    assert b"Southern" in page
    assert b"hhid" not in page


def test_republishing_brings_the_copy_up_to_date(
    client, auth_headers, board, github, github_target
):
    first = publish(client, auth_headers, board, github_target, path="census").json()
    widget = client.get(f"/api/v1/dashboards/{board['id']}", headers=auth_headers).json()[
        "widgets"
    ][0]
    client.patch(
        f"/api/v1/dashboards/{board['id']}/widgets/{widget['id']}",
        headers=auth_headers,
        json={"title": "Homes counted"},
    )
    again = client.post(
        f"/api/v1/dashboards/{board['id']}/publications/{first['id']}/publish",
        headers=auth_headers,
        json={},
    )
    assert again.status_code == 200, again.text
    assert b"Homes counted" in github.files()["census/index.html"]


def test_an_address_left_out_is_the_boards_name(client, auth_headers, board, github, github_target):
    body = publish(client, auth_headers, board, github_target).json()
    assert body["path"].startswith("census-test-an-address")
    assert f"{body['path']}/index.html" in github.files()


@pytest.mark.parametrize("github_target", [{"folder": "stats"}], indirect=True)
def test_a_folder_on_the_destination_holds_every_page(
    client, auth_headers, board, github, github_target
):
    body = publish(client, auth_headers, board, github_target, path="census").json()
    assert "stats/census/index.html" in github.files()
    assert body["url"] == "https://statsoffice.github.io/dashboards/stats/census/"


@pytest.mark.parametrize("github_target", [{"contents_page": True}], indirect=True)
def test_the_front_page_lists_what_is_published(
    client, auth_headers, board, github, github_target
):
    one = publish(client, auth_headers, board, github_target, path="census").json()
    publish(client, auth_headers, board, github_target, path="census-again")
    front = github.files()["index.html"]
    assert MARKER in front
    assert b'href="./census/"' in front and b'href="./census-again/"' in front

    gone = client.delete(
        f"/api/v1/dashboards/{board['id']}/publications/{one['id']}", headers=auth_headers
    )
    assert gone.status_code == 200, gone.text
    files = github.files()
    assert "census/index.html" not in files
    assert b'href="./census/"' not in files["index.html"]
    assert b'href="./census-again/"' in files["index.html"]


def test_a_page_this_platform_did_not_write_is_not_overwritten(
    client, auth_headers, board, github, github_target
):
    """The ministry's own page at that address, say. Replacing it takes a yes."""
    github.put_file("gh-pages", "census/index.html", b"<html>The ministry's own page</html>")
    refused = publish(client, auth_headers, board, github_target, path="census")
    assert refused.status_code == 409
    assert "did not put there" in refused.json()["detail"]
    assert github.files()["census/index.html"] == b"<html>The ministry's own page</html>"
    # Nothing was kept from the refusal.
    assert client.get(
        f"/api/v1/dashboards/{board['id']}/publications", headers=auth_headers
    ).json() == []

    replaced = publish(client, auth_headers, board, github_target, path="census", replace_existing=True)
    assert replaced.status_code == 201, replaced.text
    assert MARKER in github.files()["census/index.html"]


def test_unpublishing_leaves_a_page_it_did_not_write(
    client, auth_headers, board, github, github_target
):
    body = publish(client, auth_headers, board, github_target, path="census").json()
    github.put_file("gh-pages", "census/index.html", b"<html>Somebody replaced it</html>")
    gone = client.delete(
        f"/api/v1/dashboards/{board['id']}/publications/{body['id']}", headers=auth_headers
    )
    assert gone.status_code == 200, gone.text
    assert "left there" in gone.json()["detail"]
    assert github.files()["census/index.html"] == b"<html>Somebody replaced it</html>"


def test_two_boards_cannot_take_one_address(client, auth_headers, board, github, github_target):
    publish(client, auth_headers, board, github_target, path="census")
    again = publish(client, auth_headers, board, github_target, path="census")
    assert again.status_code == 409
    assert "already published" in again.json()["detail"]


def test_an_empty_repository_is_started(client, auth_headers, board):
    fake = FakeGitHub(empty=True)
    with mock_github(fake):
        target = make_target(
            client, auth_headers, "github", {"owner": fake.owner, "repo": fake.repo},
            token=GOOD_TOKEN,
        )
        published = publish(client, auth_headers, board, target, path="census")
    assert published.status_code == 201, published.text
    assert "census/index.html" in fake.files("gh-pages")


def test_a_bad_or_read_only_token_is_said_plainly(client, auth_headers, github):
    wrong = make_target(
        client, auth_headers, "github", {"owner": github.owner, "repo": github.repo},
        token="not-the-token",
    )
    tested = client.post(f"/api/v1/publishing/targets/{wrong['id']}/test", headers=auth_headers)
    assert tested.status_code == 422
    assert "refused the token" in tested.json()["detail"]

    github.can_push = False
    reader = make_target(
        client, auth_headers, "github", {"owner": github.owner, "repo": github.repo},
        token=GOOD_TOKEN,
    )
    tested = client.post(f"/api/v1/publishing/targets/{reader['id']}/test", headers=auth_headers)
    assert tested.status_code == 422
    assert "Contents: Read and write" in tested.json()["detail"]


def test_testing_a_token_that_may_only_read_says_so_before_publishing(client, auth_headers):
    """GitHub gives the account's permissions with the repository, not the
    token's, so a read-only fine-grained token passed its test and was refused
    at the first publish. The test now writes."""
    fake = FakeGitHub(token_can_write=False)
    with mock_github(fake):
        target = make_target(
            client, auth_headers, "github", {"owner": fake.owner, "repo": fake.repo},
            token=GOOD_TOKEN,
        )
        tested = client.post(f"/api/v1/publishing/targets/{target['id']}/test",
                             headers=auth_headers)
    assert tested.status_code == 422
    detail = tested.json()["detail"]
    assert "Contents: Read and write" in detail
    assert "Repository access" in detail
    assert fake.files("main") == {"README.md": b"# Dashboards\n"}


def test_testing_an_empty_repository_starts_it(client, auth_headers):
    fake = FakeGitHub(empty=True)
    with mock_github(fake):
        target = make_target(
            client, auth_headers, "github", {"owner": fake.owner, "repo": fake.repo},
            token=GOOD_TOKEN,
        )
        tested = client.post(f"/api/v1/publishing/targets/{target['id']}/test",
                             headers=auth_headers)
    assert tested.status_code == 200, tested.text
    assert fake.files("gh-pages") == {".nojekyll": b""}
    assert any("was empty" in note for note in tested.json()["notes"])


def test_an_empty_repository_the_token_may_not_write_to_blames_the_token(
    client, auth_headers, board
):
    """The fault reported: told to add a README when the token was the trouble."""
    fake = FakeGitHub(empty=True, token_can_write=False)
    with mock_github(fake):
        target = make_target(
            client, auth_headers, "github", {"owner": fake.owner, "repo": fake.repo},
            token=GOOD_TOKEN,
        )
        published = publish(client, auth_headers, board, target, path="census")
    assert published.status_code == 422
    detail = published.json()["detail"]
    assert "Contents: Read and write" in detail
    assert "README" not in detail
    # Not tried again on the default branch: the token would be refused there too.
    assert fake.calls.count(f"PUT /repos/{fake.owner}/{fake.repo}/contents/.nojekyll") == 1


def test_pages_that_cannot_be_switched_on_is_a_note_not_a_failure(
    client, auth_headers, board
):
    fake = FakeGitHub(can_enable_pages=False)
    with mock_github(fake):
        target = make_target(
            client, auth_headers, "github", {"owner": fake.owner, "repo": fake.repo},
            token=GOOD_TOKEN,
        )
        published = publish(client, auth_headers, board, target, path="census")
    assert published.status_code == 201, published.text
    assert any("Settings, Pages" in note for note in published.json()["notes"])


def test_a_token_that_may_not_see_pages_is_not_told_pages_is_off(client, auth_headers, board):
    """GitHub refuses the question rather than answering "off", and Pages may
    be serving the site perfectly well."""
    fake = FakeGitHub(can_read_pages=False)
    fake.pages = {"html_url": "https://statsoffice.github.io/dashboards/", "source": {"branch": "gh-pages"}}
    with mock_github(fake):
        target = make_target(
            client, auth_headers, "github", {"owner": fake.owner, "repo": fake.repo},
            token=GOOD_TOKEN,
        )
        published = publish(client, auth_headers, board, target, path="census")
    assert published.status_code == 201, published.text
    notes = " ".join(published.json()["notes"])
    assert "could not be checked" in notes
    assert "not on" not in notes and "switched on for this" not in notes
    assert not any(call == "POST /repos/statsoffice/dashboards/pages" for call in fake.calls)


@pytest.mark.parametrize("github_target", [{"contents_page": True}], indirect=True)
def test_a_board_whose_republish_failed_stays_on_the_front_page(
    client, auth_headers, board, github, github_target
):
    """Its last good copy is still online, so it is still listed."""
    first = publish(client, auth_headers, board, github_target, path="census").json()
    github.can_push = False
    failed = client.post(
        f"/api/v1/dashboards/{board['id']}/publications/{first['id']}/publish",
        headers=auth_headers,
        json={},
    )
    assert failed.status_code == 422, failed.text
    github.can_push = True
    publish(client, auth_headers, board, github_target, path="another")
    front = github.files()["index.html"]
    assert b'href="./census/"' in front and b'href="./another/"' in front


@pytest.mark.parametrize("github_target", [{"contents_page": True}], indirect=True)
def test_deleting_a_board_published_twice_clears_both_from_the_front_page(
    client, auth_headers, board, github, github_target
):
    publish(client, auth_headers, board, github_target, path="census")
    publish(client, auth_headers, board, github_target, path="census-copy")
    client.delete(f"/api/v1/dashboards/{board['id']}", headers=auth_headers)
    files = github.files()
    assert "census/index.html" not in files and "census-copy/index.html" not in files
    assert b"href=" not in files["index.html"]


def test_the_token_never_comes_back_out(client, auth_headers, github, github_target):
    listed = client.get("/api/v1/publishing/targets", headers=auth_headers)
    assert GOOD_TOKEN not in listed.text
    mine = next(one for one in listed.json() if one["id"] == github_target["id"])
    assert mine["secrets"] == ["token"]
    assert mine["folder_url"] == "https://statsoffice.github.io/dashboards/"


def test_a_destination_with_pages_on_it_cannot_be_deleted(
    client, auth_headers, board, github, github_target
):
    publish(client, auth_headers, board, github_target, path="census")
    refused = client.delete(
        f"/api/v1/publishing/targets/{github_target['id']}", headers=auth_headers
    )
    assert refused.status_code == 409
    assert "Unpublish" in refused.json()["detail"]


def test_deleting_the_board_takes_its_page_down(
    client, auth_headers, board, github, github_target
):
    publish(client, auth_headers, board, github_target, path="census")
    gone = client.delete(f"/api/v1/dashboards/{board['id']}", headers=auth_headers)
    assert gone.status_code == 200, gone.text
    assert "census/index.html" not in github.files()


@pytest.mark.parametrize("path", ["../escape", "with space", "ünïcode", "a/./b"])
def test_an_address_is_a_plain_folder_name(client, auth_headers, board, github, github_target, path):
    refused = publish(client, auth_headers, board, github_target, path=path)
    assert refused.status_code == 422, refused.text


def test_only_an_administrator_sets_up_a_destination(client, auth_headers, db_session):
    from app.core.security import hash_password
    from app.models import Role, User

    db_session.add(
        User(
            email="publisher@example.org",
            username="publisher",
            full_name="Publishes Boards",
            hashed_password=hash_password("Fieldwork-2026-publish"),
            role=Role.manager,
        )
    )
    db_session.commit()
    token = client.post(
        "/api/v1/auth/login",
        json={"email": "publisher@example.org", "password": "Fieldwork-2026-publish"},
    ).json()["access_token"]
    refused = client.post(
        "/api/v1/publishing/targets",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "Mine", "kind": "github", "settings": {"owner": "a", "repo": "b"}},
    )
    assert refused.status_code == 403


# --- following the data ---------------------------------------------------------


def test_a_new_export_republishes_a_board_set_to_follow_the_data(
    client, auth_headers, board, github, github_target, db_session
):
    published = publish(
        client, auth_headers, board, github_target, path="census", auto_republish=True
    )
    assert published.status_code == 201, published.text
    assert b"Western" not in github.files()["census/index.html"]

    again = client.post(
        "/api/v1/datasets/upload",
        headers=auth_headers,
        files={"file": ("export.zip", archive(SECOND), "application/zip")},
        data={"project_id": board["project_id"], "mode": "replace"},
    )
    assert again.status_code == 201, again.text
    assert b"Western" in github.files()["census/index.html"]
    assert any("Republished online" in line for line in again.json().get("warnings", [])), again.json()


def test_a_board_not_set_to_follow_is_left_as_published(
    client, auth_headers, board, github, github_target
):
    publish(client, auth_headers, board, github_target, path="census")
    client.post(
        "/api/v1/datasets/upload",
        headers=auth_headers,
        files={"file": ("export.zip", archive(SECOND), "application/zip")},
        data={"project_id": board["project_id"], "mode": "replace"},
    )
    assert b"Western" not in github.files()["census/index.html"]


def test_a_republish_that_fails_is_a_note_on_the_import(
    client, auth_headers, board, github, github_target, db_session
):
    published = publish(
        client, auth_headers, board, github_target, path="census", auto_republish=True
    ).json()
    github.can_push = False
    again = client.post(
        "/api/v1/datasets/upload",
        headers=auth_headers,
        files={"file": ("export.zip", archive(SECOND), "application/zip")},
        data={"project_id": board["project_id"], "mode": "replace"},
    )
    assert again.status_code == 201, again.text
    assert any(
        "could not be republished" in line for line in again.json().get("warnings", [])
    ), again.json()
    listed = client.get(
        f"/api/v1/dashboards/{board['id']}/publications", headers=auth_headers
    ).json()
    mine = next(one for one in listed if one["id"] == published["id"])
    assert mine["status"] == "failed" and mine["last_error"]


# --- SFTP -----------------------------------------------------------------------


@pytest.fixture
def sftp(tmp_path):
    server = SftpServer(tmp_path)
    yield server
    server.stop()


def sftp_target(client, auth_headers, server: SftpServer, **extra) -> dict:
    return make_target(
        client,
        auth_headers,
        "sftp",
        {
            "host": "127.0.0.1",
            "port": server.port,
            "username": SFTP_USER,
            "folder": "www/dashboards",
            "site_url": "https://stats.example.org/dashboards",
            **extra.pop("settings", {}),
        },
        **({"password": SFTP_PASSWORD} | extra),
    )


def test_sftp_trusts_the_server_at_its_test_and_publishes_into_the_folder(
    client, auth_headers, board, sftp, tmp_path
):
    target = sftp_target(client, auth_headers, sftp)
    early = publish(client, auth_headers, board, target, path="census")
    assert early.status_code == 422
    assert "Test this destination first" in early.json()["detail"]

    tested = client.post(f"/api/v1/publishing/targets/{target['id']}/test", headers=auth_headers)
    assert tested.status_code == 200, tested.text
    assert tested.json()["host_key_fingerprint"].startswith("SHA256:")
    assert not (tmp_path / "www/dashboards/.surveyhq-check").exists()

    published = publish(client, auth_headers, board, target, path="census")
    assert published.status_code == 201, published.text
    assert published.json()["url"] == "https://stats.example.org/dashboards/census/"
    page = tmp_path / "www/dashboards/census/index.html"
    assert MARKER in page.read_bytes()
    assert not list(tmp_path.rglob("*.surveyhq-upload"))

    gone = client.delete(
        f"/api/v1/dashboards/{board['id']}/publications/{published.json()['id']}",
        headers=auth_headers,
    )
    assert gone.status_code == 200, gone.text
    assert not page.exists() and not page.parent.exists()


def test_sftp_refuses_a_server_whose_key_has_changed(
    client, auth_headers, board, sftp, db_session
):
    target = sftp_target(client, auth_headers, sftp)
    client.post(f"/api/v1/publishing/targets/{target['id']}/test", headers=auth_headers)
    row = db_session.get(PublishTarget, target["id"])
    row.settings = {**row.settings, "host_key": f"ssh-ed25519 {'A' * 68}"}
    db_session.commit()

    refused = publish(client, auth_headers, board, target, path="census")
    assert refused.status_code == 422
    assert "not the one that was trusted" in refused.json()["detail"]

    # Forgetting the key and testing again trusts the server as it is now.
    client.patch(
        f"/api/v1/publishing/targets/{target['id']}",
        headers=auth_headers,
        json={"forget_host_key": True},
    )
    assert client.post(
        f"/api/v1/publishing/targets/{target['id']}/test", headers=auth_headers
    ).status_code == 200
    assert publish(client, auth_headers, board, target, path="census").status_code == 201


def test_sftp_signs_in_with_a_key(client, auth_headers, board, tmp_path):
    private = ed25519.Ed25519PrivateKey.generate().private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.OpenSSH,
        serialization.NoEncryption(),
    ).decode()
    server = SftpServer(tmp_path, client_key=paramiko.Ed25519Key.from_private_key(io.StringIO(private)))
    try:
        target = make_target(
            client,
            auth_headers,
            "sftp",
            {"host": "127.0.0.1", "port": server.port, "username": SFTP_USER, "auth": "key"},
            private_key=private,
        )
        assert client.post(
            f"/api/v1/publishing/targets/{target['id']}/test", headers=auth_headers
        ).status_code == 200
        assert publish(client, auth_headers, board, target, path="census").status_code == 201
        assert (tmp_path / "census/index.html").exists()
    finally:
        server.stop()


def test_sftp_says_when_the_password_is_wrong(client, auth_headers, sftp):
    target = sftp_target(client, auth_headers, sftp, password="wrong")
    tested = client.post(f"/api/v1/publishing/targets/{target['id']}/test", headers=auth_headers)
    assert tested.status_code == 422
    assert "refused the user name and password" in tested.json()["detail"]


# --- FTP ------------------------------------------------------------------------


@pytest.fixture
def ftp(tmp_path):
    server = FtpServer(tmp_path)
    yield server
    server.stop()


def ftp_target(client, auth_headers, server: FtpServer, **settings) -> dict:
    return make_target(
        client,
        auth_headers,
        "ftp",
        {
            "host": "127.0.0.1",
            "port": server.port,
            "username": FTP_USER,
            "folder": "public_html/dashboards",
            "site_url": "https://ministry.example.org/dashboards/",
            "tls": False,
            **settings,
        },
        password=FTP_PASSWORD,
    )


def test_ftp_publishes_republishes_and_takes_down(client, auth_headers, board, ftp, tmp_path):
    target = ftp_target(client, auth_headers, ftp)
    tested = client.post(f"/api/v1/publishing/targets/{target['id']}/test", headers=auth_headers)
    assert tested.status_code == 200, tested.text
    assert any("plain FTP" in note for note in tested.json()["notes"])

    published = publish(client, auth_headers, board, target, path="census")
    assert published.status_code == 201, published.text
    page = tmp_path / "public_html/dashboards/census/index.html"
    assert MARKER in page.read_bytes()
    again = client.post(
        f"/api/v1/dashboards/{board['id']}/publications/{published.json()['id']}/publish",
        headers=auth_headers,
        json={},
    )
    assert again.status_code == 200, again.text
    assert not list(tmp_path.rglob("*.surveyhq-upload"))

    client.delete(
        f"/api/v1/dashboards/{board['id']}/publications/{published.json()['id']}",
        headers=auth_headers,
    )
    assert not page.exists()


def test_ftp_will_not_overwrite_a_page_it_did_not_write(client, auth_headers, board, ftp, tmp_path):
    folder = tmp_path / "public_html/dashboards/census"
    folder.mkdir(parents=True)
    (folder / "index.html").write_bytes(b"<html>" + b"x" * 20000 + b"</html>")
    target = ftp_target(client, auth_headers, ftp)
    refused = publish(client, auth_headers, board, target, path="census")
    assert refused.status_code == 409, refused.text
    assert (folder / "index.html").read_bytes().startswith(b"<html>xxx")


def test_ftp_asked_to_encrypt_against_a_plain_server_says_so(client, auth_headers, ftp):
    target = ftp_target(client, auth_headers, ftp, tls=True)
    tested = client.post(f"/api/v1/publishing/targets/{target['id']}/test", headers=auth_headers)
    assert tested.status_code in (422, 502), tested.text
    assert "encrypted" in tested.json()["detail"] or "refused" in tested.json()["detail"]


def test_publications_are_listed_with_where_they_are(
    client, auth_headers, board, github, github_target, db_session
):
    publish(client, auth_headers, board, github_target, path="census", auto_republish=True)
    listed = client.get(
        f"/api/v1/dashboards/{board['id']}/publications", headers=auth_headers
    ).json()
    assert [(one["target_name"], one["path"], one["auto_republish"]) for one in listed] == [
        ("github site", "census", True)
    ]
    rows = db_session.scalars(select(Publication).where(Publication.dashboard_id == board["id"])).all()
    assert len(rows) == 1 and rows[0].size_bytes > 0
