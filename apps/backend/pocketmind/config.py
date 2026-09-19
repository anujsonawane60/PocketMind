"""Paths and constants.

Two rules govern everything in this module:

1. No path is ever relative to the current working directory. PocketMind is
   launched from a USB drive, a shortcut, and a repo checkout, and all three
   must resolve to the same files.
2. Nothing personal is written to the host computer. The only thing PocketMind
   keeps outside the drive is the running process itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

APP_NAME = "PocketMind"
APP_VERSION = "0.2.0"
CONFIG_SCHEMA_VERSION = 1

PACKAGE_DIR = Path(__file__).resolve().parent
STATIC_DIR = PACKAGE_DIR / "static"

#: Folder created at the root of the user's drive.
INSTALL_DIRNAME = "PocketMind"

#: Every directory in a complete installation, in creation order.
INSTALL_FOLDERS = (
    "app",
    "runtime",
    "models",
    "data",
    "documents",
    "vault",
    "config",
    "logs",
    "backups",
    "launcher",
)

CONFIG_FILENAME = "pocketmind.json"
INSTALL_STATE_FILENAME = "install-state.json"
PROFILE_FILENAME = "profile.json"
SETTINGS_FILENAME = "settings.json"
DATABASE_FILENAME = "pocketmind.db"
VAULT_FILENAME = "encrypted.vault"
LAUNCHER_FILENAME = "START_POCKETMIND.cmd"
READ_ME_FILENAME = "README_START_HERE.html"

#: The local inference server. Bound to loopback only, never a public interface.
RUNTIME_HOST = "127.0.0.1"
RUNTIME_PORT = 8080
#: The PocketMind web UI.
SERVER_HOST = "127.0.0.1"
SERVER_PORT = 8000

#: Free space PocketMind refuses to consume, so the drive stays usable.
RESERVE_BYTES = 2 * 1024**3
#: Rough footprint of the llama.cpp CPU and Vulkan packages once unpacked.
RUNTIME_BUDGET_BYTES = 250 * 1024**2
#: Rough footprint of the bundled portable Python and its wheels.
PORTABLE_PYTHON_BUDGET_BYTES = 300 * 1024**2
#: Headroom for the database, documents, and RAG index as they grow.
WORKSPACE_BUDGET_BYTES = 1024**3

#: A drive slower than this makes model loading unpleasant (PRD section 58).
SLOW_DRIVE_MB_PER_SECOND = 25.0

#: Uploads larger than this are rejected before being read into memory.
MAX_UPLOAD_BYTES = 64 * 1024**2

#: The vault relocks itself after this much inactivity unless configured otherwise.
DEFAULT_VAULT_LOCK_SECONDS = 15 * 60


@dataclass(frozen=True)
class InstallPaths:
    """Every path inside one PocketMind installation, derived from its root."""

    root: Path

    @classmethod
    def for_mount(cls, mount_point: str | Path) -> InstallPaths:
        return cls(Path(mount_point) / INSTALL_DIRNAME)

    @property
    def app(self) -> Path:
        return self.root / "app"

    @property
    def runtime(self) -> Path:
        return self.root / "runtime"

    @property
    def portable_python(self) -> Path:
        return self.runtime / "python"

    @property
    def models(self) -> Path:
        return self.root / "models"

    @property
    def data(self) -> Path:
        return self.root / "data"

    @property
    def documents(self) -> Path:
        return self.root / "documents"

    @property
    def vault_dir(self) -> Path:
        return self.root / "vault"

    @property
    def config(self) -> Path:
        return self.root / "config"

    @property
    def logs(self) -> Path:
        return self.root / "logs"

    @property
    def backups(self) -> Path:
        return self.root / "backups"

    @property
    def launcher_dir(self) -> Path:
        return self.root / "launcher"

    @property
    def config_file(self) -> Path:
        """Presence of this file is what marks a drive as a PocketMind drive."""
        return self.config / CONFIG_FILENAME

    @property
    def install_state_file(self) -> Path:
        return self.config / INSTALL_STATE_FILENAME

    @property
    def settings_file(self) -> Path:
        return self.config / SETTINGS_FILENAME

    @property
    def profile_file(self) -> Path:
        return self.data / PROFILE_FILENAME

    @property
    def database(self) -> Path:
        return self.data / DATABASE_FILENAME

    @property
    def vault_file(self) -> Path:
        return self.vault_dir / VAULT_FILENAME

    @property
    def log_file(self) -> Path:
        return self.logs / "pocketmind.log"

    @property
    def launcher(self) -> Path:
        """Sits at the drive root so it is the first thing the user sees."""
        return self.root.parent / LAUNCHER_FILENAME

    @property
    def start_here(self) -> Path:
        return self.root / READ_ME_FILENAME

    def create_folders(self) -> None:
        for folder in INSTALL_FOLDERS:
            (self.root / folder).mkdir(parents=True, exist_ok=True)


def total_install_budget(model_bytes: int, *, include_portable_python: bool) -> int:
    """Bytes a drive must have free before an installation is safe to start."""
    budget = model_bytes + RUNTIME_BUDGET_BYTES + WORKSPACE_BUDGET_BYTES + RESERVE_BYTES
    if include_portable_python:
        budget += PORTABLE_PYTHON_BUDGET_BYTES
    return budget
