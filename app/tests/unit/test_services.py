"""Use cases over in-memory ports."""

from datetime import timedelta

import pytest

from rxtrail import documents
from rxtrail.domain import (
    ExpiryInThePastError,
    NotFoundError,
    NotRegisteredError,
    QuantityExceedsRemainingError,
)
from rxtrail.services import RxTrail
from tests.fakes import T0, FakeLedger, FakePatients, FakeVault, a_document


@pytest.fixture
def ledger():
    ledger = FakeLedger()
    ledger.prescribers.add("dr-ana")
    ledger.dispensers.add("pharmacy-one")
    return ledger


@pytest.fixture
def vault():
    return FakeVault()


@pytest.fixture
def app(ledger, vault):
    return RxTrail(ledger, vault, FakePatients(), now=lambda: T0)


async def issue(app, quantity=30):
    return await app.issue("dr-ana", "123", a_document(quantity), timedelta(days=30))


async def test_issuing_puts_the_hash_on_chain_and_the_document_off_chain(app, ledger, vault):
    issued = await issue(app)

    on_chain = ledger.prescriptions[issued.prescription_id]
    patient_id, document, salt = vault.documents[issued.prescription_id]
    assert on_chain.document_hash == documents.document_hash(document, salt)
    assert on_chain.patient_id == patient_id == issued.patient_id
    assert on_chain.quantity_granted == 30
    assert on_chain.expires_at == T0 + timedelta(days=30)


async def test_the_same_patient_keeps_one_random_id(app):
    first = await issue(app)
    second = await issue(app)
    assert first.patient_id == second.patient_id
    assert first.prescription_id != second.prescription_id


async def test_an_invalid_prescription_never_reaches_the_chain(app, ledger, vault):
    with pytest.raises(ExpiryInThePastError):
        await app.issue("dr-ana", "123", a_document(), timedelta(0))
    assert ledger.calls == []
    assert vault.documents == {}


async def test_dispensing_past_the_remainder_is_refused_before_sending(app, ledger):
    issued = await issue(app, quantity=30)
    await app.dispense("pharmacy-one", issued.prescription_id, 20)

    with pytest.raises(QuantityExceedsRemainingError):
        await app.dispense("pharmacy-one", issued.prescription_id, 11)
    assert ledger.calls.count("dispense") == 1  # the refused one was never sent


async def test_refusals_from_the_chain_reach_the_caller(app, ledger):
    issued = await issue(app)
    with pytest.raises(NotRegisteredError):
        await app.dispense("unknown-pharmacy", issued.prescription_id, 1)


async def test_dispensing_an_unknown_prescription(app):
    with pytest.raises(NotFoundError):
        await app.dispense("pharmacy-one", b"\x09" * 32, 1)


async def test_the_audit_trail_of_a_consistent_history(app):
    issued = await issue(app, quantity=30)
    await app.dispense("pharmacy-one", issued.prescription_id, 20)
    await app.dispense("pharmacy-one", issued.prescription_id, 10)

    trail = await app.audit(issued.prescription_id)

    assert trail.consistent
    assert trail.document_verified is True
    assert [d.remaining_after for d in trail.dispensations] == [10, 0]


async def test_the_audit_catches_an_altered_off_chain_document(app, vault):
    issued = await issue(app)
    patient_id, _original, salt = vault.documents[issued.prescription_id]
    vault.documents[issued.prescription_id] = (patient_id, a_document(quantity=90), salt)

    trail = await app.audit(issued.prescription_id)

    assert trail.document_verified is False
    assert not trail.consistent


async def test_the_audit_without_the_document_still_checks_the_chain(app, vault):
    issued = await issue(app)
    vault.documents.clear()  # e.g. an auditor without access to personal data

    trail = await app.audit(issued.prescription_id)

    assert trail.document_verified is None
    assert trail.consistent


async def test_the_audit_catches_a_missing_dispensation(app, ledger):
    issued = await issue(app)
    await app.dispense("pharmacy-one", issued.prescription_id, 5)
    ledger.dispensed[issued.prescription_id].clear()

    trail = await app.audit(issued.prescription_id)

    assert any("1 dispensations recorded, 0 found" in p for p in trail.problems)
