"""Adapter над boto3: multipart upload, манифест, head/verify."""

import json
import logging
from collections.abc import Mapping
from pathlib import Path

import boto3
from boto3.s3.transfer import TransferConfig
from botocore.config import Config

from video_uploader.storage.faststart import faststart_copy

logger = logging.getLogger(__name__)

_MULTIPART_THRESHOLD_BYTES = 64 * 1024 * 1024
_CONTENT_TYPES = {
    ".webm": "video/webm",
    ".mp4": "video/mp4",
    ".mkv": "video/x-matroska",
}
# Записи не меняются после загрузки; ссылка в LMS подписывается заново, а браузер кеширует тело.
_CACHE_CONTROL = "private, max-age=86400"
_REMUX_SOURCE_SIZE_KEY = "remuxed-from-size"


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
        remux_dir: Path | None = None,
    ) -> None:
        self._bucket = bucket
        self._remux_dir = remux_dir
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
        """Multipart upload; ContentType по расширению ``key``, metadata — x-amz-meta-*.

        mp4/mov с ``moov`` в конце перед загрузкой перепаковываются в faststart (если задан
        ``remux_dir`` и есть ffmpeg); размер исходника кладётся в metadata для ``verify``.
        """
        _validate_ascii_metadata(metadata)
        if self._remux_dir is None:
            self._upload(path, key, metadata)
            return
        with faststart_copy(path, self._remux_dir) as remuxed:
            if remuxed is None:
                self._upload(path, key, metadata)
                return
            source_size = path.stat().st_size
            self._upload(remuxed, key, {**metadata, _REMUX_SOURCE_SIZE_KEY: str(source_size)})

    def _upload(self, path: Path, key: str, metadata: Mapping[str, str]) -> None:
        content_type = _CONTENT_TYPES.get(Path(key).suffix.lower(), "application/octet-stream")
        self._client.upload_file(
            Filename=str(path),
            Bucket=self._bucket,
            Key=key,
            Config=self._transfer_config,
            ExtraArgs={
                "ContentType": content_type,
                "CacheControl": _CACHE_CONTROL,
                "Metadata": dict(metadata),
            },
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
        """``head_object`` -> ``ContentLength == expected_size``; ETag не используется.

        Перепакованный объект имеет другой размер: сверяем размер исходника из metadata.
        """
        response = self._client.head_object(Bucket=self._bucket, Key=key)
        length = int(response["ContentLength"])
        if length == expected_size:
            return True
        # Beget возвращает ключи metadata с заглавной буквы (Remuxed-From-Size).
        metadata = {k.lower(): v for k, v in (response.get("Metadata") or {}).items()}
        source_size = metadata.get(_REMUX_SOURCE_SIZE_KEY)
        return source_size == str(expected_size) and length > 0

    def close(self) -> None:
        """Закрывает пул соединений внутреннего boto3-клиента (graceful shutdown)."""
        self._client.close()


def _validate_ascii_metadata(metadata: Mapping[str, str]) -> None:
    for key, value in metadata.items():
        if not key.isascii() or not value.isascii():
            raise ValueError(f"x-amz-meta-{key}: ключ и значение должны быть ASCII ({value!r})")
