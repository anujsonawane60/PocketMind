"""The secret vault.

Every route here requires the session token issued at unlock, and none of them
is reachable from prompt construction. Secret values are returned only to the
browser, only on explicit request, and are never written to the log.
"""

from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException

from pocketmind.schemas import (
    VaultChangePasswordRequest,
    VaultEntry,
    VaultPasswordRequest,
    VaultSecretRequest,
    VaultSecretValue,
    VaultStatus,
    VaultUnlockResponse,
)
from pocketmind.services.session import session
from pocketmind.services.vault import password_strength

router = APIRouter(prefix="/api/vault", tags=["vault"])

_SESSION_HEADER = "X-Vault-Session"


@router.get("/status", response_model=VaultStatus)
def status() -> VaultStatus:
    return session.vault_status()


@router.post("/create", response_model=VaultUnlockResponse, status_code=201)
def create(request: VaultPasswordRequest) -> VaultUnlockResponse:
    _, _, vault, _ = session.require()
    label, suggestions = password_strength(request.password)
    if label in {"Very weak", "Weak"}:
        raise HTTPException(400, "Choose a stronger master password. " + " ".join(suggestions))
    token = vault.create(request.password)
    return VaultUnlockResponse(session_token=token, lock_timeout_seconds=vault.lock_timeout_seconds)


@router.post("/unlock", response_model=VaultUnlockResponse)
def unlock(request: VaultPasswordRequest) -> VaultUnlockResponse:
    _, _, vault, _ = session.require()
    token = vault.unlock(request.password)
    return VaultUnlockResponse(session_token=token, lock_timeout_seconds=vault.lock_timeout_seconds)


@router.post("/lock", response_model=VaultStatus)
def lock() -> VaultStatus:
    _, _, vault, _ = session.require()
    vault.lock()
    return vault.status()


@router.post("/change-password", response_model=VaultUnlockResponse)
def change_password(request: VaultChangePasswordRequest) -> VaultUnlockResponse:
    _, _, vault, _ = session.require()
    label, suggestions = password_strength(request.new_password)
    if label in {"Very weak", "Weak"}:
        raise HTTPException(400, "Choose a stronger master password. " + " ".join(suggestions))
    token = vault.change_password(request.current_password, request.new_password)
    return VaultUnlockResponse(session_token=token, lock_timeout_seconds=vault.lock_timeout_seconds)


@router.get("/entries", response_model=list[VaultEntry])
def entries(x_vault_session: str | None = Header(default=None, alias=_SESSION_HEADER)) -> list[VaultEntry]:
    _, _, vault, _ = session.require()
    return vault.list_entries(x_vault_session)


@router.post("/entries", status_code=201)
def add_entry(
    request: VaultSecretRequest,
    x_vault_session: str | None = Header(default=None, alias=_SESSION_HEADER),
) -> dict[str, str]:
    _, _, vault, _ = session.require()
    vault.add(x_vault_session, request.name, request.value, request.note)
    return {"status": "stored"}


@router.post("/entries/{name}/reveal", response_model=VaultSecretValue)
def reveal(
    name: str,
    x_vault_session: str | None = Header(default=None, alias=_SESSION_HEADER),
) -> VaultSecretValue:
    """Show one secret to the user. The assistant never sees this response."""
    _, _, vault, _ = session.require()
    try:
        value, note = vault.reveal(x_vault_session, name)
    except KeyError as exc:
        raise HTTPException(404, "No secret with that name is stored in your vault.") from exc
    return VaultSecretValue(name=name, value=value, note=note)


@router.delete("/entries/{name}")
def delete_entry(
    name: str,
    x_vault_session: str | None = Header(default=None, alias=_SESSION_HEADER),
) -> dict[str, str]:
    _, _, vault, _ = session.require()
    if not vault.delete(x_vault_session, name):
        raise HTTPException(404, "No secret with that name is stored in your vault.")
    return {"status": "deleted"}
