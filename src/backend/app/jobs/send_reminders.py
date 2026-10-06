"""The scheduled reminder job's entrypoint.

`python -m app.jobs.send_reminders` — the exact command production invokes
(an EventBridge Scheduler-triggered ECS task, ticket 14) and the one the
`reminder-runner` service in `docker-compose.yml` loops locally, so the
scheduled path is exercisable without emulating a scheduler. The job itself
(`app.reminders.run_scheduled_reminders`) is idempotent, so running it more
than once on the same day — which the local loop deliberately does — sends
nothing on the reruns.
"""

import asyncio
import logging

from app.campaigns import activate_due_campaigns
from app.db import async_session_factory
from app.dependencies import get_ses_client
from app.reminders import run_scheduled_reminders

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("traindrain.reminders")


async def main() -> None:
    ses_client = get_ses_client()
    async with async_session_factory() as db:
        # Campaigns whose start date has arrived go live first, so the same
        # run's reminders already see them. Idempotent: the status flip is the
        # guard, so a rerun the same day activates nothing.
        activated = await activate_due_campaigns(db, ses_client)
        logger.info("Activated %d campaign(s).", activated)
        sent_count = await run_scheduled_reminders(db, ses_client)
        await db.commit()
    logger.info("Sent %d reminder email(s).", sent_count)


if __name__ == "__main__":
    asyncio.run(main())
