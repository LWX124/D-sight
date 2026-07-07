from email.message import EmailMessage
from typing import Protocol

import aiosmtplib

from app.core.config import get_settings


class EmailSender(Protocol):
    async def send(self, to: str, subject: str, body: str) -> None: ...


class ConsoleEmailSender:
    async def send(self, to: str, subject: str, body: str) -> None:
        print(f"[email → {to}] {subject}: {body}")


class SmtpEmailSender:
    async def send(self, to: str, subject: str, body: str) -> None:
        s = get_settings()
        if not (s.smtp_host and s.smtp_user and s.smtp_from):
            raise RuntimeError("SMTP 未正确配置（smtp_host/smtp_user/smtp_from 必填）")
        msg = EmailMessage()
        msg["From"] = s.smtp_from
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(body)
        await aiosmtplib.send(
            msg, hostname=s.smtp_host, port=s.smtp_port,
            username=s.smtp_user, password=s.smtp_password, use_tls=s.smtp_use_tls,
        )


def get_email_sender() -> EmailSender:
    backend = get_settings().email_backend
    if backend == "console":
        return ConsoleEmailSender()
    if backend == "smtp":
        return SmtpEmailSender()
    raise RuntimeError(f"未知 EMAIL_BACKEND: {backend!r}")
