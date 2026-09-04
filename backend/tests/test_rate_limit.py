"""Limits on how fast the two unauthenticated surfaces may be used.

Rate limiting is off for the rest of the suite - a hundred sign-ins would
otherwise start refusing themselves - so these tests turn it on around
themselves, and clear the counters afterwards so nothing they spend leaks into
another test.
"""

from __future__ import annotations

import pytest

from app.api.v1.endpoints.auth import LOGIN_ATTEMPTS_PER_ACCOUNT, LOGIN_ATTEMPTS_PER_IP
from app.core import rate_limit
from app.core.config import settings


@pytest.fixture
def limiting():
    """Enforce limits for one test, per process, starting from zero."""
    rate_limit.reset()
    settings.rate_limit_enabled = True
    # The suite has no Redis, and probing for one costs a connection timeout.
    rate_limit._redis_checked = True
    rate_limit._redis_client = None
    try:
        yield
    finally:
        settings.rate_limit_enabled = False
        rate_limit.reset()


def _attempt(client, email: str = "nobody@example.com"):
    return client.post(
        "/api/v1/auth/login", json={"email": email, "password": "wrong-password"}
    )


def test_guessing_one_account_is_cut_off(client, limiting):
    for _ in range(LOGIN_ATTEMPTS_PER_ACCOUNT):
        assert _attempt(client).status_code == 401

    refused = _attempt(client)
    assert refused.status_code == 429
    assert refused.headers["Retry-After"] == "60"


def test_spreading_guesses_over_accounts_is_cut_off_too(client, limiting):
    """The per-address limit catches what the per-account one cannot.

    A different email each time never trips the account counter, which is
    exactly how a list of stolen addresses gets tried.
    """
    seen = []
    for index in range(LOGIN_ATTEMPTS_PER_IP + 1):
        seen.append(_attempt(client, f"person{index}@example.com").status_code)

    assert seen[:LOGIN_ATTEMPTS_PER_IP] == [401] * LOGIN_ATTEMPTS_PER_IP
    assert seen[-1] == 429


def test_a_correct_password_still_works_below_the_limit(client, limiting):
    from tests.conftest import ADMIN_EMAIL, ADMIN_PASSWORD

    response = client.post(
        "/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}
    )
    assert response.status_code == 200


def test_a_refused_attempt_does_not_reveal_whether_the_account_exists(
    client, limiting
):
    """The 429 must arrive for a real address and an invented one alike.

    A limiter that only counted real accounts would answer the question the
    401 was written to avoid answering.
    """
    from tests.conftest import ADMIN_EMAIL

    for _ in range(LOGIN_ATTEMPTS_PER_ACCOUNT):
        _attempt(client, ADMIN_EMAIL)
    real = _attempt(client, ADMIN_EMAIL)

    rate_limit.reset()
    for _ in range(LOGIN_ATTEMPTS_PER_ACCOUNT):
        _attempt(client, "invented@example.com")
    invented = _attempt(client, "invented@example.com")

    assert real.status_code == invented.status_code == 429
    assert real.json()["detail"] == invented.json()["detail"]


def test_a_public_dashboard_cannot_be_hammered(client, limiting):
    """Every route under /public shares one budget per address."""
    from app.api.v1.endpoints.public import PUBLIC_REQUESTS_PER_MINUTE

    codes = set()
    for _ in range(PUBLIC_REQUESTS_PER_MINUTE):
        codes.add(client.get("/api/v1/public/dashboards/no-such-token").status_code)
    assert codes == {404}  # counted, but answered normally

    assert client.get("/api/v1/public/dashboards/no-such-token").status_code == 429


def test_limits_are_off_unless_configured(client):
    """The suite's own default, asserted so it cannot drift silently."""
    assert settings.rate_limit_enabled is False
    for _ in range(LOGIN_ATTEMPTS_PER_ACCOUNT + 5):
        assert _attempt(client).status_code == 401
