"""Committing to an off-chain document with an on-chain hash.

The chain stores sha256(salt || canonical document). Anyone holding the
document and its salt can recompute the hash and prove the document was not
altered after issuance; anyone holding only the hash learns nothing, because
the random salt defeats guessing (unlike hashing, say, a national id number).
"""

import hashlib
import json
import secrets
from dataclasses import asdict

from rxtrail.domain import PrescriptionDocument

SALT_BYTES = 32


def new_salt() -> bytes:
    return secrets.token_bytes(SALT_BYTES)


def canonical_bytes(document: PrescriptionDocument) -> bytes:
    """One byte representation per document: sorted keys, no whitespace, UTF-8."""
    return json.dumps(asdict(document), sort_keys=True, separators=(",", ":")).encode()


def document_hash(document: PrescriptionDocument, salt: bytes) -> bytes:
    return hashlib.sha256(salt + canonical_bytes(document)).digest()


def verify(document: PrescriptionDocument, salt: bytes, expected_hash: bytes) -> bool:
    return secrets.compare_digest(document_hash(document, salt), expected_hash)
