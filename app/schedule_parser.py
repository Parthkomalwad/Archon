import pytz

from app.config import ConfigError, ScheduleConfig


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DAY_MAP: dict[str, int] = {
    "sunday": 0,
    "monday": 1,
    "tuesday": 2,
    "wednesday": 3,
    "thursday": 4,
    "friday": 5,
    "saturday": 6,
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _validate_timezone(tz: str) -> None:
    """Raise ConfigError if tz is not a valid IANA timezone string."""
    try:
        pytz.timezone(tz)
    except pytz.exceptions.UnknownTimeZoneError:
        raise ConfigError(
            f"Invalid timezone '{tz}'. "
            "Must be a valid IANA timezone string (e.g. 'UTC', 'America/New_York')."
        )


def _parse_at(at: str) -> tuple[int, int]:
    """
    Parse an 'HH:MM' time string into (hour, minute).
    Raises ConfigError on invalid format or out-of-range values.
    """
    try:
        parts = at.split(":")
        if len(parts) != 2:
            raise ValueError
        hour = int(parts[0])
        minute = int(parts[1])
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError
        return hour, minute
    except (ValueError, AttributeError):
        raise ConfigError(
            f"Invalid 'at' field '{at}'. "
            "Must be in 'HH:MM' 24-hour format (e.g. '14:00', '09:30')."
        )


def _parse_day(on) -> int:
    """
    Parse a day name string to a DOW integer (Sunday=0 … Saturday=6).
    Raises ConfigError for unknown day names.
    """
    if not isinstance(on, str):
        raise ConfigError(
            f"Weekly 'on' field must be a day name (e.g. 'sunday'), got: {on!r}"
        )
    day = on.lower().strip()
    if day not in _DAY_MAP:
        raise ConfigError(
            f"Invalid day name '{on}' for weekly schedule. "
            f"Must be one of: {', '.join(_DAY_MAP)}."
        )
    return _DAY_MAP[day]


def _parse_dom(on) -> int:
    """
    Parse a day-of-month value (1–28).
    Raises ConfigError for values outside 1–28 (29–31 are excluded because
    not all months have those days, which would cause schedules to silently
    skip in short months).
    """
    try:
        dom = int(on)
    except (TypeError, ValueError):
        raise ConfigError(
            f"Monthly 'on' field must be an integer between 1 and 28, got: {on!r}"
        )
    if dom < 1 or dom > 28:
        raise ConfigError(
            f"Monthly 'on' value {dom} is out of range. "
            "Must be between 1 and 28. Values 29–31 are not allowed because "
            "not every month has those days."
        )
    return dom


# ---------------------------------------------------------------------------
# ScheduleParser
# ---------------------------------------------------------------------------

class ScheduleParser:
    """
    Converts a ScheduleConfig into a cron expression string.

    Cron field order: MINUTE HOUR DOM MONTH DOW
    (matches APScheduler CronTrigger field order)

    frequency → cron pattern
    ─────────────────────────────────────────────────
    hourly              0 * * * *
    daily   at HH:MM    MM HH * * *
    weekly  on DAY      MM HH * * D
    monthly on N        MM HH N * *
    cron    raw expr    <pass through unchanged>
    """

    @staticmethod
    def parse(schedule: ScheduleConfig) -> str:
        """
        Return a cron expression string for the given schedule config.
        Raises ConfigError if the schedule is invalid.
        """
        _validate_timezone(schedule.timezone)

        # Raw cron passthrough  no further validation
        if schedule.cron:
            return schedule.cron

        freq = schedule.frequency

        if freq == "hourly":
            return "0 * * * *"

        hour, minute = _parse_at(schedule.at)

        if freq == "daily":
            return f"{minute} {hour} * * *"

        if freq == "weekly":
            dow = _parse_day(schedule.on)
            return f"{minute} {hour} * * {dow}"

        if freq == "monthly":
            dom = _parse_dom(schedule.on)
            return f"{minute} {hour} {dom} * *"

        # ConfigLoader validates frequency values, so this branch is a safety net
        raise ConfigError(
            f"Unknown schedule frequency '{freq}'. "
            "Must be one of: daily, weekly, monthly, hourly."
        )
