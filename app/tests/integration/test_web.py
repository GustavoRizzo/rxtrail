"""Web pages over HTTP, with the chain faked out: who sees and does what."""

from contextlib import asynccontextmanager

import pytest
from django.contrib.auth import get_user_model

from records.models import Activity, Participant, PrescriptionRecord
from records.repositories import DjangoDocumentVault, DjangoPatientDirectory
from rxtrail.services import RxTrail
from solana_client.keystore import FileKeyStore
from tests.fakes import FakeLedger

pytestmark = pytest.mark.django_db(transaction=True)
Role = Participant.Role


@pytest.fixture
def ledger(monkeypatch, tmp_path):
    ledger = FakeLedger()
    keys = FileKeyStore(tmp_path / "keys")

    @asynccontextmanager
    async def fake_open():
        yield RxTrail(ledger, DjangoDocumentVault(), DjangoPatientDirectory()), ledger

    monkeypatch.setattr("config.container.open_rxtrail", fake_open)
    monkeypatch.setattr("config.container.key_store", lambda: keys)
    return ledger


def make(username, role, key_name=None):
    user = get_user_model().objects.create_user(username, password="pw")
    return Participant.objects.create(
        user=user, role=role, key_name=key_name or username, display_name=username.title()
    )


@pytest.fixture
def cast(ledger):
    people = {
        "dr": make("dr", Role.PRESCRIBER),
        "pharmacy": make("pharmacy", Role.DISPENSER),
        "council": make("council", Role.PROFESSIONAL_AUTHORITY),
        "inspector": make("inspector", Role.AUDITOR, key_name=""),
    }
    ledger.prescribers.add("dr")
    ledger.dispensers.add("pharmacy")
    return people


def issue(client):
    client.login(username="dr", password="pw")
    response = client.post(
        "/prescriber/",
        {
            "patient_name": "Maria Silva",
            "patient_document": "123",
            "medication": "Clonazepam 2mg",
            "dosage": "1 at night",
            "quantity": 30,
            "valid_days": 30,
        },
    )
    client.logout()
    return response, PrescriptionRecord.objects.get().prescription_id


def test_the_landing_and_login_pages_render(client, cast):
    assert "Every pill accounted for" in client.get("/").content.decode()
    login = client.get("/login/").content.decode()
    assert "Demo accounts" in login and "Dr" in login


@pytest.mark.parametrize(
    ("user", "dashboard"),
    [
        ("dr", "/prescriber/"),
        ("pharmacy", "/dispenser/"),
        ("council", "/authority/"),
        ("inspector", "/auditor/"),
    ],
)
def test_each_role_lands_on_its_dashboard(client, cast, user, dashboard):
    client.login(username=user, password="pw")
    assert client.get("/home/")["Location"] == dashboard
    assert client.get(dashboard).status_code == 200


def test_a_role_cannot_open_another_roles_dashboard(client, cast):
    client.login(username="pharmacy", password="pw")
    assert client.get("/prescriber/")["Location"] == "/home/"


def test_issuing_records_the_document_and_the_activity(client, cast):
    response, rx = issue(client)

    assert response["Location"] == f"/rx/{rx}/"
    record = PrescriptionRecord.objects.get()
    assert (record.prescriber, record.document["medication"]) == ("dr", "Clonazepam 2mg")
    assert Activity.objects.get().action == "issue"


def test_a_refusal_is_shown_and_nothing_is_logged(client, cast):
    _, rx = issue(client)
    client.login(username="pharmacy", password="pw")

    page = client.post("/dispenser/dispense/", {"prescription_id": rx, "quantity": 31}, follow=True)

    assert "QuantityExceedsRemaining" in page.content.decode()
    assert not Activity.objects.filter(action="dispense").exists()


def test_a_dispensation_lands_and_is_logged(client, cast, ledger):
    _, rx = issue(client)
    client.login(username="pharmacy", password="pw")

    client.post("/dispenser/dispense/", {"prescription_id": rx, "quantity": 10})

    assert ledger.prescriptions[bytes.fromhex(rx)].quantity_dispensed == 10
    assert Activity.objects.filter(action="dispense").count() == 1


def test_personal_data_is_shown_to_the_prescriber_but_not_to_the_auditor(client, cast):
    _, rx = issue(client)

    client.login(username="dr", password="pw")
    assert "Maria Silva" in client.get(f"/rx/{rx}/").content.decode()
    client.logout()
    client.login(username="inspector", password="pw")
    page = client.get(f"/rx/{rx}/").content.decode()
    assert "Maria Silva" not in page
    assert "History verified" in page  # the verdict, without the data


def test_the_authority_suspends_and_reinstates(client, cast, ledger):
    client.login(username="council", password="pw")

    client.post("/authority/status/", {"key_name": "dr", "verb": "suspend"})
    assert "dr" not in ledger.prescribers
    client.post("/authority/status/", {"key_name": "dr", "verb": "reinstate"})
    assert "dr" in ledger.prescribers


def test_the_authority_enables_a_new_prescriber_with_a_login(client, cast, ledger):
    client.login(username="council", password="pw")

    client.post(
        "/authority/enable/",
        {"display_name": "Dr. New", "username": "dr-new", "password": "long-enough"},
    )

    assert "dr-new" in ledger.prescribers
    assert client.login(username="dr-new", password="long-enough")
    assert Participant.objects.get(key_name="dr-new").role == Role.PRESCRIBER


def test_verify_rejects_a_malformed_id(client, cast):
    response = client.get("/verify/?id=abc", follow=True)
    assert "64 hexadecimal characters" in response.content.decode()
