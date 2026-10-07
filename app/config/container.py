"""Composition root: the one place that wires the domain's ports to adapters."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from django.conf import settings

from records.binding import ensure_bound
from records.repositories import DjangoCatalog, DjangoDocumentVault, DjangoPatientDirectory
from rxtrail.services import RxTrail
from solana_client.keystore import FileKeyStore
from solana_client.ledger import SolanaLedger


def key_store() -> FileKeyStore:
    return FileKeyStore(settings.SOLANA_KEYS_DIR)


def ledger() -> SolanaLedger:
    return SolanaLedger(
        settings.SOLANA_RPC_URL,
        settings.SOLANA_WS_URL,
        key_store(),
        operator=settings.SOLANA_OPERATOR,
    )


@asynccontextmanager
async def open_rxtrail() -> AsyncIterator[tuple[RxTrail, SolanaLedger]]:
    """The application plus its ledger connection, closed on exit.

    Refuses to start if this database belongs to another chain.
    """
    async with ledger() as chain:
        await ensure_bound(
            settings.SOLANA_NETWORK, await chain.genesis_hash(), str(chain.program_id)
        )
        yield (
            RxTrail(chain, DjangoDocumentVault(), DjangoPatientDirectory(), DjangoCatalog()),
            chain,
        )
