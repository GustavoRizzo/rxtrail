"""The full flow against the deployed program: the chain is the authority."""

from datetime import UTC, datetime, timedelta

import pytest

from records.repositories import DjangoDocumentVault, DjangoPatientDirectory
from rxtrail.domain import (
    NotHealthAuthorityError,
    NotRegisteredError,
    QuantityExceedsRemainingError,
    new_id,
)
from rxtrail.services import RxTrail
from tests.fakes import a_document

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
async def enabled(ledger, fresh):
    prescriber, dispenser = fresh("dr"), fresh("pharmacy")
    await ledger.register_prescriber("professional-authority", prescriber)
    await ledger.register_dispenser("health-authority", dispenser)
    return prescriber, dispenser


@pytest.fixture
def app(ledger):
    return RxTrail(ledger, DjangoDocumentVault(), DjangoPatientDirectory())


async def test_issue_dispense_and_audit(app, enabled):
    prescriber, dispenser = enabled
    issued = await app.issue(prescriber, "123", a_document(quantity=30), timedelta(days=30))

    await app.dispense(dispenser, issued.prescription_id, 20)
    await app.dispense(dispenser, issued.prescription_id, 10)
    trail = await app.audit(issued.prescription_id)

    assert trail.consistent
    assert trail.document_verified is True
    assert trail.prescription.remaining == 0
    assert [d.quantity for d in trail.dispensations] == [20, 10]


async def test_the_program_itself_refuses_over_dispensing(app, ledger, enabled):
    prescriber, dispenser = enabled
    issued = await app.issue(prescriber, "123", a_document(quantity=30), timedelta(days=30))
    await ledger.dispense(dispenser, issued.prescription_id, 25)

    # Straight to the ledger, skipping the Python pre-check: the refusal below
    # comes from the on-chain program, mapped back to the domain error.
    with pytest.raises(QuantityExceedsRemainingError):
        await ledger.dispense(dispenser, issued.prescription_id, 6)
    assert (await ledger.prescription(issued.prescription_id)).quantity_dispensed == 25


async def test_an_unregistered_dispenser_is_refused_by_the_program(app, ledger, enabled, fresh):
    prescriber, _ = enabled
    issued = await app.issue(prescriber, "123", a_document(), timedelta(days=30))

    with pytest.raises(NotRegisteredError):
        await ledger.dispense(fresh("stranger"), issued.prescription_id, 1)


async def test_the_operator_cannot_issue_in_a_prescribers_name(ledger):
    with pytest.raises(NotRegisteredError):
        await ledger.issue_prescription(
            "operator",
            new_id(),
            new_id(),
            new_id(),
            30,
            datetime.now(UTC) + timedelta(days=1),
        )


async def test_only_the_health_authority_enables_dispensers(ledger, fresh):
    with pytest.raises(NotHealthAuthorityError):
        await ledger.register_dispenser("professional-authority", fresh("pharmacy"))


async def test_a_refusal_the_app_does_not_model_is_still_an_error(ledger, enabled):
    from rxtrail.domain import TransactionRejectedError

    prescriber, _ = enabled
    prescription_id = new_id()
    expires = datetime.now(UTC) + timedelta(days=1)
    await ledger.issue_prescription(prescriber, prescription_id, new_id(), new_id(), 10, expires)

    # Same id again: no Python rule checks this; only the program knows the
    # prescription account already exists, and it refuses.
    with pytest.raises(TransactionRejectedError):
        await ledger.issue_prescription(
            prescriber, prescription_id, new_id(), new_id(), 99, expires
        )
    assert (await ledger.prescription(prescription_id)).quantity_granted == 10


async def test_suspending_a_prescriber_freezes_their_prescriptions(app, ledger, enabled):
    from rxtrail.domain import PrescriberNotActiveError

    prescriber, dispenser = enabled
    issued = await app.issue(prescriber, "123", a_document(quantity=30), timedelta(days=30))
    await app.dispense(dispenser, issued.prescription_id, 10)

    await app.suspend_prescriber("professional-authority", prescriber)
    with pytest.raises(PrescriberNotActiveError):
        await ledger.dispense(dispenser, issued.prescription_id, 5)

    await app.reinstate_prescriber("professional-authority", prescriber)
    await app.dispense(dispenser, issued.prescription_id, 5)
    assert (await ledger.prescription(issued.prescription_id)).quantity_dispensed == 15


async def test_five_pharmacies_racing_never_exceed_the_grant(app, ledger, fresh):
    """The core promise under real concurrency: 5 pharmacies ask for 10 each,
    at the same time, against a prescription of 30."""
    import asyncio

    prescriber = fresh("dr")
    await ledger.register_prescriber("professional-authority", prescriber)
    pharmacies = [fresh("pharmacy") for _ in range(5)]
    for pharmacy in pharmacies:
        await ledger.register_dispenser("health-authority", pharmacy)
    issued = await app.issue(prescriber, "123", a_document(quantity=30), timedelta(days=30))

    # Straight to the ledger, all at once: no Python pre-check can serialize them.
    results = await asyncio.gather(
        *(ledger.dispense(p, issued.prescription_id, 10) for p in pharmacies),
        return_exceptions=True,
    )

    landed = [r for r in results if not isinstance(r, BaseException)]
    refused = [r for r in results if isinstance(r, BaseException)]
    assert len(landed) == 3
    assert len(refused) == 2
    assert all(isinstance(r, QuantityExceedsRemainingError) for r in refused), refused
    trail = await app.audit(issued.prescription_id)
    assert trail.consistent
    assert trail.prescription.quantity_dispensed == 30
    assert len(trail.dispensations) == 3
