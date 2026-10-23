"""Перепаковка mp4/mov с ``moov`` в начало файла (faststart) перед загрузкой в S3.

OBS пишет ``moov`` в конец файла: браузеру для показа длительности приходится читать хвост,
а перемотка порождает лишние Range-запросы. ``ffmpeg -c copy -movflags +faststart`` только
переставляет атомы — без перекодирования и потери качества.
"""

import logging
import shutil
import struct
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

logger = logging.getLogger(__name__)

FASTSTART_EXTENSIONS = frozenset({".mp4", ".m4v", ".mov"})
_REMUX_TIMEOUT_SECONDS = 30 * 60
_BOX_HEADER_SIZE = 8
_LARGE_BOX_SIZE_FIELD = 1


def needs_faststart(path: Path) -> bool:
    """``True``, если ``mdat`` идёт раньше ``moov``; нераспознанный файл — ``False``."""
    if path.suffix.lower() not in FASTSTART_EXTENSIONS:
        return False
    try:
        with path.open("rb") as file:
            file_size = path.stat().st_size
            offset = 0
            while offset + _BOX_HEADER_SIZE <= file_size:
                file.seek(offset)
                size, box_type = struct.unpack(">I4s", file.read(_BOX_HEADER_SIZE))
                if box_type == b"moov":
                    return False
                if box_type == b"mdat":
                    return True
                if size == _LARGE_BOX_SIZE_FIELD:
                    size = struct.unpack(">Q", file.read(8))[0]
                if size < _BOX_HEADER_SIZE:
                    return False
                offset += size
    except (OSError, struct.error):
        return False
    return False


@contextmanager
def faststart_copy(path: Path, work_dir: Path) -> Iterator[Path | None]:
    """Отдаёт путь к перепакованной копии во временной папке или ``None``, если копия не нужна.

    Нет ``ffmpeg`` или он упал — ``None`` и предупреждение: загрузится исходный файл.
    Временная копия удаляется при выходе из блока.
    """
    if not needs_faststart(path):
        yield None
        return

    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        logger.warning("ffmpeg не найден, загружаем без faststart: %s", path)
        yield None
        return

    work_dir.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=work_dir) as tmp:
        target = Path(tmp) / f"remux{path.suffix.lower()}"
        command = [
            ffmpeg, "-nostdin", "-v", "error", "-y",
            "-i", str(path), "-c", "copy", "-movflags", "+faststart", str(target),
        ]  # fmt: skip
        try:
            subprocess.run(command, check=True, capture_output=True, timeout=_REMUX_TIMEOUT_SECONDS)
        except (subprocess.SubprocessError, OSError) as exc:
            stderr = getattr(exc, "stderr", b"") or b""
            logger.warning(
                "faststart не удался, загружаем исходный файл: %s (%s %s)",
                path,
                exc,
                stderr.decode("utf-8", "replace")[-300:],
                extra={"event": "faststart_failed"},
            )
            yield None
            return
        logger.info("файл перепакован с faststart: %s", path, extra={"event": "faststart_done"})
        yield target
