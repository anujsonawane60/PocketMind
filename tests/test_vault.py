"""Vault behaviour, including the properties the threat model depends on."""

from __future__ import annotations

import json
import time

import pytest

from pocketmind.services.vault import (
    Vault,
    VaultAuthError,
    VaultExists,
    VaultLocked,
    VaultMissing,
    password_strength,
)

PASSWORD = "correct horse battery staple 7!"


def test_create_then_store_and_read_back(vault: Vault):
    token = vault.create(PASSWORD)
    vault.add(token, "email recovery", "123-456", note="Backup codes")
    value, note = vault.reveal(token, "email recovery")
    assert value == "123-456"
    assert note == "Backup codes"


def test_wrong_password_is_rejected(vault: Vault):
    vault.create(PASSWORD)
    vault.lock()
    with pytest.raises(VaultAuthError):
        vault.unlock("not the password at all")


def test_correct_password_unlocks_after_locking(vault: Vault):
    token = vault.create(PASSWORD)
    vault.add(token, "api key", "sk-secret-value")
    vault.lock()
    new_token = vault.unlock(PASSWORD)
    assert vault.reveal(new_token, "api key")[0] == "sk-secret-value"


def test_master_password_is_never_written_to_the_file(vault: Vault):
    token = vault.create(PASSWORD)
    vault.add(token, "thing", "value")
    raw = vault.path.read_text(encoding="utf-8")
    assert PASSWORD not in raw
    for word in PASSWORD.split():
        assert word not in raw


def test_secret_values_and_names_are_both_encrypted(vault: Vault):
    """Entry names leak intent, so the whole list is one encrypted payload."""
    token = vault.create(PASSWORD)
    vault.add(token, "swiss bank login", "hunter2")
    raw = vault.path.read_text(encoding="utf-8")
    assert "hunter2" not in raw
    assert "swiss bank login" not in raw
    assert json.loads(raw)["entry_count"] == 1


def test_locked_vault_refuses_every_operation(vault: Vault):
    token = vault.create(PASSWORD)
    vault.add(token, "thing", "value")
    vault.lock()
    with pytest.raises(VaultLocked):
        vault.list_entries(token)
    with pytest.raises(VaultLocked):
        vault.reveal(token, "thing")
    with pytest.raises(VaultLocked):
        vault.add(token, "another", "value")


def test_a_stale_session_token_is_refused(vault: Vault):
    old_token = vault.create(PASSWORD)
    vault.lock()
    vault.unlock(PASSWORD)
    with pytest.raises(VaultAuthError):
        vault.list_entries(old_token)


def test_vault_auto_locks_after_inactivity(tmp_path):
    vault = Vault(tmp_path / "v.vault", lock_timeout_seconds=1)
    token = vault.create(PASSWORD)
    assert vault.status().state == "unlocked"
    time.sleep(1.2)
    assert vault.status().state == "locked"
    with pytest.raises(VaultLocked):
        vault.list_entries(token)


def test_activity_postpones_the_auto_lock(tmp_path):
    vault = Vault(tmp_path / "v.vault", lock_timeout_seconds=2)
    token = vault.create(PASSWORD)
    for _ in range(3):
        time.sleep(0.8)
        vault.list_entries(token)
    assert vault.status().state == "unlocked"


def test_entry_count_is_visible_while_locked(vault: Vault):
    token = vault.create(PASSWORD)
    vault.add(token, "one", "a")
    vault.add(token, "two", "b")
    vault.lock()
    status = vault.status()
    assert status.state == "locked"
    assert status.secret_count == 2


def test_changing_the_password_keeps_the_contents(vault: Vault):
    token = vault.create(PASSWORD)
    vault.add(token, "note", "keep me")
    new_token = vault.change_password(PASSWORD, "an entirely different pass 99$")
    assert vault.reveal(new_token, "note")[0] == "keep me"
    vault.lock()
    with pytest.raises(VaultAuthError):
        vault.unlock(PASSWORD)


def test_changing_the_password_requires_the_old_one(vault: Vault):
    vault.create(PASSWORD)
    with pytest.raises(VaultAuthError):
        vault.change_password("wrong one entirely", "another good password 12!")


def test_adding_the_same_name_twice_updates_rather_than_duplicates(vault: Vault):
    token = vault.create(PASSWORD)
    vault.add(token, "key", "first")
    vault.add(token, "key", "second")
    entries = vault.list_entries(token)
    assert len(entries) == 1
    assert vault.reveal(token, "key")[0] == "second"


def test_delete_removes_the_entry(vault: Vault):
    token = vault.create(PASSWORD)
    vault.add(token, "gone", "value")
    assert vault.delete(token, "gone") is True
    assert vault.delete(token, "gone") is False
    with pytest.raises(KeyError):
        vault.reveal(token, "gone")


def test_creating_twice_is_refused(vault: Vault):
    vault.create(PASSWORD)
    with pytest.raises(VaultExists):
        vault.create("a completely different one 1!")


def test_unlocking_a_missing_vault_says_so(vault: Vault):
    with pytest.raises(VaultMissing):
        vault.unlock(PASSWORD)


def test_a_backup_copy_survives_a_corrupted_vault_file(vault: Vault):
    """A torn write costs at most the most recent change, never the whole vault."""
    token = vault.create(PASSWORD)
    vault.add(token, "first", "value")
    vault.add(token, "second", "value")
    vault.path.write_text("{ this is not json", encoding="utf-8")

    recovered = vault.unlock(PASSWORD)
    names = [entry.name for entry in vault.list_entries(recovered)]
    assert "first" in names  # the backup holds the state before the last write


def test_swapping_the_kdf_parameters_invalidates_the_ciphertext(vault: Vault):
    """The KDF block is authenticated, so it cannot be downgraded in place."""
    vault.create(PASSWORD)
    payload = json.loads(vault.path.read_text(encoding="utf-8"))
    payload["kdf"]["time_cost"] = 1
    vault.path.write_text(json.dumps(payload), encoding="utf-8")
    vault.path.with_suffix(vault.path.suffix + ".bak").unlink(missing_ok=True)
    with pytest.raises(VaultAuthError):
        vault.unlock(PASSWORD)


@pytest.mark.parametrize(
    ("password", "expected"),
    [
        ("short", "Very weak"),
        ("allofitlowercase", "Weak"),
        ("Password1234", "Fair"),
        ("Password1234!xyz", "Very strong"),
    ],
)
def test_password_strength_labels(password, expected):
    assert password_strength(password)[0] == expected
