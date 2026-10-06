"""The IDL codec speaks the program's binary format (Anchor + Borsh)."""

import hashlib
import struct

import pytest
from solders.pubkey import Pubkey

from solana_client.idl import Idl

IDL = Idl.load()


def anchor_discriminator(namespace: str, name: str) -> bytes:
    """Anchor's rule: the first 8 bytes of sha256("<namespace>:<name>")."""
    return hashlib.sha256(f"{namespace}:{name}".encode()).digest()[:8]


@pytest.mark.parametrize(
    "name",
    ["initialize", "register_prescriber", "register_dispenser", "issue_prescription", "dispense"],
)
def test_instruction_discriminators_follow_anchors_rule(name):
    data = IDL.encode_instruction(name, _sample_args(name))
    assert data[:8] == anchor_discriminator("global", name)


@pytest.mark.parametrize(
    "name", ["Config", "Prescriber", "Dispenser", "Prescription", "Dispensation"]
)
def test_account_discriminators_follow_anchors_rule(name):
    assert IDL.account_discriminator(name) == anchor_discriminator("account", name)


def test_issue_prescription_args_are_laid_out_in_order():
    data = IDL.encode_instruction(
        "issue_prescription",
        {
            "id": b"\x01" * 32,
            "patient_id": b"\x02" * 32,
            "document_hash": b"\x03" * 32,
            "quantity": 30,
            "expires_at": 1_800_000_000,
        },
    )
    body = data[8:]
    assert body[:96] == b"\x01" * 32 + b"\x02" * 32 + b"\x03" * 32
    assert struct.unpack("<Iq", body[96:]) == (30, 1_800_000_000)


def test_byte_arrays_must_have_the_declared_size():
    with pytest.raises(ValueError):
        IDL.encode_instruction(
            "issue_prescription",
            {
                "id": b"short",
                "patient_id": b"\x02" * 32,
                "document_hash": b"\x03" * 32,
                "quantity": 1,
                "expires_at": 1,
            },
        )


def test_a_prescription_account_decodes_field_by_field():
    prescriber = Pubkey.new_unique()
    data = (
        IDL.account_discriminator("Prescription")
        + b"\x01" * 32  # id
        + bytes(prescriber)
        + b"\x02" * 32  # patient_id
        + b"\x03" * 32  # document_hash
        + struct.pack("<III", 30, 20, 2)  # granted, dispensed, count
        + struct.pack("<qq", 1_700_000_000, 1_800_000_000)  # issued_at, expires_at
        + b"\x00"  # status: Active (variant 0)
        + b"\xfe"  # bump
    )

    raw = IDL.decode_account("Prescription", data)

    assert raw["prescriber"] == str(prescriber)
    assert (raw["quantity_granted"], raw["quantity_dispensed"], raw["dispensation_count"]) == (
        30,
        20,
        2,
    )
    assert raw["expires_at"] == 1_800_000_000
    assert raw["status"] == "Active"


def test_decoding_refuses_an_account_of_another_type():
    with pytest.raises(ValueError, match="not a Prescription"):
        IDL.decode_account("Prescription", IDL.account_discriminator("Dispensation") + bytes(100))


def test_program_error_codes_map_to_names():
    assert IDL.error_name(6008) == "QuantityExceedsRemaining"
    assert IDL.error_name(1) is None


def _sample_args(name):
    key = Pubkey.new_unique()
    return {
        "initialize": {"professional_authority": key, "health_authority": key},
        "register_prescriber": {"prescriber_key": key},
        "register_dispenser": {"dispenser_key": key},
        "issue_prescription": {
            "id": bytes(32),
            "patient_id": bytes(32),
            "document_hash": bytes(32),
            "quantity": 1,
            "expires_at": 1,
        },
        "dispense": {"quantity": 1},
    }[name]
