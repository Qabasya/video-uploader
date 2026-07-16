"""Тесты FilenameDateExtractor: разбор блока даты, fallback-условия, tz-awareness."""

from datetime import timedelta
from pathlib import Path

from video_uploader.metadata.filename import FilenameDateExtractor


class TestDefaultPattern:
    def test_real_telemost_name(self) -> None:
        extractor = FilenameDateExtractor(tz_name="Europe/Kaliningrad")
        path = Path("Встреча_в_Телемосте_08_07_26_16_04_45_—_запись.webm")

        result = extractor.extract(path)

        assert result is not None
        assert (result.year, result.month, result.day) == (2026, 7, 8)
        assert (result.hour, result.minute, result.second) == (16, 4, 45)

    def test_two_digit_year_becomes_20xx(self) -> None:
        extractor = FilenameDateExtractor(tz_name="Europe/Kaliningrad")
        result = extractor.extract(Path("01_01_99_10_00_00_rec.webm"))
        assert result is not None
        assert result.year == 2099

    def test_prefix_does_not_matter(self) -> None:
        extractor = FilenameDateExtractor(tz_name="Europe/Kaliningrad")
        result = extractor.extract(Path("Занятие_переименовано_08_07_26_16_04_45.webm"))
        assert result is not None
        assert result.day == 8

    def test_invalid_month_returns_none(self) -> None:
        extractor = FilenameDateExtractor(tz_name="Europe/Kaliningrad")
        result = extractor.extract(Path("08_13_26_16_04_45_rec.webm"))
        assert result is None

    def test_no_date_block_returns_none(self) -> None:
        extractor = FilenameDateExtractor(tz_name="Europe/Kaliningrad")
        result = extractor.extract(Path("random_name.webm"))
        assert result is None


class TestTzAwareness:
    def test_result_is_tz_aware(self) -> None:
        extractor = FilenameDateExtractor(tz_name="Europe/Kaliningrad")
        result = extractor.extract(Path("08_07_26_16_04_45_rec.webm"))
        assert result is not None
        assert result.utcoffset() is not None

    def test_kaliningrad_offset_is_plus_two(self) -> None:
        extractor = FilenameDateExtractor(tz_name="Europe/Kaliningrad")
        result = extractor.extract(Path("08_07_26_16_04_45_rec.webm"))
        assert result is not None
        assert result.utcoffset() == timedelta(hours=2)


class TestCustomPattern:
    FOUR_DIGIT_YEAR_PATTERN = (
        r"(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})T"
        r"(?P<hour>\d{2})(?P<minute>\d{2})(?P<second>\d{2})"
    )

    def test_custom_pattern_with_four_digit_year(self) -> None:
        extractor = FilenameDateExtractor(
            tz_name="Europe/Kaliningrad", pattern=self.FOUR_DIGIT_YEAR_PATTERN
        )
        result = extractor.extract(Path("cam_2031-07-08T160445.webm"))
        assert result is not None
        assert result.year == 2031  # не 2000+2031

    def test_default_pattern_not_used_when_custom_given(self) -> None:
        extractor = FilenameDateExtractor(
            tz_name="Europe/Kaliningrad", pattern=self.FOUR_DIGIT_YEAR_PATTERN
        )
        result = extractor.extract(Path("08_07_26_16_04_45_rec.webm"))
        assert result is None
