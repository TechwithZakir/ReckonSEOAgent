import smtplib
from email.message import EmailMessage

import pytest
from pydantic import SecretStr

from reckon_api.config import Settings
from reckon_api.native_mail import EmailDeliveryUnavailable, SmtpVerificationMailer


def test_smtp_verification_requires_tls_and_does_not_send_token_in_url_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: list[EmailMessage] = []
    events: list[str] = []

    class FakeSmtp:
        def __init__(self, host: str, port: int, timeout: int) -> None:
            assert (host, port, timeout) == ("smtp.example.com", 587, 10)

        def __enter__(self) -> "FakeSmtp":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def starttls(self, *, context: object) -> None:
            events.append("tls")

        def login(self, username: str, password: str) -> None:
            assert events == ["tls"]
            events.append("login")

        def send_message(self, message: EmailMessage) -> None:
            assert events == ["tls", "login"]
            sent.append(message)

    monkeypatch.setattr(smtplib, "SMTP", FakeSmtp)
    settings = Settings(
        _env_file=None, environment="test", smtp_host="smtp.example.com",
        smtp_from="sender@example.com", smtp_username="test-user",
        smtp_password=SecretStr("fixture"), web_public_origin="http://127.0.0.1:5173",
    )
    SmtpVerificationMailer(settings).send_verification("user@example.com", "fixture-token")
    assert len(sent) == 1
    content = sent[0].get_content()
    assert "/auth/verify#token=fixture-token" in content
    assert "/auth/verify?token=" not in content


def test_smtp_failure_does_not_expose_provider_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(host: str, port: int, timeout: int) -> None:
        raise OSError("sensitive provider error")

    monkeypatch.setattr(smtplib, "SMTP", fail)
    settings = Settings(
        _env_file=None, environment="test", smtp_host="smtp.example.com",
        smtp_from="sender@example.com", web_public_origin="http://127.0.0.1:5173",
    )
    with pytest.raises(EmailDeliveryUnavailable, match="Verification email could not be sent"):
        SmtpVerificationMailer(settings).send_verification("user@example.com", "fixture-token")


def test_recovery_email_places_token_in_fragment(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(
        _env_file=None, environment="test", smtp_host="smtp.example.com",
        smtp_from="sender@example.com", web_public_origin="http://127.0.0.1:5173",
    )
    mailer = SmtpVerificationMailer(settings)
    sent: list[EmailMessage] = []
    monkeypatch.setattr(mailer, "_send", sent.append)
    mailer.send_password_reset("user@example.com", "fixture-token")
    assert "/auth/reset#token=fixture-token" in sent[0].get_content()


def test_invitation_email_links_to_in_app_review(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(
        _env_file=None, environment="test", smtp_host="smtp.example.com",
        smtp_from="sender@example.com", web_public_origin="http://127.0.0.1:5173",
    )
    mailer = SmtpVerificationMailer(settings)
    sent: list[EmailMessage] = []
    monkeypatch.setattr(mailer, "_send", sent.append)
    mailer.send_organization_invitation("member@example.com", "Fixture org")
    assert sent[0]["To"] == "member@example.com"
    assert "http://127.0.0.1:5173/invitations" in sent[0].get_content()
