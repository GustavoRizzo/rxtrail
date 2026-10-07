"""Use cases over in-memory ports."""

from datetime import timedelta

import pytest

from rxtrail import catalog, documents
from rxtrail.domain import (
    CatalogStatus,
    ExpiryInThePastError,
    MedicationDetails,
    MedicationNotActiveError,
    NotFoundError,
    NotRegisteredError,
    PrescribedProductMismatchError,
    ProductDetails,
    ProductKind,
    ProductNotActiveError,
    QuantityExceedsRemainingError,
)
from rxtrail.services import RxTrail
from tests.fakes import (
    GENERIC_ID,
    MEDICATION_ID,
    REFERENCE_ID,
    T0,
    FakeCatalog,
    FakeLedger,
    FakePatients,
    FakeVault,
    a_document,
    product_address,
)


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
def directory():
    return FakeCatalog()


@pytest.fixture
def app(ledger, vault, directory):
    return RxTrail(ledger, vault, FakePatients(), directory, now=lambda: T0)


async def issue(app, quantity=30, **changes):
    return await app.issue("dr-ana", "123", a_document(quantity, **changes), timedelta(days=30))


async def dispense(app, prescription_id, quantity, product=REFERENCE_ID):
    return await app.dispense("pharmacy-one", prescription_id, product, quantity)


async def test_issuing_puts_the_hash_on_chain_and_the_document_off_chain(app, ledger, vault):
    issued = await issue(app)

    on_chain = ledger.prescriptions[issued.prescription_id]
    patient_id, document, salt = vault.documents[issued.prescription_id]
    assert on_chain.document_hash == documents.document_hash(document, salt)
    assert patient_id == issued.patient_id  # off-chain only: nothing on-chain names the patient
    assert patient_id not in repr(on_chain).encode()
    assert on_chain.medication == ledger.medication_address(MEDICATION_ID)
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
    await dispense(app, issued.prescription_id, 20)

    with pytest.raises(QuantityExceedsRemainingError):
        await dispense(app, issued.prescription_id, 11)
    assert ledger.calls.count("dispense") == 1  # the refused one was never sent


async def test_refusals_from_the_chain_reach_the_caller(app, ledger):
    issued = await issue(app)
    with pytest.raises(NotRegisteredError):
        await app.dispense("unknown-pharmacy", issued.prescription_id, REFERENCE_ID, 1)


async def test_dispensing_an_unknown_prescription(app):
    with pytest.raises(NotFoundError):
        await dispense(app, b"\x09" * 32, 1)


async def test_the_audit_trail_of_a_consistent_history(app):
    issued = await issue(app, quantity=30)
    await dispense(app, issued.prescription_id, 20)
    await dispense(app, issued.prescription_id, 10)

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
    await dispense(app, issued.prescription_id, 5)
    ledger.dispensed[issued.prescription_id].clear()

    trail = await app.audit(issued.prescription_id)

    assert any("1 dispensations recorded, 0 found" in p for p in trail.problems)


async def test_a_chain_refusal_the_rules_did_not_foresee_is_still_an_error(app, ledger):
    from rxtrail.domain import TransactionRejectedError

    issued = await issue(app)

    async def refuses(*args):
        raise TransactionRejectedError("custom program error: 0x7d6")

    ledger.dispense = refuses  # the local check passes; the program says no

    with pytest.raises(TransactionRejectedError):
        await dispense(app, issued.prescription_id, 1)


async def test_a_suspended_prescriber_is_refused_by_the_ledger(app, ledger):
    await app.suspend_prescriber("professional-authority", "dr-ana")

    with pytest.raises(NotRegisteredError):
        await issue(app)

    await app.reinstate_prescriber("professional-authority", "dr-ana")
    await issue(app)


# -- catalog and recall ------------------------------------------------------------

CLONAZEPAM = MedicationDetails("Clonazepam 0.5 mg tablet", "clonazepam", "0.5 mg", "tablet")


async def test_registering_pins_the_catalog_record_on_chain(app, ledger, directory):
    entry = await app.register_medication("catalog-authority", CLONAZEPAM)

    address, details, digest = directory.medications[entry.id]
    on_chain = await ledger.medication(entry.id)
    assert details == CLONAZEPAM
    assert digest == entry.identity_hash == on_chain.identity_hash
    assert digest == catalog.identity_hash(CLONAZEPAM)
    assert address == on_chain.address == entry.receipt.address


async def test_a_product_is_registered_as_a_version_of_its_medication(app, ledger):
    medication = await app.register_medication("catalog-authority", CLONAZEPAM)
    details = ProductDetails(medication.id.hex(), "Beta Labs", "Clona Beta", ProductKind.GENERIC)

    product = await app.register_product("catalog-authority", details)

    assert (await ledger.product(product.id)).medication == ledger.medication_address(medication.id)


async def test_issuing_for_a_withdrawn_medication_never_reaches_the_chain(app, ledger):
    await app.withdraw_medication("catalog-authority", MEDICATION_ID)

    with pytest.raises(MedicationNotActiveError):
        await issue(app)
    assert "issue" not in ledger.calls


async def test_a_product_recall_sends_the_pharmacy_to_another_version(app, ledger):
    issued = await issue(app)
    await app.withdraw_product("catalog-authority", REFERENCE_ID)

    with pytest.raises(ProductNotActiveError):
        await dispense(app, issued.prescription_id, 5)
    await dispense(app, issued.prescription_id, 5, product=GENERIC_ID)

    await app.reinstate_product("catalog-authority", REFERENCE_ID)
    await dispense(app, issued.prescription_id, 5)
    assert ledger.prescriptions[issued.prescription_id].quantity_dispensed == 10


async def test_withdrawing_the_medication_freezes_the_prescription(app):
    issued = await issue(app)
    await dispense(app, issued.prescription_id, 10)

    await app.withdraw_medication("catalog-authority", MEDICATION_ID)
    with pytest.raises(MedicationNotActiveError):
        await dispense(app, issued.prescription_id, 5, product=GENERIC_ID)
    assert (await app.audit(issued.prescription_id)).frozen

    await app.reinstate_medication("catalog-authority", MEDICATION_ID)
    trail = await app.audit(issued.prescription_id)
    assert not trail.frozen and trail.medication.status is CatalogStatus.ACTIVE


async def test_a_locked_product_is_the_only_one_dispensable(app, ledger):
    issued = await issue(app, locked_product_id=REFERENCE_ID.hex())

    assert ledger.prescriptions[issued.prescription_id].prescribed_product == product_address(
        REFERENCE_ID
    )
    with pytest.raises(PrescribedProductMismatchError):
        await dispense(app, issued.prescription_id, 1, product=GENERIC_ID)
    await dispense(app, issued.prescription_id, 1)


async def test_locking_an_unknown_product_is_refused(app):
    with pytest.raises(NotFoundError):
        await issue(app, locked_product_id=(b"\xee" * 32).hex())
