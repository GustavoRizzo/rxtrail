"""Program-derived addresses: where each record must live.

Seeds mirror program/programs/rxtrail/src/constants.rs. Anyone can recompute
these, which is what makes the records findable and verifiable.
"""

from solders.pubkey import Pubkey


def _find(program_id: Pubkey, *seeds: bytes) -> Pubkey:
    return Pubkey.find_program_address(list(seeds), program_id)[0]


def config(program_id: Pubkey) -> Pubkey:
    return _find(program_id, b"config")


def prescriber(program_id: Pubkey, key: Pubkey) -> Pubkey:
    return _find(program_id, b"prescriber", bytes(key))


def dispenser(program_id: Pubkey, key: Pubkey) -> Pubkey:
    return _find(program_id, b"dispenser", bytes(key))


def prescription(program_id: Pubkey, prescription_id: bytes) -> Pubkey:
    return _find(program_id, b"prescription", prescription_id)


def medication(program_id: Pubkey, medication_id: bytes) -> Pubkey:
    return _find(program_id, b"medication", medication_id)


def product(program_id: Pubkey, product_id: bytes) -> Pubkey:
    return _find(program_id, b"product", product_id)


def dispensation(program_id: Pubkey, prescription_address: Pubkey, index: int) -> Pubkey:
    return _find(
        program_id, b"dispensation", bytes(prescription_address), index.to_bytes(4, "little")
    )


def closure(program_id: Pubkey, prescription_address: Pubkey) -> Pubkey:
    return _find(program_id, b"closure", bytes(prescription_address))
