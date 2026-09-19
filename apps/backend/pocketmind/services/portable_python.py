"""Put a self-contained Python on the drive.

This is what turns the drive from "data + model" into something that runs on a
computer where PocketMind was never installed. It uses the official Windows
embeddable distribution, enables ``site`` so pip works, installs PocketMind's
dependencies into it, and verifies the result by importing them.

If any of this fails the installation still succeeds: the launcher falls back
to a Python already on the host, and the user is told which mode they got.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import threading
import zipfile
from collections.abc import Callable
from pathlib import Path

from pocketmind import config
from pocketmind.logs import get_logger
from pocketmind.services import downloads

log = get_logger("portable-python")

# Pinned so a drive built today behaves the same next month. Listed newest
# first; the first version that downloads is used.
_PYTHON_VERSIONS = ("3.12.10", "3.12.9", "3.12.8")
_GET_PIP = "https://bootstrap.pypa.io/get-pip.py"
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

_REQUIREMENTS = (
    "fastapi>=0.115,<1",
    "uvicorn>=0.30,<1",
    "psutil>=6,<8",
    "cryptography>=43,<47",
    "argon2-cffi>=23,<26",
    "python-multipart>=0.0.20,<1",
    "pypdf>=5,<7",
)

_IMPORT_CHECK = "import fastapi, uvicorn, psutil, cryptography, argon2, pypdf, multipart"

ProgressCallback = Callable[[str, float, str], None]


class PortablePythonError(RuntimeError):
    """Bundling failed; the caller should fall back to host Python."""


def python_executable(paths: config.InstallPaths) -> Path | None:
    candidate = paths.portable_python / "python.exe"
    return candidate if candidate.exists() else None


def is_ready(paths: config.InstallPaths) -> bool:
    executable = python_executable(paths)
    if executable is None:
        return False
    return _run(executable, ["-c", _IMPORT_CHECK], timeout=90) is not None


def install(
    paths: config.InstallPaths,
    *,
    on_progress: ProgressCallback | None = None,
    cancel: threading.Event | None = None,
) -> Path:
    """Download and prepare a portable Python. Returns its executable path."""
    target = paths.portable_python
    if is_ready(paths):
        log.info("Portable Python already present and working")
        return python_executable(paths)  # type: ignore[return-value]

    _report(on_progress, "Downloading a portable Python for the drive", 0.05, "")
    archive = paths.runtime / "python-embed.zip"
    urls = [
        f"https://www.python.org/ftp/python/{version}/python-{version}-embed-amd64.zip"
        for version in _PYTHON_VERSIONS
    ]

    def progress(done: int, total: int | None, speed: float) -> None:
        fraction = (done / total) if total else 0.0
        _report(on_progress, "Downloading a portable Python for the drive", 0.05 + fraction * 0.2, "")

    try:
        downloads.download(urls, archive, on_progress=progress, cancel=cancel)
    except downloads.DownloadCancelled:
        raise
    except Exception as exc:
        raise PortablePythonError(f"Could not download a portable Python ({exc.__class__.__name__}).") from exc

    if target.exists():
        shutil.rmtree(target, ignore_errors=True)
    target.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(archive) as package:
            package.extractall(target)
    except (zipfile.BadZipFile, OSError) as exc:
        raise PortablePythonError("The portable Python download was damaged.") from exc
    finally:
        archive.unlink(missing_ok=True)

    _enable_site_packages(target)

    _report(on_progress, "Preparing the portable Python", 0.3, "Installing the package manager")
    executable = target / "python.exe"
    if not executable.exists():
        raise PortablePythonError("The portable Python archive did not contain python.exe.")

    get_pip = target / "get-pip.py"
    try:
        downloads.download([_GET_PIP], get_pip, cancel=cancel)
    except Exception as exc:
        raise PortablePythonError(f"Could not download the package manager ({exc.__class__.__name__}).") from exc

    if _run(executable, [str(get_pip), "--no-warn-script-location"], timeout=300) is None:
        raise PortablePythonError("The package manager could not be installed into the portable Python.")
    get_pip.unlink(missing_ok=True)

    _report(on_progress, "Installing PocketMind's dependencies onto the drive", 0.45, "This takes a minute or two")
    arguments = ["-m", "pip", "install", "--no-warn-script-location", "--disable-pip-version-check", *_REQUIREMENTS]
    if _run(executable, arguments, timeout=900) is None:
        raise PortablePythonError("PocketMind's dependencies could not be installed into the portable Python.")

    _report(on_progress, "Checking the portable Python", 0.95, "")
    if _run(executable, ["-c", _IMPORT_CHECK], timeout=120) is None:
        raise PortablePythonError("The portable Python was built but could not load PocketMind's dependencies.")

    log.info("Portable Python ready at %s", executable)
    _report(on_progress, "Portable Python ready", 1.0, "")
    return executable


def _enable_site_packages(target: Path) -> None:
    """The embeddable build ships with ``import site`` commented out.

    Without it there is no ``site-packages`` on the path, so pip installs
    succeed and then nothing can be imported.
    """
    for pth in target.glob("python*._pth"):
        lines = pth.read_text(encoding="utf-8").splitlines()
        rewritten: list[str] = []
        for line in lines:
            stripped = line.strip()
            rewritten.append("import site" if stripped == "#import site" else line)
        if "import site" not in [line.strip() for line in rewritten]:
            rewritten.append("import site")
        if "Lib\\site-packages" not in rewritten:
            rewritten.insert(len(rewritten) - 1, "Lib\\site-packages")
        # The application package sits two levels up, at <root>/app.
        if "..\\..\\app" not in rewritten:
            rewritten.insert(len(rewritten) - 1, "..\\..\\app")
        pth.write_text("\n".join(rewritten) + "\n", encoding="utf-8")
        log.info("Enabled site-packages in %s", pth.name)

    (target / "Lib" / "site-packages").mkdir(parents=True, exist_ok=True)


def _run(executable: Path, arguments: list[str], *, timeout: float) -> str | None:
    environment = dict(os.environ)
    # Keep the host's Python configuration from leaking into the drive's copy.
    for variable in ("PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP"):
        environment.pop(variable, None)
    try:
        result = subprocess.run(
            [str(executable), *arguments],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=True,
            cwd=str(executable.parent),
            env=environment,
            creationflags=_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        detail = getattr(exc, "stderr", "") or ""
        log.warning("Portable Python command failed: %s %s", exc.__class__.__name__, detail.strip()[:300])
        return None
    return result.stdout


def _report(callback: ProgressCallback | None, title: str, fraction: float, detail: str) -> None:
    if callback is not None:
        callback(title, max(0.0, min(fraction, 1.0)), detail)
