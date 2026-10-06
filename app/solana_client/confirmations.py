"""Be told when a transaction confirms, instead of asking over and over.

`signatureSubscribe` over WebSocket: the subscription is placed before the
transaction is sent (its signature is known as soon as it is signed), and the
node pushes a notification when it reaches the requested commitment. Polling
`getSignatureStatuses` instead exhausts public endpoints' quotas (HTTP 429).
"""

import asyncio
from typing import Self

from solana.rpc.commitment import Confirmed
from solana.rpc.websocket_api import SignatureNotification, SolanaWsClient
from solders.signature import Signature
from websockets.exceptions import ConnectionClosed


class ConfirmationError(Exception):
    pass


class Confirmations:
    def __init__(self, ws_url: str):
        self._client = SolanaWsClient(ws_url)
        self._reader: asyncio.Task | None = None
        self._waiting: dict[int, asyncio.Future] = {}

    async def __aenter__(self) -> Self:
        await self._client.connect()
        self._reader = asyncio.create_task(self._read_forever())
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        if self._reader is not None:
            self._reader.cancel()
            try:
                await self._reader
            except asyncio.CancelledError:
                pass
        await self._client.close()

    async def expect(self, signature: str) -> asyncio.Future:
        """Subscribe; the returned future resolves to the error (or None) on confirmation."""
        future = asyncio.get_running_loop().create_future()
        # Returns once the node has confirmed the subscription itself.
        subscription = await self._client.signature_subscribe(
            signature=Signature.from_string(signature), commitment=Confirmed
        )
        self._waiting[subscription.subscription_id] = future
        return future

    async def _read_forever(self) -> None:
        try:
            while True:
                notification = await self._client.recv()
                if isinstance(notification, SignatureNotification):
                    future = self._waiting.pop(notification.subscription, None)
                    if future is not None and not future.done():
                        future.set_result(notification.result.value.err)
        except ConnectionClosed as exc:
            for future in self._waiting.values():
                if not future.done():
                    future.set_exception(ConfirmationError(f"WebSocket closed: {exc}"))
