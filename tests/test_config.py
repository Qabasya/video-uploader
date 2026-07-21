"""Тесты Settings: дефолты, env-переопределения, валидаторы, секреты."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from video_uploader.config import Settings

REQUIRED = {
    "s3_bucket": "bucket",
    "s3_access_key": "access-key",
    "s3_secret_key": "top-secret",
    "lms_base_url": "http://lms.local",
    "lms_hmac_secret": "hmac-secret",
}


def make_settings(**overrides: object) -> Settings:
    """Settings с заполненными обязательными полями; локальный .env не читается."""
    return Settings(_env_file=None, **{**REQUIRED, **overrides})


class TestDefaults:
    def test_defaults(self) -> None:
        settings = make_settings()
        assert settings.video_root == Path("/mnt/video")
        assert settings.data_dir == Path("/data")
        assert settings.scan_interval_seconds == 300
        assert settings.stability_minutes == 5
        assert settings.max_attempts == 5
        assert settings.api_port == 8090
        assert settings.heartbeat_interval_seconds == 3600
        assert settings.skip_older_than_days is None
        assert settings.archive_after_register is True
        assert settings.dry_run is False
        assert settings.dry_run_lms_live is False
        assert settings.archive_subdir == "_uploaded"
        assert settings.tz_name == "Europe/Kaliningrad"
        assert settings.allowed_extensions == (".webm", ".mp4", ".mkv")
        assert settings.date_regex is None

    def test_required_fields_reported(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            Settings(_env_file=None)
        missing = {error["loc"][0] for error in exc_info.value.errors()}
        assert missing == {
            "s3_bucket",
            "s3_access_key",
            "s3_secret_key",
            "lms_base_url",
            "lms_hmac_secret",
        }


class TestEnvSource:
    def test_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SCAN_INTERVAL_SECONDS", "60")
        monkeypatch.setenv("VIDEO_ROOT", "/srv/video")
        monkeypatch.setenv("DRY_RUN", "true")
        monkeypatch.setenv("DRY_RUN_LMS_LIVE", "true")
        settings = make_settings()
        assert settings.scan_interval_seconds == 60
        assert settings.video_root == Path("/srv/video")
        assert settings.dry_run is True
        assert settings.dry_run_lms_live is True

    def test_required_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for name, value in {
            "S3_BUCKET": "env-bucket",
            "S3_ACCESS_KEY": "env-key",
            "S3_SECRET_KEY": "env-secret",
            "LMS_BASE_URL": "http://env-lms",
            "LMS_HMAC_SECRET": "env-hmac-secret",
        }.items():
            monkeypatch.setenv(name, value)
        settings = Settings(_env_file=None)
        assert settings.s3_bucket == "env-bucket"
        assert settings.s3_secret_key.get_secret_value() == "env-secret"

    @pytest.mark.parametrize("name", ["SKIP_OLDER_THAN_DAYS", "LOKI_URL", "DATE_REGEX"])
    def test_empty_env_means_none(self, monkeypatch: pytest.MonkeyPatch, name: str) -> None:
        monkeypatch.setenv(name, "")
        settings = make_settings()
        assert getattr(settings, name.lower()) is None


class TestConstraints:
    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("scan_interval_seconds", 0),
            ("stability_minutes", -1),
            ("max_attempts", 0),
            ("skip_older_than_days", 0),
            ("api_port", 0),
            ("api_port", 70000),
            ("heartbeat_interval_seconds", 0),
        ],
    )
    def test_out_of_range_rejected(self, field: str, value: int) -> None:
        with pytest.raises(ValidationError):
            make_settings(**{field: value})


class TestAllowedExtensions:
    def test_parsed_and_normalized(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ALLOWED_EXTENSIONS", " WEBM, .MP4,")
        assert make_settings().allowed_extensions == (".webm", ".mp4")

    def test_empty_list_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ALLOWED_EXTENSIONS", " , ,")
        with pytest.raises(ValidationError):
            make_settings()


class TestTzName:
    def test_known_zone_accepted(self) -> None:
        assert make_settings(tz_name="Europe/Moscow").tz_name == "Europe/Moscow"

    def test_unknown_zone_rejected(self) -> None:
        with pytest.raises(ValidationError, match="часовой пояс"):
            make_settings(tz_name="Mars/Olympus")


class TestDateRegex:
    VALID = (
        r"(?P<day>\d{2})_(?P<month>\d{2})_(?P<year>\d{2})"
        r"_(?P<hour>\d{2})_(?P<minute>\d{2})_(?P<second>\d{2})"
    )

    def test_valid_pattern_accepted(self) -> None:
        assert make_settings(date_regex=self.VALID).date_regex == self.VALID

    def test_uncompilable_rejected(self) -> None:
        with pytest.raises(ValidationError, match="не компилируется"):
            make_settings(date_regex="(")

    def test_missing_groups_listed(self) -> None:
        with pytest.raises(ValidationError, match="hour"):
            make_settings(date_regex=r"(?P<day>\d{2})_(?P<month>\d{2})_(?P<year>\d{2})")


class TestSecrets:
    def test_secret_masked_in_repr(self) -> None:
        settings = make_settings()
        assert "top-secret" not in repr(settings)
        assert "top-secret" not in str(settings)

    def test_secret_value_accessible(self) -> None:
        assert make_settings().s3_secret_key.get_secret_value() == "top-secret"
