"""WebSocket confirmation routing, without a network."""

import asyncio

import pytest

from solana_client.confirmations import ConfirmationError, Confirmations


@pytest.fixture
def confirmations():
    return Confirmations("ws://unused")


async def test_a_notification_resolves_the_matching_signature(confirmations):
    loop = asyncio.get_running_loop()
    confirmations._waiting[7] = done = loop.create_future()

    confirmations.handle(
        {
            "method": "signatureNotification",
            "params": {"subscription": 7, "result": {"value": {"err": None}}},
        }
    )

    assert done.result() is None


async def test_an_on_chain_failure_is_delivered_not_dropped(confirmations):
    # The case solana-py 0.41 cannot parse: it must reach the caller.
    loop = asyncio.get_running_loop()
    confirmations._waiting[7] = done = loop.create_future()
    error = {"InstructionError": [0, {"Custom": 2006}]}

    confirmations.handle(
        {
            "method": "signatureNotification",
            "params": {"subscription": 7, "result": {"value": {"err": error}}},
        }
    )

    assert done.result() == error


async def test_subscription_acknowledgements_and_refusals(confirmations):
    loop = asyncio.get_running_loop()
    confirmations._subscribing[1] = ok = loop.create_future()
    confirmations._subscribing[2] = bad = loop.create_future()

    confirmations.handle({"jsonrpc": "2.0", "id": 1, "result": 99})
    confirmations.handle({"jsonrpc": "2.0", "id": 2, "error": {"code": -32602}})

    assert ok.result() == 99
    with pytest.raises(ConfirmationError):
        bad.result()


async def test_a_dropped_connection_fails_every_pending_wait(confirmations):
    loop = asyncio.get_running_loop()
    confirmations._waiting[1] = a = loop.create_future()
    confirmations._subscribing[2] = b = loop.create_future()

    confirmations._fail_all(ConfirmationError("closed"))

    for future in (a, b):
        with pytest.raises(ConfirmationError):
            future.result()
