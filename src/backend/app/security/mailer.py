from typing import Any, Protocol

from starlette.concurrency import run_in_threadpool

from app.core.config import get_settings

_INVITE_SUBJECTS = {
    "en": "You're invited to TrainDrain",
    "de": "Sie wurden zu TrainDrain eingeladen",
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
    sender = get_settings().ses_sender_email

    def _send() -> None:
        ses_client.send_email(
            Source=sender,
            Destination={"ToAddresses": [to_email]},
            Message={
                "Subject": {"Data": subject, "Charset": "UTF-8"},
                "Body": {"Text": {"Data": body, "Charset": "UTF-8"}},
            },
        )

    await run_in_threadpool(_send)
