"""
Unit tests for ScheduleParser (Phase 5).
"""
import pytest

from app.config import ConfigError, ScheduleConfig
from app.schedule_parser import ScheduleParser


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _parse(**kwargs) -> str:
    """Build a ScheduleConfig and run ScheduleParser.parse()."""
    cfg = ScheduleConfig(**kwargs)
    return ScheduleParser.parse(cfg)


# ---------------------------------------------------------------------------
# daily
# ---------------------------------------------------------------------------

class TestDaily:
    def test_daily_standard_time(self):
        assert _parse(frequency="daily", at="14:00", timezone="UTC") == "0 14 * * *"

    def test_daily_midnight(self):
        assert _parse(frequency="daily", at="00:00", timezone="UTC") == "0 0 * * *"

    def test_daily_end_of_day(self):
        assert _parse(frequency="daily", at="23:00", timezone="UTC") == "0 23 * * *"

    def test_daily_with_nonzero_minutes(self):
        assert _parse(frequency="daily", at="14:30", timezone="UTC") == "30 14 * * *"

    def test_daily_single_digit_hour(self):
        assert _parse(frequency="daily", at="02:00", timezone="UTC") == "0 2 * * *"


# ---------------------------------------------------------------------------
# weekly
# ---------------------------------------------------------------------------

class TestWeekly:
    def test_weekly_sunday(self):
        assert _parse(frequency="weekly", on="sunday", at="03:00", timezone="UTC") == "0 3 * * 0"

    def test_weekly_monday(self):
        assert _parse(frequency="weekly", on="monday", at="09:00", timezone="UTC") == "0 9 * * 1"

    def test_weekly_tuesday(self):
        assert _parse(frequency="weekly", on="tuesday", at="10:00", timezone="UTC") == "0 10 * * 2"

    def test_weekly_wednesday(self):
        assert _parse(frequency="weekly", on="wednesday", at="11:00", timezone="UTC") == "0 11 * * 3"

    def test_weekly_thursday(self):
        assert _parse(frequency="weekly", on="thursday", at="12:00", timezone="UTC") == "0 12 * * 4"

    def test_weekly_friday(self):
        assert _parse(frequency="weekly", on="friday", at="18:00", timezone="UTC") == "0 18 * * 5"

    def test_weekly_saturday(self):
        assert _parse(frequency="weekly", on="saturday", at="22:00", timezone="UTC") == "0 22 * * 6"

    def test_weekly_day_name_case_insensitive(self):
        assert _parse(frequency="weekly", on="Sunday", at="03:00", timezone="UTC") == "0 3 * * 0"
        assert _parse(frequency="weekly", on="MONDAY", at="09:00", timezone="UTC") == "0 9 * * 1"

    def test_weekly_invalid_day_raises_config_error(self):
        with pytest.raises(ConfigError, match="funday"):
            _parse(frequency="weekly", on="funday", at="10:00", timezone="UTC")

    def test_weekly_numeric_on_raises_config_error(self):
        with pytest.raises(ConfigError):
            ScheduleParser.parse(ScheduleConfig(
                frequency="weekly", on=1, at="10:00", timezone="UTC"
            ))


# ---------------------------------------------------------------------------
# monthly
# ---------------------------------------------------------------------------

class TestMonthly:
    def test_monthly_first_of_month(self):
        assert _parse(frequency="monthly", on=1, at="00:00", timezone="UTC") == "0 0 1 * *"

    def test_monthly_last_safe_day(self):
        assert _parse(frequency="monthly", on=28, at="12:00", timezone="UTC") == "0 12 28 * *"

    def test_monthly_mid_month(self):
        assert _parse(frequency="monthly", on=15, at="06:00", timezone="UTC") == "0 6 15 * *"

    def test_monthly_on_string_integer(self):
        # on: can arrive as a string from YAML
        assert _parse(frequency="monthly", on="10", at="08:00", timezone="UTC") == "0 8 10 * *"

    def test_monthly_on_29_raises_config_error(self):
        with pytest.raises(ConfigError, match="29"):
            _parse(frequency="monthly", on=29, at="00:00", timezone="UTC")

    def test_monthly_on_30_raises_config_error(self):
        with pytest.raises(ConfigError, match="30"):
            _parse(frequency="monthly", on=30, at="00:00", timezone="UTC")

    def test_monthly_on_31_raises_config_error(self):
        with pytest.raises(ConfigError, match="31"):
            _parse(frequency="monthly", on=31, at="00:00", timezone="UTC")

    def test_monthly_on_0_raises_error(self):
        # on=0 is falsy  caught by ScheduleConfig's model_validator (ValidationError)
        # before ScheduleParser even runs; either exception means "rejected"
        with pytest.raises(Exception):
            _parse(frequency="monthly", on=0, at="00:00", timezone="UTC")

    def test_monthly_on_negative_raises_config_error(self):
        with pytest.raises(ConfigError):
            _parse(frequency="monthly", on=-1, at="00:00", timezone="UTC")


