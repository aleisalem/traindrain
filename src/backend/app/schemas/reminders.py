from pydantic import BaseModel, Field


class RemindResponse(BaseModel):
    """How many outstanding learners the manual nudge actually reached —
    fewer than "everyone assigned" whenever the daily cap already covered
    some of them via the scheduled job or an earlier nudge today."""

    sent_count: int


class ReminderTimezoneSettingResponse(BaseModel):
    timezone: str


class ReminderTimezoneSettingRequest(BaseModel):
    # An IANA zone name, e.g. "Europe/Berlin" — validated against the
    # tzdata database itself (`security.system_settings.set_reminder_timezone`)
    # rather than a regex, since that is the only thing that can actually
    # tell a real zone from a plausible-looking typo.
    timezone: str = Field(min_length=1, max_length=64)
