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
    [
        "initialize",
        "register_prescriber",
        "register_dispenser",
        "register_medication",
        "register_product",
        "issue_prescription",
        "dispense",
        "cancel_prescription",
        "stop_prescription",
    ],
)
def test_instruction_discriminators_follow_anchors_rule(name):
    data = IDL.encode_instruction(name, _sample_args(name))
    assert data[:8] == anchor_discriminator("global", name)


@pytest.mark.parametrize(
    "name",
    [
        "Config",
        "Prescriber",
        "Dispenser",
        "Medication",
        "Product",
        "Prescription",
        "Dispensation",
        "PrescriptionClosure",
    ],
)
def test_account_discriminators_follow_anchors_rule(name):
    assert IDL.account_discriminator(name) == anchor_discriminator("account", name)


def test_issue_prescription_args_are_laid_out_in_order():
    data = IDL.encode_instruction(
        "issue_prescription",
        {
            "id": b"\x01" * 32,
            "document_hash": b"\x03" * 32,
            "quantity": 30,
            "expires_at": 1_800_000_000,
        },
    )
    body = data[8:]
    assert body[:64] == b"\x01" * 32 + b"\x03" * 32
    assert struct.unpack("<Iq", body[64:]) == (30, 1_800_000_000)


def test_the_prescription_takes_no_patient_at_all():
    args = {a["name"] for a in IDL._instructions["issue_prescription"]["args"]}
    fields = {f["name"] for f in IDL._types["Prescription"]["fields"]}
    assert not any("patient" in name for name in args | fields)


def test_the_locked_product_is_an_optional_account():
    slots = {s["name"]: s for s in IDL.instruction_accounts("issue_prescription")}
    assert slots["prescribed_product"].get("optional") is True
    assert not slots["medication"].get("optional")


def test_byte_arrays_must_have_the_declared_size():
    with pytest.raises(ValueError):
        IDL.encode_instruction(
            "issue_prescription",
            {
                "id": b"short",
                "document_hash": b"\x03" * 32,
                "quantity": 1,
                "expires_at": 1,
            },
        )


def prescription_bytes(prescriber, medication, locked: bytes = b"\x00") -> bytes:
    return (
        IDL.account_discriminator("Prescription")
        + b"\x01" * 32  # id
        + bytes(prescriber)
        + bytes(medication)
        + b"\x03" * 32  # document_hash
        + struct.pack("<III", 30, 20, 2)  # granted, dispensed, count
        + struct.pack("<qq", 1_700_000_000, 1_800_000_000)  # issued_at, expires_at
        + b"\x00"  # status: Active (variant 0)
        + locked  # prescribed_product: Option<Pubkey>
        + b"\xfe"  # bump
    )


def test_a_prescription_account_decodes_field_by_field():
    prescriber, medication = Pubkey.new_unique(), Pubkey.new_unique()

    raw = IDL.decode_account("Prescription", prescription_bytes(prescriber, medication))

    assert raw["prescriber"] == str(prescriber)
    assert raw["medication"] == str(medication)
    assert raw["prescribed_product"] is None
    assert raw["bump"] == 0xFE
    assert (raw["quantity_granted"], raw["quantity_dispensed"], raw["dispensation_count"]) == (
        30,
        20,
        2,
    )
    assert raw["expires_at"] == 1_800_000_000
    assert raw["status"] == "Active"


def test_an_option_is_a_flag_byte_then_the_value():
    product = Pubkey.new_unique()
    data = prescription_bytes(Pubkey.new_unique(), Pubkey.new_unique(), b"\x01" + bytes(product))

    assert IDL.decode_account("Prescription", data)["prescribed_product"] == str(product)
    assert IDL._encode({"option": "pubkey"}, None) == b"\x00"
    assert IDL._encode({"option": "pubkey"}, product) == b"\x01" + bytes(product)


def test_an_account_type_is_recognized_by_its_discriminator():
    assert IDL.account_name(IDL.account_discriminator("Medication") + bytes(10)) == "Medication"
    assert IDL.account_name(bytes(18)) is None


def test_decoding_refuses_an_account_of_another_type():
    with pytest.raises(ValueError, match="not a Prescription"):
        IDL.decode_account("Prescription", IDL.account_discriminator("Dispensation") + bytes(100))


def test_program_error_codes_map_to_names():
    assert IDL.error_name(6008) == "QuantityExceedsRemaining"
    assert IDL.error_name(1) is None


def _sample_args(name):
    key = Pubkey.new_unique()
    return {
        "initialize": {
            "professional_authority": key,
            "health_authority": key,
            "catalog_authority": key,
        },
        "register_prescriber": {"prescriber_key": key},
        "register_dispenser": {"dispenser_key": key},
        "register_medication": {"id": bytes(32), "identity_hash": bytes(32)},
        "register_product": {"id": bytes(32), "identity_hash": bytes(32)},
        "issue_prescription": {
            "id": bytes(32),
            "document_hash": bytes(32),
            "quantity": 1,
            "expires_at": 1,
        },
        "dispense": {"quantity": 1},
        "cancel_prescription": {"reason": "IssuedInError"},
        "stop_prescription": {"reason": "SuspectedMisuse"},
        "set_prescriber_status": {"status": "Suspended"},
        "set_dispenser_status": {"status": "Active"},
    }[name]


@pytest.mark.parametrize(("status", "byte"), [("Active", 0), ("Suspended", 1)])
def test_unit_enum_arguments_are_their_variant_index(status, byte):
    data = IDL.encode_instruction("set_prescriber_status", {"status": status})
    assert data[:8] == anchor_discriminator("global", "set_prescriber_status")
    assert data[8:] == bytes([byte])


@pytest.mark.parametrize(
    ("reason", "byte"),
    [
        ("IssuedInError", 0),
        ("Replaced", 1),
        ("ClinicalDecision", 2),
        ("SuspectedMisuse", 3),
        ("Other", 4),
    ],
)
def test_closure_reasons_are_their_variant_index(reason, byte):
    assert IDL.encode_instruction("cancel_prescription", {"reason": reason})[8:] == bytes([byte])


def test_every_closure_reason_has_a_variant_on_chain():
    from rxtrail.domain import ClosureReason
    from solana_client.ledger import _value, _variant

    for reason in ClosureReason:
        assert _value(_variant(reason.value)) == reason.value


@pytest.mark.parametrize(
    ("account", "size"),
    # Measured: the data length of every account the demo created on devnet.
    [
        ("Config", 105),
        ("Prescriber", 58),
        ("Dispenser", 58),
        ("Medication", 90),
        ("Product", 122),
        ("Prescription", 199),
        ("Dispensation", 125),
        ("PrescriptionClosure", 91),
    ],
)
def test_account_sizes_match_what_the_program_allocates(account, size):
    assert IDL.account_size(account) == size
