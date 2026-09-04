"""Settings must survive the values docker-compose actually passes.

A plain "CORS_ORIGINS=http://host:8080" once crashed the API at start-up with
SettingsError, because pydantic-settings JSON-decodes environment values for
list-typed fields before any validator runs. Nothing caught it: local runs never
set the variable, and CI built the images without running them. nginx answered
502 on every request.
"""

from __future__ import annotations

import os
from contextlib import contextmanager

import pytest

from app.core.config import Settings


@contextmanager
def env(**values: str):
    previous = {key: os.environ.get(key) for key in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def test_single_origin_from_environment():
    with env(CORS_ORIGINS="http://localhost:8083"):
        assert Settings().cors_origin_list == ["http://localhost:8083"]


def test_comma_separated_origins():
    with env(CORS_ORIGINS="https://a.example, https://b.example"):
        assert Settings().cors_origin_list == ["https://a.example", "https://b.example"]


def test_json_array_form_still_accepted():
    """The workaround people applied while the plain form was broken."""
    with env(CORS_ORIGINS='["http://localhost:8083", "https://b.example"]'):
        assert Settings().cors_origin_list == ["http://localhost:8083", "https://b.example"]


def test_empty_origins():
    with env(CORS_ORIGINS=""):
        assert Settings().cors_origin_list == []


def test_default_when_unset():
    saved = os.environ.pop("CORS_ORIGINS", None)
    try:
        assert Settings().cors_origin_list == ["http://localhost:5173"]
    finally:
        if saved is not None:
            os.environ["CORS_ORIGINS"] = saved


@pytest.mark.parametrize(
    "variable,value",
    [
        ("PUBLIC_URL", "http://example.org:8083"),
        ("SMTP_FROM", "susoDash <no-reply@example.org>"),
        ("STORAGE_DIR", "/data"),
        ("MAX_UPLOAD_MB", "512"),
        ("SYNC_TICK_MINUTES", "5"),
    ],
)
def test_plain_environment_values_do_not_break_settings(variable: str, value: str):
    """Every value docker-compose passes must construct without raising."""
    with env(**{variable: value}):
        Settings()


def test_app_imports_with_a_compose_style_environment():
    """The whole failure was at import time, so import the app with that env."""
    with env(
        CORS_ORIGINS="http://localhost:8083",
        PUBLIC_URL="http://localhost:8083",
        SECRET_KEY="not-a-real-key",
        STORAGE_DIR="/tmp/surveyhq-config-test",
    ):
        from app.main import app

        assert app.title
