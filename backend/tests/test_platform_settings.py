"""Settings an administrator can change without touching the server.

Everything is configured in .env, which is right for a deployment's secrets
and its database but wrong for how large an upload may be or how often
fieldwork is looked at: an office that runs the platform but not the server
could not change those without someone editing a file and restarting five
containers.

So a handful are stored instead, read through one place, and what is stored
wins over .env. These tests are about that precedence, about the settings
that cannot be reached from here, and about a change actually reaching the
thing it configures.
"""

from __future__ import annotations

import pytest

from app.core.config import settings
from app.services import preferences


@pytest.fixture(autouse=True)
def _forget_between_tests():
    """Each test reads the database rather than the last test's memory."""
    preferences.forget()
    yield
    preferences.forget()


def _settings(client, headers) -> dict[str, dict]:
    response = client.get("/api/v1/system/settings", headers=headers)
    assert response.status_code == 200, response.text
    return {entry["name"]: entry for entry in response.json()}


def test_until_somebody_changes_one_it_is_what_env_says(client, auth_headers):
    listed = _settings(client, auth_headers)

    assert listed["max_upload_mb"]["value"] == settings.max_upload_mb
    assert listed["max_upload_mb"]["default"] == settings.max_upload_mb
    assert listed["max_upload_mb"]["overridden"] is False
    assert preferences.value("max_upload_mb") == settings.max_upload_mb


def test_what_is_stored_wins_and_says_it_is_stored(client, auth_headers):
    saved = client.put(
        "/api/v1/system/settings", headers=auth_headers, json={"max_upload_mb": 512}
    )
    assert saved.status_code == 200, saved.text

    listed = {entry["name"]: entry for entry in saved.json()}
    assert listed["max_upload_mb"]["value"] == 512
    assert listed["max_upload_mb"]["default"] == settings.max_upload_mb
    assert listed["max_upload_mb"]["overridden"] is True
    # And the platform itself reads it, not just the page that set it.
    assert preferences.value("max_upload_mb") == 512

    client.delete("/api/v1/system/settings/max_upload_mb", headers=auth_headers)
    assert preferences.value("max_upload_mb") == settings.max_upload_mb


def test_a_value_the_setting_will_not_take_says_why(client, auth_headers):
    refused = client.put(
        "/api/v1/system/settings", headers=auth_headers, json={"max_upload_mb": 0}
    )
    assert refused.status_code == 422, refused.text
    assert "cannot be below 1" in refused.json()["detail"]
    assert "MB" in refused.json()["detail"], "in the unit it is asked for"

    words = client.put(
        "/api/v1/system/settings", headers=auth_headers, json={"max_upload_mb": "lots"}
    )
    assert words.status_code == 422
    assert "whole number" in words.json()["detail"]

    # And the ceiling, which is what stops a typed zero too many turning the
    # tick into something that never runs or a limit into a full disk.
    far = client.put(
        "/api/v1/system/settings",
        headers=auth_headers,
        json={"monitor_tick_minutes": 100000},
    )
    assert far.status_code == 422, far.text
    assert "cannot be above 1440" in far.json()["detail"]
    assert "minutes" in far.json()["detail"]


def test_nothing_is_saved_when_one_of_them_is_refused(client, auth_headers):
    """A page that saved four of six would leave somebody guessing which four."""
    before = preferences.value("monitor_tick_minutes")
    refused = client.put(
        "/api/v1/system/settings",
        headers=auth_headers,
        json={"monitor_tick_minutes": 30, "max_upload_mb": -5},
    )
    assert refused.status_code == 422, refused.text
    preferences.forget()
    assert preferences.value("monitor_tick_minutes") == before


def test_the_settings_that_would_lock_somebody_out_are_not_here(client, auth_headers):
    """A web page is not where a secret key or a database belongs."""
    listed = _settings(client, auth_headers)

    for unreachable in (
        "secret_key",
        "encryption_key",
        "database_url_override",
        "postgres_password",
        "redis_url",
        "storage_dir",
        "cors_origins",
    ):
        assert unreachable not in listed
        with pytest.raises(preferences.NotAllowed):
            preferences.put(None, unreachable, "anything")


def test_a_password_is_stored_encrypted_and_never_sent_back(client, auth_headers, db_session):
    from app.models import SystemSetting

    saved = client.put(
        "/api/v1/system/settings",
        headers=auth_headers,
        json={"smtp_password": "a-real-password"},
    )
    assert saved.status_code == 200, saved.text

    listed = {entry["name"]: entry for entry in saved.json()}
    # Whether there is one, not what it is.
    assert listed["smtp_password"]["value"] is True
    assert "a-real-password" not in saved.text

    db_session.expire_all()
    stored = db_session.get(SystemSetting, "smtp_password").value["value"]
    assert stored and "a-real-password" not in stored, "encrypted at rest"
    assert preferences.value("smtp_password") == "a-real-password"


def test_an_empty_password_leaves_the_one_that_is_there(client, auth_headers):
    """The page never had it to send back, so an empty box is not a change."""
    client.put(
        "/api/v1/system/settings", headers=auth_headers, json={"smtp_password": "keep-me"}
    )
    client.put(
        "/api/v1/system/settings",
        headers=auth_headers,
        json={"smtp_password": "", "smtp_host": "mail.example.org"},
    )
    assert preferences.value("smtp_password") == "keep-me"
    assert preferences.value("smtp_host") == "mail.example.org"


