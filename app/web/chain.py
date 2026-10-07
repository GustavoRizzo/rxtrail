"""Run the async application from synchronous Django views."""

from collections.abc import Awaitable, Callable

from asgiref.sync import async_to_sync

from config import container
from rxtrail.services import RxTrail
from solana_client.ledger import SolanaLedger


def with_chain[T](work: Callable[[RxTrail, SolanaLedger], Awaitable[T]]) -> T:
    """Open the application and its chain connection, run `work`, close them."""

    async def run() -> T:
        async with container.open_rxtrail() as (app, ledger):
            return await work(app, ledger)

    return async_to_sync(run)()
