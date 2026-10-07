"""Tests against the real program on the local validator.

Skipped unless the program is deployed there (`just localnet`,
`just deploy-localnet`). Authorities and the operator come from the
configured key store, set up by `manage.py rxtrail setup`; each test gets
fresh participants in a temporary key store.
"""

import asyncio
import secrets
import shutil

import pytest
from django.conf import settings
from django.core.management import call_command
from solana.exceptions import SolanaRpcException
from solana.rpc.async_api import AsyncClient

from solana_client.idl import Idl
from solana_client.keystore import FileKeyStore
from solana_client.ledger import SolanaLedger

pytestmark = pytest.mark.django_db(transaction=True)


def _program_deployed() -> bool:
    async def check():
        async with AsyncClient(settings.SOLANA_ENDPOINTS["localnet"][0], timeout=3) as client:
            account = (await client.get_account_info(Idl.load().program_id)).value
            return account is not None and account.executable

    try:
        return asyncio.run(check())
    except OSError, SolanaRpcException:  # validator unreachable: not available
        return False


def pytest_collection_modifyitems(config, items):
    if _program_deployed():
        return
    skip = pytest.mark.skip(reason="program not deployed on localnet (just deploy-localnet)")
    for item in items:
        if "tests/localnet/" in str(item.path):
            item.add_marker(skip)


@pytest.fixture
def keys(tmp_path, settings):
    settings.SOLANA_NETWORK = "localnet"
    settings.SOLANA_RPC_URL, settings.SOLANA_WS_URL = settings.SOLANA_ENDPOINTS["localnet"]
    call_command("rxtrail", "setup", verbosity=0)  # idempotent
    store = tmp_path / "keys"
    store.mkdir(mode=0o700)
    for name in ("operator", "professional-authority", "health-authority", "catalog-authority"):
        shutil.copy(settings.SOLANA_KEYS_DIR / f"{name}.json", store)
    return FileKeyStore(store)


@pytest.fixture
async def ledger(keys, settings):
    async with SolanaLedger(settings.SOLANA_RPC_URL, settings.SOLANA_WS_URL, keys) as chain:
        yield chain


@pytest.fixture
def fresh(keys):
    """A new participant name, with its key, unique to this test."""

    def make(role: str) -> str:
        name = f"{role}-{secrets.token_hex(4)}"
        keys.create(name)
        return name

    return make
