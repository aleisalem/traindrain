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

_CAMPAIGN_ACTIVATION_SUBJECTS = {
    "en": "A new training campaign has started on TrainDrain",
    "de": "Eine neue Trainingskampagne hat auf TrainDrain begonnen",
}

_REMINDER_SUBJECTS = {
    "en": "Reminder: training due on TrainDrain",
    "de": "Erinnerung: Fälliges Training auf TrainDrain",
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


def _campaign_activation_email_body(
    language: str, *, campaign_name: str, due_date: date | None, url: str
) -> str:
    if language == "de":
        due_line = f"Fällig am: {due_date.isoformat()}\n\n" if due_date else ""
        return (
            f"Für Sie hat eine neue Trainingskampagne begonnen: {campaign_name}\n\n"
            f"{due_line}"
            f"Öffnen Sie Ihre Trainings hier:\n{url}"
        )
    due_line = f"Due: {due_date.isoformat()}\n\n" if due_date else ""
    return (
        f"A new training campaign has started for you: {campaign_name}\n\n"
        f"{due_line}"
        f"Open your learning here:\n{url}"
    )


async def send_campaign_activation_email(
    ses_client: SESClient,
    *,
    to_email: str,
    language: str,
    campaign_name: str,
    due_date: date | None,
    url: str,
) -> None:
    subject = _CAMPAIGN_ACTIVATION_SUBJECTS.get(language, _CAMPAIGN_ACTIVATION_SUBJECTS["en"])
    body = _campaign_activation_email_body(
        language, campaign_name=campaign_name, due_date=due_date, url=url
    )
    await _send(ses_client, to_email=to_email, subject=subject, body=body)


def _reminder_headline(language: str, *, module_title: str, due: str, kind: str) -> str:
    """The one line that varies by cadence checkpoint — one entry per kind,
    each carrying both languages together, rather than two parallel
    per-language dicts that could drift out of sync with each other."""
    # Kind strings, not `app.reminders`'s constants: this module sits below
    # the domain layer (`app.reminders` already imports `send_reminder_email`
    # from here), so importing back from it would be circular.
    en_manual = f"Still outstanding: {module_title} (due: {due})" if due else f"Still outstanding: {module_title}"
    de_manual = f"Noch ausstehend: {module_title} (fällig: {due})" if due else f"Noch ausstehend: {module_title}"
    headlines: dict[str, tuple[str, str]] = {
        "advance_7": (f"Due in 7 days ({due}): {module_title}", f"Fällig in 7 Tagen ({due}): {module_title}"),
        "advance_1": (f"Due tomorrow ({due}): {module_title}", f"Fällig morgen ({due}): {module_title}"),
        "due": (f"Due today ({due}): {module_title}", f"Heute fällig ({due}): {module_title}"),
        "overdue_weekly": (f"Overdue since {due}: {module_title}", f"Überfällig seit {due}: {module_title}"),
        "manual": (en_manual, de_manual),
    }
    en, de = headlines.get(kind, (module_title, module_title))
    return de if language == "de" else en


def _reminder_email_body(
    language: str, *, module_title: str, due_date: date | None, module_url: str, kind: str
) -> str:
    due = due_date.isoformat() if due_date else ""
    headline = _reminder_headline(language, module_title=module_title, due=due, kind=kind)
    close = "Öffnen Sie es hier" if language == "de" else "Open it here"
    return f"{headline}\n\n{close}:\n{module_url}"


async def send_reminder_email(
    ses_client: SESClient,
    *,
    to_email: str,
    language: str,
    module_title: str,
    due_date: date | None,
    module_url: str,
    kind: str,
) -> None:
    subject = _REMINDER_SUBJECTS.get(language, _REMINDER_SUBJECTS["en"])
    body = _reminder_email_body(
        language, module_title=module_title, due_date=due_date, module_url=module_url, kind=kind
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
