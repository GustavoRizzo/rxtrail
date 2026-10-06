"""Named keypair files."""

import json
import stat

import pytest
from solders.keypair import Keypair

from solana_client.keystore import FileKeyStore, KeyNotFoundError


@pytest.fixture
def store(tmp_path):
    return FileKeyStore(tmp_path / "keys")


def test_keys_are_solana_cli_compatible_and_private(store, tmp_path):
    created = store.create("dr-ana")

    path = tmp_path / "keys" / "dr-ana.json"
    raw = json.loads(path.read_text())
    assert len(raw) == 64
    assert Keypair.from_bytes(bytes(raw)).pubkey() == created.pubkey()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE((tmp_path / "keys").stat().st_mode) == 0o700


def test_an_existing_key_is_never_overwritten(store):
    store.create("dr-ana")
    with pytest.raises(FileExistsError):
        store.create("dr-ana")


def test_unknown_keys_raise(store):
    with pytest.raises(KeyNotFoundError):
        store.keypair("nobody")


@pytest.mark.parametrize("name", ["../escape", "Dr-Ana", "a/b", ""])
def test_names_cannot_escape_the_directory(store, name):
    with pytest.raises(ValueError):
        store.create(name)
    assert not store.exists(name)
