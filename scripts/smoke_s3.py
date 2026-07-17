"""Ручная проверка против реального Beget S3 (вне pytest, вне [project.scripts]).

Запуск:
    uv run python scripts/smoke_s3.py

Читает реальные креды из .env (Settings), грузит маленький тестовый объект,
проверяет verify(), кладёт манифест — и удаляет тестовый объект в конце.
Ничего не оставляет после себя в бакете.
"""

import sys
import tempfile
import uuid
from pathlib import Path

import boto3
from botocore.config import Config

from video_uploader.config import Settings
from video_uploader.storage.s3_gateway import S3Gateway

_TEST_CONTENT = b"fs-video-uploader smoke test\n"


def main() -> None:
    settings = Settings()
    key = f"smoke-test/{uuid.uuid4().hex}.txt"
    manifest_key = f"{key}.json"

    gateway = S3Gateway(
        endpoint_url=settings.s3_endpoint_url,
        region=settings.s3_region,
        bucket=settings.s3_bucket,
        access_key=settings.s3_access_key,
        secret_key=settings.s3_secret_key.get_secret_value(),
    )

    with tempfile.TemporaryDirectory() as tmp_dir:
        test_file = Path(tmp_dir) / "smoke-test.txt"
        test_file.write_bytes(_TEST_CONTENT)

        print(f"[1/4] upload_video -> {key}")
        gateway.upload_video(test_file, key, metadata={"purpose": "smoke-test"})

        print(f"[2/4] put_manifest -> {manifest_key}")
        gateway.put_manifest(manifest_key, {"purpose": "smoke-test"})

        print("[3/4] verify")
        ok = gateway.verify(key, expected_size=len(_TEST_CONTENT))
        if not ok:
            print("verify() вернул False — размер объекта в S3 не совпал", file=sys.stderr)
            sys.exit(1)
        print("verify() OK: ContentLength совпадает")

    print("[4/4] удаление тестовых объектов")
    client = boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        region_name=settings.s3_region,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key.get_secret_value(),
        config=Config(s3={"addressing_style": "path"}),
    )
    client.delete_object(Bucket=settings.s3_bucket, Key=key)
    client.delete_object(Bucket=settings.s3_bucket, Key=manifest_key)

    print("Готово: Beget S3 доступен, upload/verify/manifest работают, тестовые объекты удалены.")


if __name__ == "__main__":
    main()
