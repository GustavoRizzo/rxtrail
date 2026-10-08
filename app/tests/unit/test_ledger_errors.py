"""Every refusal or failure from the chain reaches the domain as an error.

The program is the source of truth: even a refusal the app does not model is
an error, and a transaction whose landing cannot be confirmed is never
reported as a success.
"""

import asyncio

import pytest
from solana.exceptions import SolanaRpcException
from solana.rpc.core import RPCException

from rxtrail.domain import (
    AlreadyDispensedError,
    LedgerUnavailableError,
    NothingDispensedError,
    NothingRemainingError,
    NotPrescriptionIssuerError,
    NotRegisteredError,
    OutcomeUnknownError,
    QuantityExceedsRemainingError,
    RxTrailError,
    TransactionRejectedError,
)
from solana_client import ledger as ledger_module
from solana_client.confirmations import ConfirmationError
from solana_client.keystore import FileKeyStore
from solana_client.ledger import SolanaLedger


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    async def instant(_seconds):
        return None

    monkeypatch.setattr(ledger_module.asyncio, "sleep", instant)
    # Nothing connects: only the error handling is exercised.
    return SolanaLedger("http://unused", "ws://unused", FileKeyStore(tmp_path), max_retries=2)


def preflight(message: str) -> RPCException:
    return RPCException(f"Transaction simulation failed: {message}")


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        (
            "Error processing Instruction 0: custom program error: 0x1778",
            QuantityExceedsRemainingError,
        ),
        ("InstructionError(0, Custom(6008))", QuantityExceedsRemainingError),
        ("custom program error: 0xbc4", NotRegisteredError),  # 3012: no such participant
        ("custom program error: 0x177e", NotPrescriptionIssuerError),  # 6014
        ("InstructionError(0, Custom(6015))", AlreadyDispensedError),
        ("InstructionError(0, Custom(6016))", NothingDispensedError),
        ("InstructionError(0, Custom(6017))", NothingRemainingError),
    ],
)
def test_refusals_the_program_explains_map_to_their_domain_error(ledger, message, expected):
    assert isinstance(ledger._translate(preflight(message)), expected)


@pytest.mark.parametrize(
    "message",
    [
        "custom program error: 0x7d6",  # 2006, Anchor ConstraintSeeds: not modelled
        "custom program error: 0x0",  # system program: account already in use
        "Blockhash not found",
        "something nobody has ever seen",
    ],
)
def test_refusals_the_app_does_not_model_are_still_errors(ledger, message):
    error = ledger._translate(preflight(message))

    assert isinstance(error, TransactionRejectedError)
    assert message in str(error)  # the chain's own words are kept


async def test_a_transaction_that_fails_on_chain_is_an_error(ledger):
    landed = asyncio.get_running_loop().create_future()
    landed.set_result({"InstructionError": [0, {"Custom": 1}]})

    with pytest.raises(TransactionRejectedError, match="failed on-chain"):
        await ledger._wait("sig", landed)


async def test_a_confirmation_that_never_comes_is_unknown_not_success(ledger, monkeypatch):
    monkeypatch.setattr(ledger_module, "CONFIRM_TIMEOUT_SECONDS", 0.01)
    never = asyncio.get_running_loop().create_future()

    with pytest.raises(OutcomeUnknownError) as raised:
        await ledger._wait("sent-sig", never)
    assert raised.value.signature == "sent-sig"


async def test_a_dropped_websocket_is_unknown_not_success(ledger):
    dropped = asyncio.get_running_loop().create_future()
    dropped.set_exception(ConfirmationError("WebSocket closed"))

    with pytest.raises(OutcomeUnknownError):
        await ledger._wait("sent-sig", dropped)


async def test_a_confirmed_transaction_passes(ledger):
    ok = asyncio.get_running_loop().create_future()
    ok.set_result(None)
    await ledger._wait("sig", ok)


async def test_an_unreachable_node_becomes_a_domain_error_after_retries(ledger):
    calls = []

    async def down():
        calls.append(1)
        raise SolanaRpcException(ConnectionError("refused"), down, None, object())

    with pytest.raises(LedgerUnavailableError):
        await ledger._call(down)
    assert len(calls) == 3  # first try + 2 retries


def test_every_outcome_error_is_a_domain_error():
    # Callers can catch RxTrailError and never see a library exception.
    for error in (
        TransactionRejectedError,
        OutcomeUnknownError,
        LedgerUnavailableError,
        NotRegisteredError,
    ):
        assert issubclass(error, RxTrailError)


@pytest.mark.parametrize(
    ("message", "taken"),
    [
        ("Allocate: account Address { ... } already in use", True),
        ("failed on-chain: {'InstructionError': [0, {'Custom': 2006}]}", True),
        ("custom program error: 0x7d6", True),
        ("custom program error: 0x1778", False),  # QuantityExceedsRemaining: real limit
        ("Blockhash not found", False),
    ],
)
def test_only_a_taken_dispensation_slot_is_retried(message, taken):
    from solana_client.ledger import _slot_taken

    assert _slot_taken(TransactionRejectedError(message)) is taken
