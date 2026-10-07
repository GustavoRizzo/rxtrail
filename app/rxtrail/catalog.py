"""The medication catalog: what pins a record's meaning, and gentle warnings.

The catalog is public and lives off-chain. On-chain, each medication and
product keeps only an id, a status and an identity hash: sha256 of the fields
that define it, in canonical form. Anyone holding the published catalog can
recompute the hash and check that the id still means what it meant when it
was registered. No salt: there is nothing secret to protect.

Names, therapeutic class and dosage guidance are not part of the identity:
they may be corrected without touching the chain.
"""

import hashlib
import json

from rxtrail.domain import MedicationDetails, ProductDetails


def identity_fields(details: MedicationDetails | ProductDetails) -> dict[str, str]:
    """The fields that define a catalog record. Changing one means a new record."""
    if isinstance(details, MedicationDetails):
        return {
            "active_ingredient": details.active_ingredient,
            "strength": details.strength,
            "form": details.form,
        }
    return {
        "medication_id": details.medication_id,
        "manufacturer": details.manufacturer,
        "brand_name": details.brand_name,
        "kind": str(details.kind),
    }


def canonical_bytes(fields: dict[str, str]) -> bytes:
    """Sorted keys, no whitespace, UTF-8, values trimmed and lower-cased: the
    same record typed twice gives the same bytes."""
    normalized = {key: value.strip().casefold() for key, value in fields.items()}
    return json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode()


def identity_hash(details: MedicationDetails | ProductDetails) -> bytes:
    return hashlib.sha256(canonical_bytes(identity_fields(details))).digest()


def warnings(details: MedicationDetails, quantity: int, valid_days: int) -> list[str]:
    """What the prescriber should double-check. Advice only: nothing is blocked
    (RN-26, RN-27); the program does not know these limits."""
    found = []
    if details.max_quantity and quantity > details.max_quantity:
        found.append(
            f"{quantity} {details.unit}s is above the regulatory limit of "
            f"{details.max_quantity} per prescription"
        )
    if details.max_validity_days and valid_days > details.max_validity_days:
        found.append(
            f"{valid_days} days is above the regulatory validity of "
            f"{details.max_validity_days} days"
        )
    if details.usual_max_daily_units and quantity > details.usual_max_daily_units * valid_days:
        found.append(
            f"{quantity} {details.unit}s exceeds the usual maximum of "
            f"{details.usual_max_daily_units} a day for {valid_days} days"
        )
    return found
