from typing import Protocol


class EmailSender(Protocol):
    async def send(self, to: str, subject: str, body: str) -> None: ...


class ConsoleEmailSender:
    """开发/测试用：验证码打到 stdout，不发真实邮件。SMTP 实现在部署阶段按 spec §7.1 接入。"""

    async def send(self, to: str, subject: str, body: str) -> None:
        print(f"[email → {to}] {subject}: {body}")


def get_email_sender() -> EmailSender:
    return ConsoleEmailSender()
