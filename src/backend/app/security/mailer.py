from datetime import date
from typing import Any, Protocol

from starlette.concurrency import run_in_threadpool

from app.core.config import get_settings

_INVITE_SUBJECTS = {
    "en": "You're invited to TrainDrain",
    "de": "Sie wurden zu TrainDrain eingeladen",
}

_PASSWORD_RESET_SUBJECTS = {
    "en": "Reset your TrainDrain password",
    "de": "Setzen Sie Ihr TrainDrain-Passwort zurück",
}

_ASSIGNMENT_SUBJECTS = {
    "en": "New training assigned to you on TrainDrain",
    "de": "Ihnen wurde ein neues Training auf TrainDrain zugewiesen",
}


class SESClient(Protocol):
    def send_email(self, **kwargs: Any) -> Any: ...


def _invite_email_body(language: str, accept_url: str) -> str:
    if language == "de":
        return (
            "Sie wurden eingeladen, TrainDrain beizutreten.\n\n"
            f"Klicken Sie auf den folgenden Link, um Ihr Konto zu aktivieren:\n{accept_url}\n\n"
            "Dieser Link ist nur einmal gültig und läuft nach einiger Zeit ab."
        )
    return (
        "You've been invited to join TrainDrain.\n\n"
        f"Follow this link to activate your account:\n{accept_url}\n\n"
        "This link is single-use and will expire after some time."
    )


async def send_invite_email(
    ses_client: SESClient, *, to_email: str, language: str, accept_url: str
) -> None:
    # boto3 is a blocking client — offloaded to a thread so it doesn't stall
    # the event loop other requests share.
    subject = _INVITE_SUBJECTS.get(language, _INVITE_SUBJECTS["en"])
    body = _invite_email_body(language, accept_url)
    await _send(ses_client, to_email=to_email, subject=subject, body=body)


def _password_reset_email_body(language: str, reset_url: str) -> str:
    if language == "de":
        return (
            "Für Ihr TrainDrain-Konto wurde ein Passwort-Reset angefordert.\n\n"
            f"Klicken Sie auf den folgenden Link, um ein neues Passwort festzulegen:\n{reset_url}\n\n"
            "Dieser Link ist nur einmal gültig und läuft in einer Stunde ab. Wenn Sie diese "
            "Anfrage nicht gestellt haben, können Sie diese E-Mail ignorieren."
        )
    return (
        "A password reset was requested for your TrainDrain account.\n\n"
        f"Follow this link to set a new password:\n{reset_url}\n\n"
        "This link is single-use and expires in one hour. If you didn't request this, "
        "you can safely ignore this email."
    )


async def send_password_reset_email(
    ses_client: SESClient, *, to_email: str, language: str, reset_url: str
) -> None:
    subject = _PASSWORD_RESET_SUBJECTS.get(language, _PASSWORD_RESET_SUBJECTS["en"])
    body = _password_reset_email_body(language, reset_url)
    await _send(ses_client, to_email=to_email, subject=subject, body=body)


def _assignment_email_body(
    language: str, *, module_title: str, due_date: date | None, module_url: str
) -> str:
    if language == "de":
        due_line = f"Fällig am: {due_date.isoformat()}\n\n" if due_date else ""
        return (
            f"Ihnen wurde folgendes Training zugewiesen: {module_title}\n\n"
            f"{due_line}"
            f"Öffnen Sie es hier:\n{module_url}"
        )
    due_line = f"Due: {due_date.isoformat()}\n\n" if due_date else ""
    return (
        f"You have been assigned the following training: {module_title}\n\n"
        f"{due_line}"
        f"Open it here:\n{module_url}"
    )


async def send_assignment_email(
    ses_client: SESClient,
    *,
    to_email: str,
    language: str,
    module_title: str,
    due_date: date | None,
    module_url: str,
) -> None:
    subject = _ASSIGNMENT_SUBJECTS.get(language, _ASSIGNMENT_SUBJECTS["en"])
    body = _assignment_email_body(
        language, module_title=module_title, due_date=due_date, module_url=module_url
    )
    await _send(ses_client, to_email=to_email, subject=subject, body=body)


async def _send(ses_client: SESClient, *, to_email: str, subject: str, body: str) -> None:
    # boto3 is a blocking client — offloaded to a thread so it doesn't stall
    # the event loop other requests share.
    sender = get_settings().ses_sender_email

    def _send_sync() -> None:
        ses_client.send_email(
            Source=sender,
            Destination={"ToAddresses": [to_email]},
            Message={
                "Subject": {"Data": subject, "Charset": "UTF-8"},
                "Body": {"Text": {"Data": body, "Charset": "UTF-8"}},
            },
        )

    await run_in_threadpool(_send_sync)
