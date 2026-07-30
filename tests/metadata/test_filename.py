"""Тесты FilenameDateExtractor: разбор блока даты, fallback-условия, tz-awareness."""

from datetime import timedelta
from pathlib import Path

from video_uploader.metadata.filename import FilenameDateExtractor

OBS_NAME = "2026-07-30_15-04-14.mp4"


class TestDefaultPattern:
    def test_real_obs_name(self) -> None:
        extractor = FilenameDateExtractor(tz_name="Europe/Kaliningrad")
        path = Path(OBS_NAME)

        result = extractor.extract(path)

        assert result is not None
        assert (result.year, result.month, result.day) == (2026, 7, 30)
        assert (result.hour, result.minute, result.second) == (15, 4, 14)

    def test_prefix_does_not_matter(self) -> None:
        extractor = FilenameDateExtractor(tz_name="Europe/Kaliningrad")
        result = extractor.extract(Path("Занятие_переименовано_2026-07-30_15-04-14.mp4"))
        assert result is not None
        assert result.day == 30

    def test_invalid_month_returns_none(self) -> None:
        extractor = FilenameDateExtractor(tz_name="Europe/Kaliningrad")
        result = extractor.extract(Path("2026-13-30_15-04-14.mp4"))
        assert result is None

    def test_nonexistent_day_returns_none(self) -> None:
        extractor = FilenameDateExtractor(tz_name="Europe/Kaliningrad")
        result = extractor.extract(Path("2026-02-30_15-04-14.mp4"))
        assert result is None

    def test_no_date_block_returns_none(self) -> None:
        extractor = FilenameDateExtractor(tz_name="Europe/Kaliningrad")
        result = extractor.extract(Path("random_name.mp4"))
        assert result is None

    def test_obs_name_with_space_is_not_parsed(self) -> None:
        # OBS из коробки ставит пробел между датой и временем; в настройках записи
        # должен быть выбран формат без пробелов, иначе дата уйдёт в fallback на mtime
        extractor = FilenameDateExtractor(tz_name="Europe/Kaliningrad")
        result = extractor.extract(Path("2026-07-30 15-04-14.mp4"))
        assert result is None

    def test_two_digit_year_is_not_matched(self) -> None:
        extractor = FilenameDateExtractor(tz_name="Europe/Kaliningrad")
        result = extractor.extract(Path("26-07-30_15-04-14.mp4"))
        assert result is None

    def test_telemost_name_no_longer_parsed(self) -> None:
        # записи Телемоста больше не поддерживаются: их имена уходят в fallback на mtime
        extractor = FilenameDateExtractor(tz_name="Europe/Kaliningrad")
        result = extractor.extract(Path("Встреча_в_Телемосте_08_07_26_16_04_45_—_запись.webm"))
        assert result is None


class TestTzAwareness:
    def test_result_is_tz_aware(self) -> None:
        extractor = FilenameDateExtractor(tz_name="Europe/Kaliningrad")
        result = extractor.extract(Path(OBS_NAME))
        assert result is not None
        assert result.utcoffset() is not None

    def test_kaliningrad_offset_is_plus_two(self) -> None:
        extractor = FilenameDateExtractor(tz_name="Europe/Kaliningrad")
        result = extractor.extract(Path(OBS_NAME))
        assert result is not None
        assert result.utcoffset() == timedelta(hours=2)


class TestCustomPattern:
    COMPACT_PATTERN = (
        r"(?P<year>\d{4})(?P<month>\d{2})(?P<day>\d{2})"
        r"_(?P<hour>\d{2})(?P<minute>\d{2})(?P<second>\d{2})"
    )
    TWO_DIGIT_YEAR_PATTERN = (
        r"(?P<year>\d{2})_(?P<month>\d{2})_(?P<day>\d{2})"
        r"_(?P<hour>\d{2})_(?P<minute>\d{2})_(?P<second>\d{2})"
    )

    def test_custom_pattern_is_used(self) -> None:
        extractor = FilenameDateExtractor(
            tz_name="Europe/Kaliningrad", pattern=self.COMPACT_PATTERN
        )
        result = extractor.extract(Path("cam_20310708_160445.mp4"))
        assert result is not None
        assert (result.year, result.month, result.day) == (2031, 7, 8)
        assert (result.hour, result.minute, result.second) == (16, 4, 45)

    def test_default_pattern_not_used_when_custom_given(self) -> None:
        extractor = FilenameDateExtractor(
            tz_name="Europe/Kaliningrad", pattern=self.COMPACT_PATTERN
        )
        result = extractor.extract(Path(OBS_NAME))
        assert result is None

    def test_two_digit_year_is_taken_literally(self) -> None:
        # нормализации «ГГ -> 20ГГ» больше нет: кастомный DATE_REGEX обязан
        # захватывать четырёхзначный год, иначе год будет разобран буквально
        extractor = FilenameDateExtractor(
            tz_name="Europe/Kaliningrad", pattern=self.TWO_DIGIT_YEAR_PATTERN
        )
        result = extractor.extract(Path("rec_26_07_30_15_04_14.mp4"))
        assert result is not None
        assert result.year == 26