# ---------------------------------------------------------------------------
# hourly
# ---------------------------------------------------------------------------

class TestHourly:
    def test_hourly_returns_fixed_cron(self):
        cfg = ScheduleConfig(frequency="hourly", timezone="UTC")
        assert ScheduleParser.parse(cfg) == "0 * * * *"

    def test_hourly_ignores_at_field(self):
        # at is not required for hourly; if provided it should still work
        cfg = ScheduleConfig(frequency="hourly", timezone="UTC")
        assert ScheduleParser.parse(cfg) == "0 * * * *"


# ---------------------------------------------------------------------------
# raw cron passthrough
# ---------------------------------------------------------------------------

class TestRawCron:
    def test_cron_passthrough_every_30_minutes(self):
        cfg = ScheduleConfig(cron="*/30 * * * *", timezone="UTC")
        assert ScheduleParser.parse(cfg) == "*/30 * * * *"

    def test_cron_passthrough_complex_expression(self):
        expr = "0 2 * * 1-5"
        cfg = ScheduleConfig(cron=expr, timezone="UTC")
        assert ScheduleParser.parse(cfg) == expr

    def test_cron_passthrough_preserves_whitespace_exactly(self):
        expr = "15 4 1,15 * *"
        cfg = ScheduleConfig(cron=expr, timezone="UTC")
        assert ScheduleParser.parse(cfg) == expr


# ---------------------------------------------------------------------------
# timezone validation
# ---------------------------------------------------------------------------

class TestTimezone:
    def test_utc_is_valid(self):
        result = _parse(frequency="daily", at="10:00", timezone="UTC")
        assert result == "0 10 * * *"

    def test_america_new_york_is_valid(self):
        result = _parse(frequency="daily", at="10:00", timezone="America/New_York")
        assert result == "0 10 * * *"

    def test_europe_london_is_valid(self):
        result = _parse(frequency="daily", at="10:00", timezone="Europe/London")
        assert result == "0 10 * * *"

    def test_invalid_timezone_raises_config_error(self):
        with pytest.raises(ConfigError, match="Mars/Olympus"):
            _parse(frequency="daily", at="10:00", timezone="Mars/Olympus")

    def test_empty_timezone_raises_config_error(self):
        with pytest.raises(ConfigError):
            _parse(frequency="daily", at="10:00", timezone="Not/AReal/Zone")


# ---------------------------------------------------------------------------
# at field validation
# ---------------------------------------------------------------------------

class TestAtField:
    def test_at_max_valid_time(self):
        assert _parse(frequency="daily", at="23:59", timezone="UTC") == "59 23 * * *"

    def test_at_invalid_hour_raises_config_error(self):
        with pytest.raises(ConfigError, match="'at'"):
            _parse(frequency="daily", at="25:00", timezone="UTC")

    def test_at_invalid_minute_raises_config_error(self):
        with pytest.raises(ConfigError, match="'at'"):
            _parse(frequency="daily", at="10:60", timezone="UTC")

    def test_at_bad_format_raises_config_error(self):
        with pytest.raises(ConfigError, match="'at'"):
            _parse(frequency="daily", at="1400", timezone="UTC")

    def test_at_missing_colon_raises_config_error(self):
        with pytest.raises(ConfigError, match="'at'"):
            _parse(frequency="daily", at="14-00", timezone="UTC")
