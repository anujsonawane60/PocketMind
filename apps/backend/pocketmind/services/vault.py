"""The encrypted secret vault.

Design decisions worth stating plainly:

* The master password is never stored, never logged, and never written to the
  drive. Only an Argon2id salt and the parameters needed to re-derive the key
  are persisted.
* Entry *names* are encrypted along with their values. A name like
  "bank recovery codes" is itself sensitive, so the whole entry list is one
  AEAD payload. Only the number of entries is readable while locked, so the
  dashboard can show a count.
* Vault contents are never placed in the model's context. Nothing in this
  module is reachable from prompt construction.
* Writes are atomic with a retained backup, because the drive can be removed
  mid-write.
"""

from __future__ import annotations

import base64
import hmac
import json
import os
import secrets
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from argon2.low_level import Type, hash_secret_raw
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from pocketmind import config
from pocketmind.logs import get_logger
from pocketmind.schemas import VaultEntry, VaultState, VaultStatus

log = get_logger("vault")

FORMAT_VERSION = 2

# Argon2id parameters. 64 MiB keeps unlocking under a second on a laptop while
# making offline guessing against a stolen drive expensive.
_TIME_COST = 3
_MEMORY_COST_KIB = 64 * 1024
_PARALLELISM = 4
_KEY_LENGTH = 32


class VaultLocked(PermissionError):
    """An operation needs an unlocked vault."""


class VaultAuthError(PermissionError):
    """The password or session token did not match."""


class VaultExists(ValueError):
    """A vault is already present at this location."""


class VaultMissing(FileNotFoundError):
    """No vault has been created yet."""


