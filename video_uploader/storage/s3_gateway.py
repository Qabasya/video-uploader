"""Adapter над boto3: multipart upload, манифест, head/verify."""

import json
import logging
from collections.abc import Mapping
from pathlib import Path

import boto3
from boto3.s3.transfer import TransferConfig
from botocore.config import Config

logger = logging.getLogger(__name__)

_MULTIPART_THRESHOLD_BYTES = 64 * 1024 * 1024
_CONTENT_TYPES = {
    ".webm": "video/webm",
    ".mp4": "video/mp4",
    ".mkv": "video/x-matroska",
}


class S3Gateway:
    """Шлюз S3 Beget: path-style addressing, multipart upload, верификация."""

    def __init__(
        self,
        *,
        endpoint_url: str,
        region: str,
        bucket: str,
        access_key: str,
        secret_key: str,
    ) -> None:
        self._bucket = bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            region_name=region,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            config=Config(s3={"addressing_style": "path"}),
        )
        self._transfer_config = TransferConfig(
            multipart_threshold=_MULTIPART_THRESHOLD_BYTES,
            multipart_chunksize=_MULTIPART_THRESHOLD_BYTES,
        )

    def upload_video(self, path: Path, key: str, metadata: Mapping[str, str]) -> None:
        """Multipart upload; ContentType по расширению ``key``, metadata — x-amz-meta-*."""
        _validate_ascii_metadata(metadata)
        content_type = _CONTENT_TYPES.get(Path(key).suffix.lower(), "application/octet-stream")
        self._client.upload_file(
            Filename=str(path),
            Bucket=self._bucket,
            Key=key,
            Config=self._transfer_config,
            ExtraArgs={"ContentType": content_type, "Metadata": dict(metadata)},
        )

    def put_manifest(self, key: str, manifest: dict[str, object]) -> None:
        """Кладёт JSON-манифест рядом с видео (UTF-8, кириллица не экранируется)."""
        body = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
        self._client.put_object(
            Bucket=self._bucket,
            Key=key,
            Body=body,
            ContentType="application/json",
        )

    def verify(self, key: str, expected_size: int) -> bool:
        """``head_object`` -> ``ContentLength == expected_size``; ETag не используется."""
        response = self._client.head_object(Bucket=self._bucket, Key=key)
        return int(response["ContentLength"]) == expected_size


def _validate_ascii_metadata(metadata: Mapping[str, str]) -> None:
    for key, value in metadata.items():
        if not key.isascii() or not value.isascii():
            raise ValueError(f"x-amz-meta-{key}: ключ и значение должны быть ASCII ({value!r})")
