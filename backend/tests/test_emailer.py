import pytest

from app.auth import emailer


def test_console_backend(monkeypatch):
    monkeypatch.setattr("app.auth.emailer.get_settings",
                        lambda: type("S", (), {"email_backend": "console"})())
    assert isinstance(emailer.get_email_sender(), emailer.ConsoleEmailSender)


def test_unknown_backend_fails_loud(monkeypatch):
    monkeypatch.setattr("app.auth.emailer.get_settings",
                        lambda: type("S", (), {"email_backend": "carrier-pigeon"})())
    with pytest.raises(RuntimeError):
        emailer.get_email_sender()


@pytest.mark.asyncio
async def test_smtp_missing_config_raises(monkeypatch):
    cfg = type("S", (), {
        "email_backend": "smtp", "smtp_host": "", "smtp_user": "", "smtp_from": "",
        "smtp_port": 465, "smtp_password": "", "smtp_use_tls": True,
    })()
    monkeypatch.setattr("app.auth.emailer.get_settings", lambda: cfg)
    with pytest.raises(RuntimeError):
        await emailer.SmtpEmailSender().send("a@b.com", "s", "b")