def test_only_an_administrator_may_look_or_change(client, auth_headers):
    from tests.conftest import sign_in

    made = client.post(
        "/api/v1/users",
        headers=auth_headers,
        json={
            "email": "settings-viewer@example.com",
            "full_name": "Viewer",
            "role": "viewer",
            "password": "viewer-password-123",
        },
    )
    assert made.status_code == 201, made.text
    viewer = sign_in(client, "settings-viewer@example.com", "viewer-password-123")

    assert client.get("/api/v1/system/settings", headers=viewer).status_code == 403
    assert (
        client.put(
            "/api/v1/system/settings", headers=viewer, json={"max_upload_mb": 1}
        ).status_code
        == 403
    )


def test_every_change_is_recorded_with_who_made_it(client, auth_headers):
    client.put(
        "/api/v1/system/settings", headers=auth_headers, json={"disclosure_threshold": 5}
    )
    log = client.get("/api/v1/system/audit?limit=20", headers=auth_headers)
    assert log.status_code == 200, log.text
    entries = [one for one in log.json()["items"] if one["action"] == "system.settings"]
    assert entries, log.text
    assert entries[0]["detail"] == {"disclosure_threshold": 5}
    assert entries[0]["user_email"]


def test_a_stored_password_is_recorded_as_the_word_set(client, auth_headers):
    """What goes in the audit log is read by everybody who can read the log."""
    client.put(
        "/api/v1/system/settings", headers=auth_headers, json={"smtp_password": "secret-one"}
    )
    log = client.get("/api/v1/system/audit?limit=20", headers=auth_headers)
    entries = [one for one in log.json()["items"] if one["action"] == "system.settings"]
    assert entries[0]["detail"] == {"smtp_password": "set"}
    assert "secret-one" not in log.text


# --- The two that beat reads ------------------------------------------------
#
# A settings page whose settings do not settle is a trap, and the refresh
# rates were the ones at risk: beat is handed its intervals once, at start-up.


def test_the_scheduler_reads_its_interval_when_it_asks(client, auth_headers):
    import datetime as dt

    from app.workers.schedules import Tunable

    every = Tunable("monitor_tick_minutes")
    assert every.run_every == dt.timedelta(minutes=settings.monitor_tick_minutes)

    saved = client.put(
        "/api/v1/system/settings", headers=auth_headers, json={"monitor_tick_minutes": 45}
    )
    assert saved.status_code == 200, saved.text
    preferences.forget()

    # The same object, without being rebuilt: this is what beat is holding.
    assert every.run_every == dt.timedelta(minutes=45)
    # And a run from an hour ago is now due, where under the old interval it
    # would have been due half an hour earlier - which is the whole point.
    assert every.is_due(dt.datetime.now(dt.UTC) - dt.timedelta(hours=1)).is_due


def test_beat_is_holding_the_tunable_ones():
    """Wired, not merely written: the schedule has to be the one that re-reads."""
    from app.workers.celery_app import celery_app
    from app.workers.schedules import Tunable

    schedule = celery_app.conf.beat_schedule
    assert isinstance(schedule["check-due-connection-syncs"]["schedule"], Tunable)
    assert isinstance(schedule["refresh-indicators-and-alerts"]["schedule"], Tunable)
    # Beat sleeps until the next run is due, so how soon a shortened interval
    # is noticed is this, and nothing else.
    assert celery_app.conf.beat_max_loop_interval == 60


def test_a_schedule_survives_being_written_to_disk_and_read_back():
    """Beat keeps its schedule in a file between runs."""
    import pickle

    from app.workers.schedules import Tunable

    back = pickle.loads(pickle.dumps(Tunable("sync_tick_minutes")))
    assert isinstance(back, Tunable)
    assert back.name == "sync_tick_minutes"
    assert back == Tunable("sync_tick_minutes")


def test_an_unreadable_setting_does_not_stop_the_scheduler(monkeypatch):
    """A schedule that raised would take beat down with it."""
    import datetime as dt

    from app.workers.schedules import Tunable

    def unreadable(name):
        raise RuntimeError("the database is not there")

    monkeypatch.setattr(preferences, "value", unreadable)
    assert Tunable("monitor_tick_minutes").run_every == dt.timedelta(minutes=15)


def test_a_server_that_cannot_encrypt_says_so_rather_than_erroring(client, auth_headers, monkeypatch):
    """A password is the one setting that needs a key to store at all."""
    from app.services import preferences as service

    # Starting from nothing stored, so this is about what the refusal leaves
    # behind rather than about what some earlier test put there.
    client.delete("/api/v1/system/settings/smtp_password", headers=auth_headers)

    def no_key(_: str) -> str:
        raise RuntimeError(
            "ENCRYPTION_KEY is not a valid Fernet key. Generate one with: "
            "python -m app.cli gen-encryption-key"
        )

    monkeypatch.setattr("app.core.crypto.encrypt", no_key)

    refused = client.put(
        "/api/v1/system/settings",
        headers=auth_headers,
        json={"smtp_password": "cannot-be-kept"},
    )
    assert refused.status_code == 422, refused.text
    assert "gen-encryption-key" in refused.json()["detail"], "and what to run"
    assert service.value("smtp_password") == ""
