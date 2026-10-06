"""The salted hash that binds an off-chain document to its on-chain record."""

from dataclasses import replace

from rxtrail import documents
from tests.fakes import a_document


def test_the_hash_is_deterministic_for_the_same_document_and_salt():
    salt = documents.new_salt()
    assert documents.document_hash(a_document(), salt) == documents.document_hash(
        a_document(), salt
    )


def test_a_different_salt_gives_a_different_hash():
    # Without the salt, the hash cannot be found by guessing documents.
    assert documents.document_hash(a_document(), b"a" * 32) != documents.document_hash(
        a_document(), b"b" * 32
    )


def test_any_edit_to_the_document_is_detected():
    salt = documents.new_salt()
    original = documents.document_hash(a_document(quantity=30), salt)

    tampered = replace(a_document(quantity=30), quantity=60)

    assert not documents.verify(tampered, salt, original)
    assert documents.verify(a_document(quantity=30), salt, original)


def test_the_canonical_form_ignores_field_order():
    # Same data, built in a different order: same bytes, same hash.
    assert documents.canonical_bytes(a_document()) == documents.canonical_bytes(
        replace(a_document(), dosage="1 tablet at night")
    )


def test_salts_are_random_and_32_bytes():
    assert len(documents.new_salt()) == 32
    assert documents.new_salt() != documents.new_salt()
