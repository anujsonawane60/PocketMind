"""Resumable, verifiable downloads.

A model download is several gigabytes onto removable storage over a connection
that may drop. Every download therefore streams into a ``.part`` file, resumes
with a Range request when interrupted, reports progress, can be cancelled, and
is only moved into place after verification.
"""

from __future__ import annotations

import hashlib
import socket
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from pocketmind import config
from pocketmind.logs import get_logger

log = get_logger("downloads")

_USER_AGENT = f"PocketMind/{config.APP_VERSION}"
_CHUNK = 1024 * 1024
_READ_TIMEOUT = 60.0

ProgressCallback = Callable[[int, int | None, float], None]


class DownloadCancelled(RuntimeError):
    """Raised when the caller's cancel event is set mid-transfer."""


class DownloadFailed(RuntimeError):
    """Raised when every candidate URL and every retry has been exhausted."""


@dataclass
class DownloadResult:
    path: Path
    byte_size: int
    sha256: str | None
    resumed: bool


def is_online(timeout: float = 4.0) -> bool:
    """Cheap reachability check used to decide whether to offer downloads."""
    for host, port in (("huggingface.co", 443), ("1.1.1.1", 53)):
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except OSError:
            continue
    return False


def _open(url: str, offset: int) -> tuple[object, int | None, bool]:
    headers = {"User-Agent": _USER_AGENT, "Accept-Encoding": "identity"}
    if offset:
        headers["Range"] = f"bytes={offset}-"
    response = urlopen(Request(url, headers=headers), timeout=_READ_TIMEOUT)
    status = getattr(response, "status", 200)
    resumed = status == 206
    length = response.headers.get("Content-Length")
    total: int | None = None
    if length and length.isdigit():
        total = int(length) + (offset if resumed else 0)
    return response, total, resumed


def download(
    urls: Sequence[str],
    destination: Path,
    *,
    on_progress: ProgressCallback | None = None,
    cancel: threading.Event | None = None,
    expected_sha256: str | None = None,
    verify_gguf: bool = False,
    retries: int = 4,
) -> DownloadResult:
    """Fetch the first working URL into ``destination``, resuming if possible."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(destination.name + ".part")
    last_error: Exception | None = None

    for attempt in range(retries):
        for url in urls:
            if cancel is not None and cancel.is_set():
                raise DownloadCancelled("Download cancelled.")
            offset = partial.stat().st_size if partial.exists() else 0
            try:
                return _transfer(url, partial, destination, offset, on_progress, cancel, expected_sha256, verify_gguf)
            except DownloadCancelled:
                raise
            except (HTTPError, URLError, OSError, ValueError) as exc:
                last_error = exc
                log.warning(
                    "Download attempt %d failed (%s); %d bytes kept for resume",
                    attempt + 1,
                    exc.__class__.__name__,
                    partial.stat().st_size if partial.exists() else 0,
                )
        if cancel is not None and cancel.wait(min(2**attempt, 15)):
            raise DownloadCancelled("Download cancelled.")

    raise DownloadFailed(
        "The download could not be completed. Your progress is saved, so choosing Resume will "
        f"continue from where it stopped. Last error: {last_error.__class__.__name__ if last_error else 'unknown'}"
    )


def _transfer(
    url: str,
    partial: Path,
    destination: Path,
    offset: int,
    on_progress: ProgressCallback | None,
    cancel: threading.Event | None,
    expected_sha256: str | None,
    verify_gguf: bool,
) -> DownloadResult:
    response, total, resumed = _open(url, offset)
    if offset and not resumed:
        # Server ignored the Range header; start over rather than corrupt the file.
        log.info("Server did not honour resume; restarting the download")
        partial.unlink(missing_ok=True)
        offset = 0

    mode = "ab" if offset else "wb"
    done = offset
    started = time.monotonic()
    last_report = 0.0

    with response, partial.open(mode) as handle:
        while True:
            if cancel is not None and cancel.is_set():
                handle.flush()
                raise DownloadCancelled("Download cancelled.")
            chunk = response.read(_CHUNK)  # type: ignore[attr-defined]
            if not chunk:
                break
            handle.write(chunk)
            done += len(chunk)
            now = time.monotonic()
            if on_progress and now - last_report >= 0.4:
                elapsed = max(now - started, 1e-6)
                speed = (done - offset) / elapsed
                on_progress(done, total, speed)
                last_report = now

    if total is not None and done < total:
        raise OSError(f"Transfer ended early: {done} of {total} bytes")

    digest = _verify(partial, expected_sha256, verify_gguf)
    partial.replace(destination)
    if on_progress:
        on_progress(done, total or done, 0.0)
    return DownloadResult(path=destination, byte_size=done, sha256=digest, resumed=bool(offset))


def _verify(path: Path, expected_sha256: str | None, verify_gguf: bool) -> str | None:
    if verify_gguf:
        with path.open("rb") as handle:
            magic = handle.read(4)
        if magic != b"GGUF":
            path.unlink(missing_ok=True)
            raise ValueError("The downloaded file is not a valid GGUF model. It has been discarded.")

    if not expected_sha256:
        return None

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK):
            digest.update(chunk)
    actual = digest.hexdigest()
    if actual.lower() != expected_sha256.lower():
        path.unlink(missing_ok=True)
        raise ValueError("The downloaded file did not match its published checksum. It has been discarded.")
    return actual


def partial_bytes(destination: Path) -> int:
    partial = destination.with_name(destination.name + ".part")
    return partial.stat().st_size if partial.exists() else 0
