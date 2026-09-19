"""The running application's state.

PocketMind has two modes and works out which one it is in by looking at the
connected drives, not at anything stored on the host computer:

* No drive carries an installation -> setup mode, show the wizard.
* A drive does -> ready mode, open it and go straight to chat.

Binding an installation opens its database, vault, and model runtime. Unbinding
closes all three so the drive can be ejected safely.
"""

from __future__ import annotations

import json
import shutil
import threading
import time
from datetime import datetime
from pathlib import Path

from pocketmind import config
from pocketmind.logs import configure as configure_logging
from pocketmind.logs import get_logger
from pocketmind.providers.llamacpp import LlamaCppProvider
from pocketmind.schemas import (
    AppMode,
    AppState,
    Drive,
    InstallationSummary,
    NetworkStatus,
    RuntimeStatus,
    Settings,
    VaultState,
    VaultStatus,
)
from pocketmind.services import assistant, downloads, drives, hardware
from pocketmind.services.data import PocketDatabase
from pocketmind.services.installer import InstallJob
from pocketmind.services.vault import Vault

log = get_logger("session")


class SessionNotReady(RuntimeError):
    """No PocketMind drive is connected and opened."""


class DriveDisconnected(RuntimeError):
    """The drive was removed while PocketMind was using it."""


