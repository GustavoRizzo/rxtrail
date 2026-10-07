"""The RxTrail on-chain program, behind the domain's PrescriptionLedger port.

Every write is a transaction paid by the operator and signed by the named
participant it is attributed to: the program refuses it otherwise. Reads
decode accounts at addresses anyone can derive (see pdas.py).

The program is the source of truth. Every write ends in exactly one of:
a Receipt (the chain accepted it), a domain error the program explained
(PROGRAM_ERRORS), TransactionRejectedError (refused, reason not modelled),
OutcomeUnknownError (sent, landing not confirmed) or LedgerUnavailableError
(node unreachable). Nothing from the chain escapes as a library exception.
"""

import asyncio
import logging
import re
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Self

from solana.exceptions import SolanaRpcException
from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Confirmed
from solana.rpc.core import RPCException
from solana.rpc.models import TxOpts
from solders.instruction import AccountMeta, Instruction
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.system_program import ID as SYSTEM_PROGRAM_ID
from solders.transaction import Transaction

from rxtrail.domain import (
    PROGRAM_ERRORS,
    Dispensation,
    LedgerUnavailableError,
    NotRegisteredError,
    OutcomeUnknownError,
    ParticipantStatus,
    Prescription,
    PrescriptionStatus,
    Receipt,
    TransactionRejectedError,
)
from solana_client import pdas
from solana_client.confirmations import ConfirmationError, Confirmations
from solana_client.idl import Idl
from solana_client.keystore import FileKeyStore

logger = logging.getLogger(__name__)

# Anchor's own code for "this account does not exist": e.g. a signer with no
# prescriber record, i.e. not enabled by the authority.
ACCOUNT_NOT_INITIALIZED = 3012

CONFIRM_TIMEOUT_SECONDS = 90  # a transaction's blockhash expires in about a minute

# Concurrent pharmacies can collide on the next dispensation slot; see dispense().
DISPENSE_ATTEMPTS = 5


def _timestamp(seconds: int) -> datetime:
    return datetime.fromtimestamp(seconds, UTC)


