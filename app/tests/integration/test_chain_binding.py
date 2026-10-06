"""A database belongs to one chain; the app refuses any other."""

import pytest

from records.binding import ensure_bound
from records.models import ChainBinding
from rxtrail.domain import ChainMismatchError

pytestmark = pytest.mark.django_db(transaction=True)


async def test_the_first_use_binds_the_database():
    await ensure_bound("localnet", "GENESIS-A", "PROGRAM")

    binding = await ChainBinding.objects.aget()
    assert (binding.network, binding.genesis_hash) == ("localnet", "GENESIS-A")


async def test_the_same_chain_is_accepted_again():
    await ensure_bound("localnet", "GENESIS-A", "PROGRAM")
    await ensure_bound("localnet", "GENESIS-A", "PROGRAM")
    assert await ChainBinding.objects.acount() == 1


async def test_another_network_is_refused():
    await ensure_bound("localnet", "GENESIS-A", "PROGRAM")
    with pytest.raises(ChainMismatchError, match="belongs to localnet"):
        await ensure_bound("devnet", "GENESIS-DEVNET", "PROGRAM")


async def test_a_reset_local_validator_is_refused():
    # Same network name, new genesis: the old records point at a chain that is gone.
    await ensure_bound("localnet", "GENESIS-A", "PROGRAM")
    with pytest.raises(ChainMismatchError):
        await ensure_bound("localnet", "GENESIS-B", "PROGRAM")


async def test_another_program_is_refused():
    await ensure_bound("localnet", "GENESIS-A", "PROGRAM-1")
    with pytest.raises(ChainMismatchError):
        await ensure_bound("localnet", "GENESIS-A", "PROGRAM-2")