@dataclass
class _Entry:
    name: str
    value: str
    note: str
    created_at: str
    updated_at: str

    def to_json(self) -> dict[str, str]:
        return {
            "name": self.name,
            "value": self.value,
            "note": self.note,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_json(cls, raw: dict) -> _Entry:
        stamp = str(raw.get("created_at") or _now())
        return cls(
            name=str(raw["name"]),
            value=str(raw["value"]),
            note=str(raw.get("note") or ""),
            created_at=stamp,
            updated_at=str(raw.get("updated_at") or stamp),
        )


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.b64decode(text.encode("ascii"))


def _derive(password: str, salt: bytes, params: dict) -> bytes:
    return hash_secret_raw(
        secret=password.encode("utf-8"),
        salt=salt,
        time_cost=int(params.get("time_cost", _TIME_COST)),
        memory_cost=int(params.get("memory_cost", _MEMORY_COST_KIB)),
        parallelism=int(params.get("parallelism", _PARALLELISM)),
        hash_len=int(params.get("length", _KEY_LENGTH)),
        type=Type.ID,
    )


def password_strength(password: str) -> tuple[str, list[str]]:
    """A description the setup screen can show, plus concrete suggestions."""
    suggestions: list[str] = []
    score = 0
    if len(password) >= 12:
        score += 1
    if len(password) >= 16:
        score += 1
    else:
        suggestions.append("Longer is stronger — aim for 16 characters or a short sentence.")
    if any(character.islower() for character in password) and any(character.isupper() for character in password):
        score += 1
    else:
        suggestions.append("Mix upper and lower case.")
    if any(character.isdigit() for character in password):
        score += 1
    else:
        suggestions.append("Add a number.")
    if any(not character.isalnum() for character in password):
        score += 1
    else:
        suggestions.append("Add a symbol or a space.")

    label = {0: "Very weak", 1: "Very weak", 2: "Weak", 3: "Fair", 4: "Strong", 5: "Very strong"}[score]
    return label, suggestions


class Vault:
    """Password-protected storage for credentials, kept apart from AI memory."""

    def __init__(self, path: Path, *, lock_timeout_seconds: int = config.DEFAULT_VAULT_LOCK_SECONDS) -> None:
        self.path = path
        self.lock_timeout_seconds = lock_timeout_seconds
        self._lock = threading.RLock()
        self._key: bytes | None = None
        self._session_token: str | None = None
        self._last_used: float = 0.0

    # -- state -------------------------------------------------------------

    def exists(self) -> bool:
        return self.path.exists()

    def _read_file(self) -> dict:
        if not self.exists():
            raise VaultMissing("No vault has been created on this drive yet.")
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            backup = self.path.with_suffix(self.path.suffix + ".bak")
            if backup.exists():
                log.warning("Vault file unreadable; falling back to the previous good copy")
                return json.loads(backup.read_text(encoding="utf-8"))
            raise VaultMissing("The vault file on this drive is damaged and no backup was found.") from exc

    def _expired(self) -> bool:
        if self._key is None or self.lock_timeout_seconds <= 0:
            return False
        return (time.monotonic() - self._last_used) > self.lock_timeout_seconds

    def status(self) -> VaultStatus:
        with self._lock:
            if self._expired():
                log.info("Vault auto-locked after inactivity")
                self._clear()
            if not self.exists():
                return VaultStatus(state=VaultState.ABSENT, lock_timeout_seconds=self.lock_timeout_seconds)
            count = 0
            try:
                count = int(self._read_file().get("entry_count", 0))
            except (VaultMissing, ValueError):
                pass
            if self._key is None:
                return VaultStatus(
                    state=VaultState.LOCKED, secret_count=count, lock_timeout_seconds=self.lock_timeout_seconds
                )
            remaining = int(max(self.lock_timeout_seconds - (time.monotonic() - self._last_used), 0))
            return VaultStatus(
                state=VaultState.UNLOCKED,
                secret_count=count,
                lock_timeout_seconds=self.lock_timeout_seconds,
                seconds_until_lock=remaining if self.lock_timeout_seconds > 0 else None,
            )

    def _clear(self) -> None:
        self._key = None
        self._session_token = None
        self._last_used = 0.0

    def lock(self) -> None:
        with self._lock:
            self._clear()

    def authorise(self, session_token: str | None) -> None:
        """Gate for every operation that touches decrypted content."""
        with self._lock:
            if self._expired():
                self._clear()
            if self._key is None or self._session_token is None:
                raise VaultLocked("The vault is locked. Unlock it with your master password.")
            if not session_token or not hmac.compare_digest(session_token, self._session_token):
                raise VaultAuthError("This session is not authorised to use the vault.")
            self._last_used = time.monotonic()

    # -- lifecycle ---------------------------------------------------------

    def create(self, password: str) -> str:
        with self._lock:
            if self.exists():
                raise VaultExists("A vault already exists on this drive.")
            salt = os.urandom(16)
            params = {
                "algorithm": "argon2id",
                "salt": _b64(salt),
                "time_cost": _TIME_COST,
                "memory_cost": _MEMORY_COST_KIB,
                "parallelism": _PARALLELISM,
                "length": _KEY_LENGTH,
            }
            key = _derive(password, salt, params)
            self._write(key, params, [])
            self._key = key
            self._session_token = secrets.token_urlsafe(32)
            self._last_used = time.monotonic()
            log.info("Vault created")
            return self._session_token

    def unlock(self, password: str) -> str:
        with self._lock:
            payload = self._read_file()
            params = payload["kdf"]
            key = _derive(password, _unb64(params["salt"]), params)
            try:
                self._decrypt(key, payload)
            except InvalidTag as exc:
                log.warning("Vault unlock rejected")
                raise VaultAuthError("That master password is not correct.") from exc
            self._key = key
            self._session_token = secrets.token_urlsafe(32)
            self._last_used = time.monotonic()
            log.info("Vault unlocked")
            return self._session_token

    def change_password(self, current_password: str, new_password: str) -> str:
        with self._lock:
            payload = self._read_file()
            params = payload["kdf"]
            old_key = _derive(current_password, _unb64(params["salt"]), params)
            try:
                entries = self._decrypt(old_key, payload)
            except InvalidTag as exc:
                raise VaultAuthError("That master password is not correct.") from exc

            salt = os.urandom(16)
            new_params = {
                "algorithm": "argon2id",
                "salt": _b64(salt),
                "time_cost": _TIME_COST,
                "memory_cost": _MEMORY_COST_KIB,
                "parallelism": _PARALLELISM,
                "length": _KEY_LENGTH,
            }
            new_key = _derive(new_password, salt, new_params)
            self._write(new_key, new_params, entries)
            self._key = new_key
            self._session_token = secrets.token_urlsafe(32)
            self._last_used = time.monotonic()
            log.info("Vault master password changed")
            return self._session_token

    # -- entries -----------------------------------------------------------

    def _entries(self) -> list[_Entry]:
        assert self._key is not None
        return self._decrypt(self._key, self._read_file())

    def _persist(self, entries: list[_Entry]) -> None:
        assert self._key is not None
        self._write(self._key, self._read_file()["kdf"], entries)

    def list_entries(self, session_token: str | None) -> list[VaultEntry]:
        self.authorise(session_token)
        with self._lock:
            return [
                VaultEntry(name=entry.name, note=entry.note, created_at=entry.created_at, updated_at=entry.updated_at)
                for entry in sorted(self._entries(), key=lambda item: item.name.lower())
            ]

    def add(self, session_token: str | None, name: str, value: str, note: str = "") -> None:
        self.authorise(session_token)
        with self._lock:
            entries = self._entries()
            stamp = _now()
            for entry in entries:
                if entry.name.lower() == name.lower():
                    entry.value, entry.note, entry.updated_at = value, note, stamp
                    break
            else:
                entries.append(_Entry(name=name, value=value, note=note, created_at=stamp, updated_at=stamp))
            self._persist(entries)
            log.info("Vault entry stored")

    def reveal(self, session_token: str | None, name: str) -> tuple[str, str]:
        """Return one secret's value. Callers must not pass this to the model."""
        self.authorise(session_token)
        with self._lock:
            for entry in self._entries():
                if entry.name.lower() == name.lower():
                    log.info("Vault entry revealed to the user interface")
                    return entry.value, entry.note
            raise KeyError(name)

    def delete(self, session_token: str | None, name: str) -> bool:
        self.authorise(session_token)
        with self._lock:
            entries = self._entries()
            remaining = [entry for entry in entries if entry.name.lower() != name.lower()]
            if len(remaining) == len(entries):
                return False
            self._persist(remaining)
            log.info("Vault entry deleted")
            return True

    # -- crypto ------------------------------------------------------------

    @staticmethod
    def _aad(params: dict) -> bytes:
        """Bind the ciphertext to its KDF parameters so they cannot be swapped."""
        return json.dumps({"v": FORMAT_VERSION, "kdf": params}, sort_keys=True).encode("utf-8")

    def _decrypt(self, key: bytes, payload: dict) -> list[_Entry]:
        blob = payload["payload"]
        plaintext = AESGCM(key).decrypt(
            _unb64(blob["nonce"]), _unb64(blob["ciphertext"]), self._aad(payload["kdf"])
        )
        return [_Entry.from_json(item) for item in json.loads(plaintext.decode("utf-8"))]

    def _write(self, key: bytes, params: dict, entries: list[_Entry]) -> None:
        nonce = os.urandom(12)
        plaintext = json.dumps([entry.to_json() for entry in entries]).encode("utf-8")
        ciphertext = AESGCM(key).encrypt(nonce, plaintext, self._aad(params))
        document = {
            "version": FORMAT_VERSION,
            "kdf": params,
            "entry_count": len(entries),
            "payload": {"nonce": _b64(nonce), "ciphertext": _b64(ciphertext)},
            "updated_at": _now(),
        }
        _atomic_write(self.path, json.dumps(document, indent=2))


def _atomic_write(path: Path, text: str) -> None:
    """Write via a temporary file, keeping the previous version as a backup.

    Removable drives get unplugged. A half-written vault must never be the only
    copy, so the old file is preserved until the new one is safely in place.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    if path.exists():
        backup = path.with_suffix(path.suffix + ".bak")
        backup.unlink(missing_ok=True)
        try:
            path.replace(backup)
        except OSError:
            log.warning("Could not refresh the vault backup copy")
    temporary.replace(path)