class SolanaLedger:
    def __init__(
        self,
        rpc_url: str,
        ws_url: str,
        keys: FileKeyStore,
        operator: str = "operator",
        idl: Idl | None = None,
        max_retries: int = 5,
    ):
        self._idl = idl or Idl.load()
        self.program_id = self._idl.program_id
        self._client = AsyncClient(rpc_url, commitment=Confirmed, timeout=30)
        self._confirmations = Confirmations(ws_url)
        self._keys = keys
        self._operator = operator
        self._max_retries = max_retries

    async def __aenter__(self) -> Self:
        await self._client.__aenter__()
        await self._confirmations.__aenter__()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self._confirmations.__aexit__(*exc_info)
        await self._client.close()

    def address_of(self, participant: str) -> str:
        return str(self._keys.keypair(participant).pubkey())

    # -- writes -------------------------------------------------------------------

    async def initialize(self, professional_authority: str, health_authority: str) -> Receipt:
        config = pdas.config(self.program_id)
        return await self._send(
            "initialize",
            {
                "professional_authority": self.address_of(professional_authority),
                "health_authority": self.address_of(health_authority),
            },
            {"config": config},
            signers=[],
            address=config,
        )

    async def register_prescriber(self, authority: str, prescriber: str) -> Receipt:
        key = self._keys.keypair(prescriber).pubkey()
        record = pdas.prescriber(self.program_id, key)
        return await self._send(
            "register_prescriber",
            {"prescriber_key": key},
            {
                "professional_authority": self._keys.keypair(authority).pubkey(),
                "config": pdas.config(self.program_id),
                "prescriber": record,
            },
            signers=[authority],
            address=record,
        )

    async def register_dispenser(self, authority: str, dispenser: str) -> Receipt:
        key = self._keys.keypair(dispenser).pubkey()
        record = pdas.dispenser(self.program_id, key)
        return await self._send(
            "register_dispenser",
            {"dispenser_key": key},
            {
                "health_authority": self._keys.keypair(authority).pubkey(),
                "config": pdas.config(self.program_id),
                "dispenser": record,
            },
            signers=[authority],
            address=record,
        )

    async def set_prescriber_status(
        self, authority: str, prescriber: str, status: ParticipantStatus
    ) -> Receipt:
        record = pdas.prescriber(self.program_id, self._keys.keypair(prescriber).pubkey())
        return await self._send(
            "set_prescriber_status",
            {"status": status.value.capitalize()},
            {
                "professional_authority": self._keys.keypair(authority).pubkey(),
                "config": pdas.config(self.program_id),
                "prescriber": record,
            },
            signers=[authority],
            address=record,
        )

    async def set_dispenser_status(
        self, authority: str, dispenser: str, status: ParticipantStatus
    ) -> Receipt:
        record = pdas.dispenser(self.program_id, self._keys.keypair(dispenser).pubkey())
        return await self._send(
            "set_dispenser_status",
            {"status": status.value.capitalize()},
            {
                "health_authority": self._keys.keypair(authority).pubkey(),
                "config": pdas.config(self.program_id),
                "dispenser": record,
            },
            signers=[authority],
            address=record,
        )

    async def issue_prescription(
        self,
        prescriber: str,
        prescription_id: bytes,
        patient_id: bytes,
        document_hash: bytes,
        quantity: int,
        expires_at: datetime,
    ) -> Receipt:
        key = self._keys.keypair(prescriber).pubkey()
        address = pdas.prescription(self.program_id, prescription_id)
        return await self._send(
            "issue_prescription",
            {
                "id": prescription_id,
                "patient_id": patient_id,
                "document_hash": document_hash,
                "quantity": quantity,
                "expires_at": int(expires_at.timestamp()),
            },
            {
                "prescriber_signer": key,
                "prescriber": pdas.prescriber(self.program_id, key),
                "prescription": address,
            },
            signers=[prescriber],
            address=address,
        )

    async def dispense(self, dispenser: str, prescription_id: bytes, quantity: int) -> Receipt:
        """Record a dispensation; if another pharmacy took the same slot first, retry.

        Each dispensation lives at an address derived from the prescription's
        counter. Two pharmacies reading the counter at once derive the same
        address: the chain accepts one and refuses the other ("already in
        use"). The loser re-reads the counter and tries again, so it either
        lands in the next slot or meets the real limit (QuantityExceedsRemaining).
        """
        for attempt in range(DISPENSE_ATTEMPTS):
            try:
                return await self._dispense_once(dispenser, prescription_id, quantity)
            except TransactionRejectedError as exc:
                if not _slot_taken(exc) or attempt == DISPENSE_ATTEMPTS - 1:
                    raise
                logger.info("dispensation slot taken by a concurrent pharmacy; retrying")
        raise AssertionError("unreachable")

    async def _dispense_once(
        self, dispenser: str, prescription_id: bytes, quantity: int
    ) -> Receipt:
        current = await self.prescription(prescription_id)
        if current is None:
            raise TransactionRejectedError(f"no prescription {prescription_id.hex()}")
        key = self._keys.keypair(dispenser).pubkey()
        address = Pubkey.from_string(current.address)
        record = pdas.dispensation(self.program_id, address, current.dispensation_count)
        return await self._send(
            "dispense",
            {"quantity": quantity},
            {
                "dispenser_signer": key,
                "dispenser": pdas.dispenser(self.program_id, key),
                "prescription": address,
                "prescriber": pdas.prescriber(
                    self.program_id, Pubkey.from_string(current.prescriber)
                ),
                "dispensation": record,
            },
            signers=[dispenser],
            address=record,
        )

    # -- reads ----------------------------------------------------------------------

    async def genesis_hash(self) -> str:
        """The identity of the chain this node serves: its first block's hash."""
        return str((await self._call(self._client.get_genesis_hash)).value)

    async def initialized(self) -> bool:
        return await self._account(pdas.config(self.program_id)) is not None

    async def prescription(self, prescription_id: bytes) -> Prescription | None:
        address = pdas.prescription(self.program_id, prescription_id)
        data = await self._account(address)
        if data is None:
            return None
        raw = self._idl.decode_account("Prescription", data)
        return Prescription(
            id=raw["id"],
            address=str(address),
            prescriber=raw["prescriber"],
            patient_id=raw["patient_id"],
            document_hash=raw["document_hash"],
            quantity_granted=raw["quantity_granted"],
            quantity_dispensed=raw["quantity_dispensed"],
            dispensation_count=raw["dispensation_count"],
            issued_at=_timestamp(raw["issued_at"]),
            expires_at=_timestamp(raw["expires_at"]),
            status=PrescriptionStatus(raw["status"].lower()),
        )

    async def participant_status(self, role: str, participant: str) -> ParticipantStatus | None:
        key = self._keys.keypair(participant).pubkey()
        find, account = {
            "prescriber": (pdas.prescriber, "Prescriber"),
            "dispenser": (pdas.dispenser, "Dispenser"),
        }[role]
        data = await self._account(find(self.program_id, key))
        if data is None:
            return None
        return ParticipantStatus(self._idl.decode_account(account, data)["status"].lower())

    async def dispensations(self, prescription: Prescription) -> Sequence[Dispensation]:
        """Every dispensation, fetched at its derived address: no index needed."""
        if prescription.dispensation_count == 0:
            return []
        parent = Pubkey.from_string(prescription.address)
        addresses = [
            pdas.dispensation(self.program_id, parent, i)
            for i in range(prescription.dispensation_count)
        ]
        response = await self._call(self._client.get_multiple_accounts, addresses)
        found = []
        for address, account in zip(addresses, response.value, strict=True):
            if account is None:
                continue
            raw = self._idl.decode_account("Dispensation", bytes(account.data))
            found.append(
                Dispensation(
                    address=str(address),
                    prescription=raw["prescription"],
                    index=raw["index"],
                    dispenser=raw["dispenser"],
                    quantity=raw["quantity"],
                    remaining_after=raw["remaining_after"],
                    dispensed_at=_timestamp(raw["dispensed_at"]),
                )
            )
        return found

    # -- operator funding (local development only) -------------------------------------

    async def airdrop_to_operator(self, lamports: int) -> None:
        """Faucets only exist on test networks; localnet's is unlimited."""
        payer = self._keys.keypair(self._operator).pubkey()
        response = await self._call(self._client.request_airdrop, payer, lamports)
        await self._wait(str(response.value), await self._confirmations.expect(str(response.value)))

    async def operator_balance(self) -> int:
        payer = self._keys.keypair(self._operator).pubkey()
        return (await self._call(self._client.get_balance, payer)).value

    # -- plumbing ---------------------------------------------------------------------

    async def _send(
        self, name: str, args: dict, named: dict[str, Pubkey], signers: list[str], address: Pubkey
    ) -> Receipt:
        operator = self._keys.keypair(self._operator)
        named = {"payer": operator.pubkey(), "system_program": SYSTEM_PROGRAM_ID, **named}
        metas = [
            AccountMeta(named[slot["name"]], bool(slot.get("signer")), bool(slot.get("writable")))
            for slot in self._idl.instruction_accounts(name)
        ]
        instruction = Instruction(self.program_id, self._idl.encode_instruction(name, args), metas)

        keypairs: list[Keypair] = [operator]
        for signer in signers:
            keypair = self._keys.keypair(signer)
            if keypair.pubkey() != operator.pubkey():
                keypairs.append(keypair)

        blockhash = (await self._call(self._client.get_latest_blockhash, Confirmed)).value.blockhash
        transaction = Transaction.new_signed_with_payer(
            [instruction], operator.pubkey(), keypairs, blockhash
        )
        signature = str(transaction.signatures[0])
        # Subscribe before sending: the confirmation cannot slip past us.
        try:
            confirmed = await self._confirmations.expect(signature)
        except ConfirmationError as exc:
            raise LedgerUnavailableError(f"cannot follow confirmations: {exc}") from exc
        try:
            await self._call(
                self._client.send_raw_transaction,
                bytes(transaction),
                TxOpts(preflight_commitment=Confirmed),
            )
        except RPCException as exc:
            # Preflight: the node simulated it and the program said no.
            raise self._translate(exc) from exc
        except LedgerUnavailableError as exc:
            # It may or may not have reached the node before the failure.
            raise OutcomeUnknownError(signature, str(exc)) from exc
        await self._wait(signature, confirmed)
        return Receipt(signature=signature, address=str(address))

    async def _wait(self, signature: str, confirmed: asyncio.Future) -> None:
        try:
            error = await asyncio.wait_for(confirmed, CONFIRM_TIMEOUT_SECONDS)
        except TimeoutError:
            raise OutcomeUnknownError(signature, "not confirmed in time") from None
        except ConfirmationError as exc:
            raise OutcomeUnknownError(signature, str(exc)) from exc
        if error is not None:
            # Landed in a block but failed while executing: the program refused.
            raise TransactionRejectedError(f"{signature} failed on-chain: {error}")

    def _translate(self, exc: RPCException) -> Exception:
        """A preflight refusal, as a domain error when the program said why."""
        text = str(exc.args[0] if exc.args else exc)
        match = re.search(r"custom program error: 0x([0-9a-fA-F]+)|Custom\((\d+)\)", text)
        if match:
            code = int(match.group(1), 16) if match.group(1) else int(match.group(2))
            if code == ACCOUNT_NOT_INITIALIZED:
                return NotRegisteredError("the signer is not an enabled participant")
            name = self._idl.error_name(code)
            if name in PROGRAM_ERRORS:
                return PROGRAM_ERRORS[name](name)
        return TransactionRejectedError(text)

    async def _account(self, address: Pubkey) -> bytes | None:
        response = await self._call(self._client.get_account_info, address)
        return None if response.value is None else bytes(response.value.data)

    async def _call(self, method, *args):
        """Back off when a node throttles (HTTP 429) or the network drops.
        JSON-RPC errors are answers, not outages: never retried."""
        delay = 0.5
        for attempt in range(self._max_retries + 1):
            try:
                return await method(*args)
            except SolanaRpcException as exc:
                if attempt == self._max_retries:
                    raise LedgerUnavailableError(
                        f"Solana node unavailable after {self._max_retries} retries: {exc}"
                    ) from exc
                logger.warning("RPC %s failed (%s); retrying in %.1fs", method.__name__, exc, delay)
                await asyncio.sleep(delay)
                delay = min(delay * 2, 8)
        raise AssertionError("unreachable")


# A concurrent dispensation took the slot: the account exists, or the
# prescription's counter moved past the index the address was derived from.
_SLOT_TAKEN = re.compile(r"already in use|Custom\W{0,4}2006|0x7d6", re.IGNORECASE)


def _slot_taken(error: TransactionRejectedError) -> bool:
    return bool(_SLOT_TAKEN.search(str(error)))
