"""Bind this database to one chain, and refuse any other."""

from records.models import ChainBinding
from rxtrail.domain import ChainMismatchError


async def ensure_bound(network: str, genesis_hash: str, program_id: str) -> None:
    """First use: remember the chain. Afterwards: insist on the same one."""
    binding = await ChainBinding.objects.afirst()
    if binding is None:
        await ChainBinding.objects.acreate(
            network=network, genesis_hash=genesis_hash, program_id=program_id
        )
        return
    if (binding.genesis_hash, binding.program_id) != (genesis_hash, program_id):
        raise ChainMismatchError(
            f"this database belongs to {binding.network} (genesis {binding.genesis_hash[:8]}…, "
            f"program {binding.program_id[:8]}…), but the app is connected to {network} "
            f"(genesis {genesis_hash[:8]}…, program {program_id[:8]}…). "
            "Use that network's environment, or reset this one."
        )
