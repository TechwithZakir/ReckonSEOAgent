import smtplib
import ssl
from email.message import EmailMessage
from typing import Protocol

from reckon_api.config import Settings
from reckon_core.native_auth import normalize_email


class EmailDeliveryUnavailable(RuntimeError):
    pass


class VerificationMailer(Protocol):
    def send_verification(self, email: str, token: str) -> None: ...

    def send_existing_account_notice(self, email: str) -> None: ...

    def send_password_reset(self, email: str, token: str) -> None: ...

    def send_password_reset_notice(self, email: str) -> None: ...

    def send_organization_invitation(self, email: str, organization_name: str) -> None: ...


class SmtpVerificationMailer:
    def __init__(self, settings: Settings) -> None:
        if not settings.smtp_host or not settings.smtp_from or not settings.web_public_origin:
            raise ValueError("SMTP verification settings are incomplete.")
        if any(char.isspace() for char in settings.smtp_host):
            raise ValueError("SMTP host is invalid.")
        self._host = settings.smtp_host
        self._port = settings.smtp_port
        self._sender = normalize_email(settings.smtp_from)
        self._origin = settings.web_public_origin.rstrip("/")
        self._tls = settings.smtp_tls
        self._username = settings.smtp_username
        self._password = settings.smtp_password

    def send_verification(self, email: str, token: str) -> None:
        message = EmailMessage()
        message["From"] = self._sender
        message["To"] = email
        message["Subject"] = "Verify your Reckon account"
        message.set_content(
            "To create your Reckon account, open this link and choose your password:\n\n"
            f"{self._origin}/auth/verify#token={token}\n\n"
            "This link expires in 30 minutes. If you did not request it, ignore this email."
        )
        self._send(message)

    def send_existing_account_notice(self, email: str) -> None:
        message = EmailMessage()
        message["From"] = self._sender
        message["To"] = email
        message["Subject"] = "Your Reckon account"
        message.set_content(
            "An account already exists for this address. Sign in to your Reckon workspace. "
            "If you did not request this, you can ignore this email."
        )
        self._send(message)

    def send_password_reset(self, email: str, token: str) -> None:
        message = EmailMessage()
        message["From"] = self._sender
        message["To"] = email
        message["Subject"] = "Reset your Reckon password"
        message.set_content(
            "To reset your Reckon account password, open this link:\n\n"
            f"{self._origin}/auth/reset#token={token}\n\n"
            "This link expires in 30 minutes. If you did not request it, ignore this email."
        )
        self._send(message)

    def send_password_reset_notice(self, email: str) -> None:
        message = EmailMessage()
        message["From"] = self._sender
        message["To"] = email
        message["Subject"] = "Reckon password reset request"
        message.set_content(
            "A password reset was requested for this address. "
            "If you did not request it, you can ignore this email."
        )
        self._send(message)

    def send_organization_invitation(self, email: str, organization_name: str) -> None:
        message = EmailMessage()
        message["From"] = self._sender
        message["To"] = email
        message["Subject"] = "Reckon organization invitation"
        message.set_content(
            f"You have been invited to {organization_name} on Reckon.\n\n"
            f"Sign in with this verified email address to review the invitation: {self._origin}/invitations\n\n"
            "The invitation expires in seven days."
        )
        self._send(message)

    def _send(self, message: EmailMessage) -> None:
        try:
            context = ssl.create_default_context()
            if self._tls == "implicit":
                smtp = smtplib.SMTP_SSL(self._host, self._port, timeout=10, context=context)
            else:
                smtp = smtplib.SMTP(self._host, self._port, timeout=10)
            with smtp:
                if self._tls == "starttls":
                    smtp.starttls(context=context)
                if self._username is not None and self._password is not None:
                    smtp.login(self._username, self._password.get_secret_value())
                smtp.send_message(message)
        except (smtplib.SMTPException, OSError):
            raise EmailDeliveryUnavailable("Verification email could not be sent.") from None
