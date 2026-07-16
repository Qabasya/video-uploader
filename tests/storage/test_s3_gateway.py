"""Тесты S3Gateway: правильные вызовы boto3 через фейковый клиент (без сети)."""

import json
from pathlib import Path
from typing import Any

import boto3
import pytest

from video_uploader.storage.s3_gateway import S3Gateway


class FakeBotoClient:
    """Записывает аргументы вызовов вместо реального обращения к S3."""

    def __init__(self) -> None:
        self.constructor_calls: list[dict[str, Any]] = []
        self.upload_file_calls: list[dict[str, Any]] = []
        self.put_object_calls: list[dict[str, Any]] = []
        self.head_object_calls: list[dict[str, Any]] = []
        self.head_object_response: dict[str, Any] = {"ContentLength": 0}

    def upload_file(self, **kwargs: Any) -> None:
        self.upload_file_calls.append(kwargs)

    def put_object(self, **kwargs: Any) -> None:
        self.put_object_calls.append(kwargs)

    def head_object(self, **kwargs: Any) -> dict[str, Any]:
        self.head_object_calls.append(kwargs)
        return self.head_object_response


@pytest.fixture
def fake_client(monkeypatch: pytest.MonkeyPatch) -> FakeBotoClient:
    client = FakeBotoClient()

    def fake_boto3_client(*args: Any, **kwargs: Any) -> FakeBotoClient:
        client.constructor_calls.append(kwargs)
        return client

    monkeypatch.setattr(boto3, "client", fake_boto3_client)
    return client


def make_gateway() -> S3Gateway:
    return S3Gateway(
        endpoint_url="https://s3.ru1.storage.beget.cloud",
        region="ru-1",
        bucket="my-bucket",
        access_key="key",
        secret_key="secret",
    )


class TestConstructor:
    def test_uses_path_style_addressing(self, fake_client: FakeBotoClient) -> None:
        make_gateway()
        assert len(fake_client.constructor_calls) == 1
        assert fake_client.constructor_calls[0]["config"].s3["addressing_style"] == "path"


class TestUploadVideo:
    def test_calls_upload_file_with_correct_args(
        self, fake_client: FakeBotoClient, tmp_path: Path
    ) -> None:
        gateway = make_gateway()
        video_path = tmp_path / "rec.webm"
        video_path.write_bytes(b"data")

        gateway.upload_video(
            video_path, "videos/kege-1/rec.webm", metadata={"group-slug": "kege-1"}
        )

        assert len(fake_client.upload_file_calls) == 1
        call = fake_client.upload_file_calls[0]
        assert call["Filename"] == str(video_path)
        assert call["Bucket"] == "my-bucket"
        assert call["Key"] == "videos/kege-1/rec.webm"
        assert call["ExtraArgs"]["Metadata"] == {"group-slug": "kege-1"}

    @pytest.mark.parametrize(
        ("key", "expected_content_type"),
        [
            ("videos/kege-1/rec.webm", "video/webm"),
            ("videos/kege-1/rec.mp4", "video/mp4"),
            ("videos/kege-1/rec.mkv", "video/x-matroska"),
            ("videos/kege-1/rec.mov", "application/octet-stream"),
        ],
    )
    def test_content_type_by_extension(
        self, fake_client: FakeBotoClient, tmp_path: Path, key: str, expected_content_type: str
    ) -> None:
        gateway = make_gateway()
        video_path = tmp_path / "rec.bin"
        video_path.write_bytes(b"data")

        gateway.upload_video(video_path, key, metadata={})

        content_type = fake_client.upload_file_calls[0]["ExtraArgs"]["ContentType"]
        assert content_type == expected_content_type

    def test_metadata_keys_have_no_manual_prefix(
        self, fake_client: FakeBotoClient, tmp_path: Path
    ) -> None:
        gateway = make_gateway()
        video_path = tmp_path / "rec.webm"
        video_path.write_bytes(b"data")

        gateway.upload_video(video_path, "videos/kege-1/rec.webm", metadata={"lms-group-id": "3"})

        metadata = fake_client.upload_file_calls[0]["ExtraArgs"]["Metadata"]
        assert metadata == {"lms-group-id": "3"}
        assert not any(key.startswith("x-amz-meta-") for key in metadata)

    def test_non_ascii_metadata_rejected(self, fake_client: FakeBotoClient, tmp_path: Path) -> None:
        gateway = make_gateway()
        video_path = tmp_path / "rec.webm"
        video_path.write_bytes(b"data")

        with pytest.raises(ValueError, match="ASCII"):
            gateway.upload_video(
                video_path, "videos/kege-1/rec.webm", metadata={"teacher": "Иванов"}
            )

        assert fake_client.upload_file_calls == []


class TestPutManifest:
    def test_body_is_valid_json_with_content_type(self, fake_client: FakeBotoClient) -> None:
        gateway = make_gateway()
        manifest = {"schema": 2, "source_folder": "КЕГЭ-1"}

        gateway.put_manifest("videos/kege-1/rec.webm.json", manifest)

        call = fake_client.put_object_calls[0]
        assert call["ContentType"] == "application/json"
        decoded = json.loads(call["Body"].decode("utf-8"))
        assert decoded == manifest

    def test_cyrillic_values_are_not_escaped(self, fake_client: FakeBotoClient) -> None:
        gateway = make_gateway()
        gateway.put_manifest("videos/kege-1/rec.webm.json", {"source_folder": "КЕГЭ-1"})
        body_text = fake_client.put_object_calls[0]["Body"].decode("utf-8")
        assert "КЕГЭ-1" in body_text
        assert "\\u" not in body_text


class TestVerify:
    def test_matching_size_returns_true(self, fake_client: FakeBotoClient) -> None:
        gateway = make_gateway()
        fake_client.head_object_response = {"ContentLength": 100}
        assert gateway.verify("videos/kege-1/rec.webm", expected_size=100) is True

    def test_mismatching_size_returns_false(self, fake_client: FakeBotoClient) -> None:
        gateway = make_gateway()
        fake_client.head_object_response = {"ContentLength": 99}
        assert gateway.verify("videos/kege-1/rec.webm", expected_size=100) is False
