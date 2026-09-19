from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest

from pocketmind import config
from pocketmind.services.data import PocketDatabase
from pocketmind.services.vault import Vault


@pytest.fixture
def database(tmp_path: Path) -> PocketDatabase:
    db = PocketDatabase(tmp_path / "pocketmind.db")
    yield db
    db.close()


@pytest.fixture
def vault(tmp_path: Path) -> Vault:
    return Vault(tmp_path / "encrypted.vault")


@pytest.fixture
def installation(tmp_path: Path) -> config.InstallPaths:
    """A complete-looking PocketMind installation, minus the model and engine."""
    paths = config.InstallPaths(tmp_path / "drive" / config.INSTALL_DIRNAME)
    paths.create_folders()
    paths.config_file.write_text(
        json.dumps(
            {
                "schema_version": config.CONFIG_SCHEMA_VERSION,
                "app_version": config.APP_VERSION,
                "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
                "drive_id": "T:",
                "default_model_id": "qwen2.5-3b-instruct-q4_k_m",
                "backend": "cpu",
                "portable_python": False,
            }
        ),
        encoding="utf-8",
    )
    paths.profile_file.write_text(
        json.dumps({"display_name": "Alex", "use_cases": ["assistant", "coding"]}), encoding="utf-8"
    )
    yield paths
    shutil.rmtree(tmp_path / "drive", ignore_errors=True)


@pytest.fixture
def fake_install(monkeypatch, tmp_path: Path) -> Path:
    """Replace every network and subprocess call in the installer with a fake."""
    from pocketmind.services import installer
    from tests.fakes import FakeProvider

    FakeProvider.reset()
    monkeypatch.setattr(installer, "LlamaCppProvider", FakeProvider)
    monkeypatch.setattr(installer.portable_python, "install", lambda paths, **kwargs: Path("python.exe"))
    monkeypatch.setattr(installer.portable_python, "python_executable", lambda paths: Path("python.exe"))
    return tmp_path


@pytest.fixture
def bound_session(installation: config.InstallPaths):
    """The application session, opened against the temporary installation."""
    from pocketmind.services.session import session

    session.bind(installation.root)
    yield session
    session.unbind()