class AppSession:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.paths: config.InstallPaths | None = None
        self.database: PocketDatabase | None = None
        self.vault: Vault | None = None
        self.provider: LlamaCppProvider | None = None
        self.profile: dict = {}
        self.install_job: InstallJob | None = None
        self._config: dict = {}
        self._online: bool | None = None
        self._online_checked_at = 0.0

    # -- discovery ---------------------------------------------------------

    @staticmethod
    def discover() -> list[InstallationSummary]:
        """Installations on currently connected drives."""
        summaries: list[InstallationSummary] = []
        for drive in drives.find_installations():
            paths = config.InstallPaths.for_mount(drive.mount_point)
            data = _read_json(paths.config_file)
            profile = _read_json(paths.profile_file)
            summaries.append(
                InstallationSummary(
                    root=str(paths.root),
                    drive_id=drive.id,
                    drive_label=drive.label,
                    display_name=profile.get("display_name"),
                    model_name=data.get("default_model_id"),
                    created_at=_parse_time(data.get("created_at")),
                    drive_connected=True,
                )
            )
        return summaries

    def autobind(self) -> InstallationSummary | None:
        """Open the only connected installation, if there is exactly one."""
        found = self.discover()
        if len(found) == 1:
            return self.bind(found[0].root)
        return None

    # -- binding -----------------------------------------------------------

    def bind(self, root: str | Path) -> InstallationSummary:
        root_path = Path(root)
        paths = config.InstallPaths(root_path)
        if not paths.config_file.exists():
            raise SessionNotReady(f"{root_path} does not contain a PocketMind installation.")

        with self._lock:
            self._release()
            configure_logging(paths.log_file)
            self.paths = paths
            self._config = _read_json(paths.config_file)
            self.profile = assistant.load_profile(paths.profile_file)
            self.database = PocketDatabase(paths.database)
            settings = self.database.load_settings()
            self.vault = Vault(paths.vault_file, lock_timeout_seconds=settings.vault_lock_seconds)
            self.provider = LlamaCppProvider(paths, hardware.inspect_hardware())
            log.info("Opened the PocketMind installation at %s", paths.root)

        drive = drives.get_drive(Path(paths.root).drive.upper())
        return InstallationSummary(
            root=str(paths.root),
            drive_id=Path(paths.root).drive.upper(),
            drive_label=drive.label if drive else None,
            display_name=self.profile.get("display_name"),
            model_name=self._config.get("default_model_id"),
            created_at=_parse_time(self._config.get("created_at")),
            drive_connected=True,
        )

    def unbind(self) -> None:
        with self._lock:
            self._release()
            log.info("Closed the PocketMind installation")

    def _release(self) -> None:
        if self.provider is not None:
            self.provider.stop_runtime()
        if self.vault is not None:
            self.vault.lock()
        if self.database is not None:
            self.database.close()
        self.paths = None
        self.database = None
        self.vault = None
        self.provider = None
        self.profile = {}
        self._config = {}

    def shutdown(self) -> None:
        with self._lock:
            if self.install_job is not None:
                self.install_job.cancel()
            self._release()

    # -- accessors ---------------------------------------------------------

    @property
    def is_ready(self) -> bool:
        return self.paths is not None and self.database is not None

    def require(self) -> tuple[config.InstallPaths, PocketDatabase, Vault, LlamaCppProvider]:
        """Fetch the bound installation, or explain why there isn't one."""
        with self._lock:
            if not (self.paths and self.database and self.vault and self.provider):
                raise SessionNotReady(
                    "No PocketMind drive is open. Connect your drive and reopen it from the welcome screen."
                )
            if not self.paths.config_file.exists():
                self._release()
                raise DriveDisconnected(
                    "The PocketMind drive was removed. Reconnect it, then reopen it from the welcome screen."
                )
            return self.paths, self.database, self.vault, self.provider

    def settings(self) -> Settings:
        _, database, _, _ = self.require()
        return database.load_settings()

    def save_settings(self, settings: Settings) -> Settings:
        _, database, vault, _ = self.require()
        saved = database.save_settings(settings)
        vault.lock_timeout_seconds = saved.vault_lock_seconds
        return saved

    def is_online(self, *, max_age_seconds: float = 30.0) -> bool:
        now = time.monotonic()
        if self._online is None or now - self._online_checked_at > max_age_seconds:
            self._online = downloads.is_online()
            self._online_checked_at = now
        return bool(self._online)

    def network_status(self) -> NetworkStatus:
        allowed = True
        if self.is_ready:
            try:
                allowed = self.settings().network_allowed
            except SessionNotReady:
                allowed = True
        return NetworkStatus(
            allowed=allowed,
            online=self.is_online() if allowed else False,
            used_for=["Model downloads", "Application updates"] if allowed else [],
            telemetry=False,
        )

    def runtime_status(self) -> RuntimeStatus:
        if self.provider is None:
            return RuntimeStatus(detail="No drive is open")
        return self.provider.status()

    def vault_status(self) -> VaultStatus:
        if self.vault is None:
            return VaultStatus(state=VaultState.ABSENT)
        return self.vault.status()

    def state(self) -> AppState:
        ready = self.is_ready
        installation: InstallationSummary | None = None
        if ready and self.paths is not None:
            drive_id = Path(self.paths.root).drive.upper()
            drive = drives.get_drive(drive_id)
            installation = InstallationSummary(
                root=str(self.paths.root),
                drive_id=drive_id,
                drive_label=drive.label if drive else None,
                display_name=self.profile.get("display_name"),
                model_name=self._config.get("default_model_id"),
                created_at=_parse_time(self._config.get("created_at")),
                drive_connected=self.paths.config_file.exists(),
            )

        tutorial_seen = bool(self._config.get("tutorial_seen"))
        return AppState(
            mode=AppMode.READY if ready else AppMode.SETUP,
            version=config.APP_VERSION,
            installation=installation,
            candidates=self.discover(),
            vault=self.vault_status(),
            runtime=self.runtime_status(),
            network=self.network_status(),
            onboarding_complete=ready,
            tutorial_seen=tutorial_seen,
        )

    def mark_tutorial_seen(self) -> None:
        paths, _, _, _ = self.require()
        self._config["tutorial_seen"] = True
        temporary = paths.config_file.with_suffix(".tmp")
        temporary.write_text(json.dumps(self._config, indent=2), encoding="utf-8")
        temporary.replace(paths.config_file)

    # -- storage -----------------------------------------------------------

    def storage_usage(self) -> tuple[int, int, int]:
        """(bytes used by PocketMind, drive used, drive total)."""
        paths, _, _, _ = self.require()
        total_size = 0
        for path in paths.root.rglob("*"):
            try:
                if path.is_file():
                    total_size += path.stat().st_size
            except OSError:
                continue
        usage = shutil.disk_usage(paths.root)
        return total_size, usage.used, usage.total

    def drive(self) -> Drive | None:
        if self.paths is None:
            return None
        return drives.get_drive(Path(self.paths.root).drive.upper())


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


#: The application's single session, created at import time and wired up on startup.
session = AppSession()
