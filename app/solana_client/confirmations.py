"""Be told when a transaction confirms, instead of asking over and over.

`signatureSubscribe` over WebSocket: the subscription is placed before the
transaction is sent (its signature is known as soon as it is signed), and the
node pushes a notification when it reaches the requested commitment. Polling
`getSignatureStatuses` instead exhausts public endpoints' quotas (HTTP 429).

Plain JSON-RPC over `websockets`, on purpose: solana-py 0.41's client fails to
parse a notification for a transaction that failed on-chain and drops the
whole connection, which is exactly the case that must be reported.
"""

import asyncio
import itertools
import json
from typing import Self

from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

SUBSCRIBE_TIMEOUT_SECONDS = 10


class ConfirmationError(Exception):
    pass


class Confirmations:
    def __init__(self, ws_url: str):
        self._url = ws_url
        self._ws = None
        self._reader: asyncio.Task | None = None
        self._ids = itertools.count(1)
        # request id -> future of the server's subscription id
        self._subscribing: dict[int, asyncio.Future] = {}
        # subscription id -> future of the transaction's error (None = success)
        self._waiting: dict[int, asyncio.Future] = {}

    async def __aenter__(self) -> Self:
        try:
            self._ws = await connect(self._url, max_size=None)
        except OSError as exc:
            raise ConfirmationError(f"cannot open {self._url}: {exc}") from exc
        self._reader = asyncio.create_task(self._read_forever())
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        if self._reader is not None:
            self._reader.cancel()
            try:
                await self._reader
            except asyncio.CancelledError:
                pass
        if self._ws is not None:
            await self._ws.close()

    async def expect(self, signature: str) -> asyncio.Future:
        """Subscribe and wait until the node has registered it.

        The returned future resolves to the transaction's error, or None if it
        confirmed without error.
        """
        loop = asyncio.get_running_loop()
        request_id = next(self._ids)
        subscribed = loop.create_future()
        self._subscribing[request_id] = subscribed
        await self._ws.send(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "method": "signatureSubscribe",
                    "params": [signature, {"commitment": "confirmed"}],
                }
            )
        )
        try:
            subscription = await asyncio.wait_for(subscribed, SUBSCRIBE_TIMEOUT_SECONDS)
        except TimeoutError:
            raise ConfirmationError("the node did not acknowledge the subscription") from None
        confirmed = loop.create_future()
        self._waiting[subscription] = confirmed
        return confirmed

    def handle(self, message: dict) -> None:
        """Route one decoded message (public for tests)."""
        if "id" in message and message["id"] in self._subscribing:
            future = self._subscribing.pop(message["id"])
            if "error" in message:
                future.set_exception(ConfirmationError(str(message["error"])))
            else:
                future.set_result(message["result"])
        elif message.get("method") == "signatureNotification":
            params = message["params"]
            future = self._waiting.pop(params["subscription"], None)
            if future is not None and not future.done():
                future.set_result(params["result"]["value"].get("err"))

    async def _read_forever(self) -> None:
        try:
            async for raw in self._ws:
                self.handle(json.loads(raw))
        except ConnectionClosed as exc:
            self._fail_all(ConfirmationError(f"WebSocket closed: {exc}"))

    def _fail_all(self, error: Exception) -> None:
        for future in [*self._subscribing.values(), *self._waiting.values()]:
            if not future.done():
                future.set_exception(error)
