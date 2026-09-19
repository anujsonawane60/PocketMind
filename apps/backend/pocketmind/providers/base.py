"""The runtime interface PocketMind depends on (PRD section 68)."""

from __future__ import annotations

import threading
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from pocketmind.schemas import HardwareProfile, RuntimeStatus


class RuntimeError_(RuntimeError):
    """A runtime problem phrased for the person using PocketMind."""

    def __init__(self, message: str, *, hint: str = "") -> None:
        super().__init__(message)
        self.hint = hint


@dataclass(frozen=True)
class InstalledModel:
    id: str
    name: str
    path: Path
    byte_size: int
    is_default: bool = False


@runtime_checkable
class LLMProvider(Protocol):
    """Everything the application needs from a local model runtime."""

    name: str

    def discover_models(self, *, online: bool) -> Sequence[object]:
        """Models this provider could install, as standardised metadata."""

    def installed_models(self) -> list[InstalledModel]:
        """Models already present on the drive."""

    def install_runtime(
        self,
        hardware: HardwareProfile,
        *,
        on_progress: object | None = None,
        cancel: threading.Event | None = None,
    ) -> str:
        """Place the inference engine on the drive. Returns the backend name."""

    def install_model(
        self,
        model_id: str,
        *,
        on_progress: object | None = None,
        cancel: threading.Event | None = None,
    ) -> InstalledModel:
        """Download and verify one model onto the drive."""

    def remove_model(self, model_id: str) -> None:
        ...

    def start_runtime(self, model_id: str | None = None, *, context_length: int | None = None) -> RuntimeStatus:
        ...

    def stop_runtime(self) -> None:
        ...

    def health_check(self) -> bool:
        ...

    def status(self) -> RuntimeStatus:
        ...

    def chat(self, messages: Sequence[dict[str, str]], **options: object) -> str:
        ...

    def stream_chat(self, messages: Sequence[dict[str, str]], **options: object) -> Iterator[str]:
        ...
