from __future__ import annotations

import ssl

from app.services import mailer


def test_starttls_uses_a_verified_tls_context(monkeypatch):
    captured: dict[str, object] = {}

    class FakeSMTP:
        def __init__(self, host: str, port: int, timeout: int):
            captured["host"] = host
            captured["port"] = port
            captured["timeout"] = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def starttls(self, context: ssl.SSLContext):
            captured["context"] = context

        def login(self, user: str, password: str):
            captured["login"] = (user, password)

        def send_message(self, message):
            captured["message"] = message

    monkeypatch.setattr(mailer.smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(mailer.settings, "smtp_host", "smtp.example.org")
    monkeypatch.setattr(mailer.settings, "smtp_port", 587)
    monkeypatch.setattr(mailer.settings, "smtp_tls", True)
    monkeypatch.setattr(mailer.settings, "smtp_user", "alerts")
    monkeypatch.setattr(mailer.settings, "smtp_password", "secret")
    monkeypatch.setattr(mailer.settings, "smtp_from", "susoDash <no-reply@example.org>")

    sent = mailer.send_email(["ops@example.org"], "Alert", "Body")

    assert sent is True
    context = captured["context"]
    assert isinstance(context, ssl.SSLContext)
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True
