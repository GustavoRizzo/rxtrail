"""Web pages over HTTP, with the chain faked out: who sees and does what."""

from contextlib import asynccontextmanager
from dataclasses import replace

import pytest
from django.contrib.auth import get_user_model

from records.models import (
    Activity,
    CatalogMedication,
    CatalogProduct,
    Manufacturer,
    Participant,
    PrescriptionRecord,
)
from records.repositories import DjangoCatalog, DjangoDocumentVault, DjangoPatientDirectory
from rxtrail.domain import CatalogStatus
from rxtrail.services import RxTrail
from solana_client.keystore import FileKeyStore
from tests.fakes import (
    GENERIC_ID,
    MEDICATION_ID,
    REFERENCE_ID,
    FakeLedger,
    medication_address,
    product_address,
)

pytestmark = pytest.mark.django_db(transaction=True)
Role = Participant.Role


@pytest.fixture
def ledger(monkeypatch, tmp_path):
    ledger = FakeLedger()
    keys = FileKeyStore(tmp_path / "keys")

    @asynccontextmanager
    async def fake_open():
        app = RxTrail(ledger, DjangoDocumentVault(), DjangoPatientDirectory(), DjangoCatalog())
        yield app, ledger

    monkeypatch.setattr("config.container.open_rxtrail", fake_open)
    monkeypatch.setattr("config.container.key_store", lambda: keys)
    stock_catalog()
    return ledger


def stock_catalog():
    """The off-chain side of the medication and products FakeLedger starts with."""
    medication = CatalogMedication.objects.create(
        medication_id=MEDICATION_ID.hex(),
        address=medication_address(MEDICATION_ID),
        identity_hash="00" * 32,
        name="Clonazepam 2 mg tablet",
        active_ingredient="clonazepam",
        strength="2 mg",
        form="tablet",
        atc_code="N03AE01",
        unit="tablet",
        max_quantity=60,
    )
    for product_id, maker, brand, kind in [
        (REFERENCE_ID, "Acme Pharma", "Calmazen 2 mg", "reference"),
        (GENERIC_ID, "Beta Labs", "Clonazepam Beta", "generic"),
    ]:
        CatalogProduct.objects.create(
            product_id=product_id.hex(),
            address=product_address(product_id),
            identity_hash=product_id.hex(),
            medication=medication,
            manufacturer=Manufacturer.objects.create(name=maker),
            brand_name=brand,
            kind=kind,
        )


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
        "registry": make("registry", Role.CATALOG_AUTHORITY),
        "inspector": make("inspector", Role.AUDITOR, key_name=""),
    }
    ledger.prescribers.add("dr")
    ledger.dispensers.add("pharmacy")
    return people


def issue(client, **changes):
    client.login(username="dr", password="pw")
    response = client.post(
        "/prescriber/",
        {
            "patient_name": "Maria Silva",
            "patient_document": "123",
            "medication_id": MEDICATION_ID.hex(),
            "dosage": "1 at night",
            "quantity": 30,
            "valid_days": 30,
            **changes,
        },
    )
    client.logout()
    return response, PrescriptionRecord.objects.get().prescription_id


def dispense(client, rx, quantity, product=REFERENCE_ID):
    client.login(username="pharmacy", password="pw")
    return client.post(
        "/dispenser/dispense/",
        {"prescription_id": rx, "product_id": product.hex(), "quantity": quantity},
        follow=True,
    )


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
        ("registry", "/catalog-office/"),
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
    assert (record.prescriber, record.document["medication"]) == ("dr", "Clonazepam 2 mg tablet")
    assert record.document["medication_id"] == MEDICATION_ID.hex()
    assert Activity.objects.get().action == "issue"


def issue_many(client, *prescriptions):
    client.login(username="dr", password="pw")
    other = CatalogMedication.objects.create(
        medication_id="cc" * 32,
        address="med-other",
        identity_hash="cc" * 32,
        name="Methylphenidate 10 mg tablet",
        active_ingredient="methylphenidate",
        strength="10 mg",
        form="tablet",
    )
    ledger_medications = {"Clonazepam": MEDICATION_ID.hex(), "Methylphenidate": other.medication_id}
    for patient, medication, quantity in prescriptions:
        client.post(
            "/prescriber/",
            {
                "patient_name": patient,
                "patient_document": patient,
                "medication_id": ledger_medications[medication],
                "dosage": "1 a day",
                "quantity": quantity,
                "valid_days": 30,
            },
        )
    return {r.patient.name: r.prescription_id for r in PrescriptionRecord.objects.all()}


def card_order(page, *names):
    return sorted(names, key=page.index)


def test_the_prescriber_searches_filters_and_sorts(client, cast, ledger):
    ledger._add_medication(b"\xcc" * 32, b"\x00" * 32)  # Methylphenidate, on the fake chain
    ids = issue_many(
        client,
        ("Maria Silva", "Clonazepam", 30),
        ("João Pereira", "Methylphenidate", 60),
        ("Ana Costa", "Clonazepam", 10),
    )
    ledger.prescriptions[bytes.fromhex(ids["Ana Costa"])] = replace(
        ledger.prescriptions[bytes.fromhex(ids["Ana Costa"])], quantity_dispensed=10
    )

    page = client.get("/prescriber/", {"q": "clonazepam"}).content.decode()
    assert "Maria Silva" in page and "Ana Costa" in page and "João Pereira" not in page
    assert "2 of 3 prescriptions match" in page

    page = client.get("/prescriber/", {"q": "joão"}).content.decode()
    assert "João Pereira" in page and "Maria Silva" not in page

    page = client.get("/prescriber/", {"standing": "completed"}).content.decode()
    assert "Ana Costa" in page and "Completed" in page and "Maria Silva" not in page

    page = client.get("/prescriber/", {"sort": "remaining"}).content.decode()
    assert card_order(page, "Ana Costa", "Maria Silva", "João Pereira") == [
        "João Pereira",
        "Maria Silva",
        "Ana Costa",
    ]

    page = client.get("/prescriber/", {"issued_to": "2000-01-01"}).content.decode()
    assert "No prescriptions match these filters" in page


def test_a_prescription_card_shows_its_dates_not_its_id(client, cast):
    _, rx = issue(client)
    client.login(username="dr", password="pw")

    page = client.get("/prescriber/").content.decode()

    assert "Issued Oct 1, 2026" in page and "Expires" in page
    assert rx[:6] not in page.replace(f"/rx/{rx}/", "")


def test_a_refusal_is_shown_and_nothing_is_logged(client, cast):
    _, rx = issue(client)

    page = dispense(client, rx, 31)

    assert "QuantityExceedsRemaining" in page.content.decode()
    assert not Activity.objects.filter(action="dispense").exists()


def test_a_dispensation_lands_and_is_logged(client, cast, ledger):
    _, rx = issue(client)

    dispense(client, rx, 10, product=GENERIC_ID)

    assert ledger.prescriptions[bytes.fromhex(rx)].quantity_dispensed == 10
    assert ledger.dispensed[bytes.fromhex(rx)][0].product == product_address(GENERIC_ID)
    assert Activity.objects.get(action="dispense").summary == "Dispensed 10 × Clonazepam Beta"


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


def test_the_style_guide_exists_only_in_development(client, settings):
    settings.DEBUG = True
    page = client.get("/styleguide/").content.decode()
    assert "tokens.css" in page and "--brand-primary" in page
    settings.DEBUG = False
    assert client.get("/styleguide/").status_code == 404


def test_password_fields_can_be_revealed(client, cast):
    login = client.get("/login/").content.decode()
    assert "Show password" in login and "eye-off" in login


def test_authors_are_credited_in_the_footer_and_metadata(client, settings):
    settings.RXTRAIL_AUTHORS = [{"name": "Ada Example", "github": "https://github.com/ada"}]
    page = client.get("/").content.decode()
    assert '<meta name="author" content="Ada Example">' in page
    assert "Built by" in page and "https://github.com/ada" in page


# -- catalog ---------------------------------------------------------------------------


def test_the_medication_picker_searches_by_ingredient_brand_and_maker(client, cast):
    client.login(username="dr", password="pw")

    for query in ("clonaz", "calmazen", "beta labs", "N03A"):
        page = client.get("/catalog/search/", {"q": query}).content.decode()
        assert "Clonazepam 2 mg tablet" in page, query
    page = client.get("/catalog/search/", {"q": "insulin"}).content.decode()
    assert "No medication matches" in page


def test_the_picker_starts_with_the_prescribers_most_used(client, cast):
    issue(client)
    client.login(username="dr", password="pw")

    page = client.get("/catalog/search/").content.decode()

    assert "Your most prescribed" in page and "Clonazepam 2 mg tablet" in page


def test_only_prescribers_search_the_picker(client, cast):
    client.login(username="pharmacy", password="pw")
    assert client.get("/catalog/search/")["Location"] == "/home/"


def test_a_prescription_needs_a_catalog_medication(client, cast, ledger):
    client.login(username="dr", password="pw")

    page = client.post(
        "/prescriber/",
        {
            "patient_name": "Maria",
            "patient_document": "1",
            "medication_id": "ee" * 32,
            "dosage": "1",
            "quantity": 1,
            "valid_days": 1,
        },
    ).content.decode()

    assert "Choose a medication from the catalog" in page
    assert ledger.prescriptions == {}


def test_a_quantity_above_the_limit_warns_but_is_issued(client, cast, ledger):
    client.login(username="dr", password="pw")

    page = client.post(
        "/prescriber/",
        {
            "patient_name": "Maria",
            "patient_document": "1",
            "medication_id": MEDICATION_ID.hex(),
            "dosage": "1",
            "quantity": 90,
            "valid_days": 30,
        },
        follow=True,
    ).content.decode()

    assert len(ledger.prescriptions) == 1
    assert "above the regulatory limit of 60" in page


def test_a_locked_brand_is_the_only_one_the_pharmacy_can_hand_out(client, cast, ledger):
    _, rx = issue(client, locked_product_id=REFERENCE_ID.hex())

    page = dispense(client, rx, 5, product=GENERIC_ID).content.decode()
    assert "PrescribedProductMismatch" in page
    counter = client.get("/dispenser/", {"rx": rx}).content.decode()
    assert "not the locked brand" in counter and "substitution is not allowed" in counter

    dispense(client, rx, 5, product=REFERENCE_ID)
    assert ledger.prescriptions[bytes.fromhex(rx)].quantity_dispensed == 5


def test_the_catalog_authority_registers_a_medication_and_a_product(client, cast, ledger):
    client.login(username="registry", password="pw")

    client.post(
        "/catalog-office/medication/",
        {
            "name": "Zolpidem 10 mg tablet",
            "active_ingredient": "zolpidem",
            "strength": "10 mg",
            "form": "tablet",
            "unit": "tablet",
        },
    )
    zolpidem = CatalogMedication.objects.get(active_ingredient="zolpidem")
    client.post(
        "/catalog-office/product/",
        {
            "medication_id": zolpidem.medication_id,
            "manufacturer": "Delta Pharma",
            "brand_name": "Dormirex",
            "kind": "reference",
        },
    )

    product = CatalogProduct.objects.get(brand_name="Dormirex")
    assert ledger.catalog[zolpidem.address].identity_hash.hex() == zolpidem.identity_hash
    assert ledger.catalog[product.address].medication == zolpidem.address
    page = client.get("/catalog-office/").content.decode()
    assert "Zolpidem 10 mg tablet" in page and "Dormirex" in page


def test_a_recall_freezes_the_prescription_for_every_pharmacy(client, cast, ledger):
    _, rx = issue(client)
    client.login(username="registry", password="pw")

    client.post(
        "/catalog-office/status/",
        {"kind": "medication", "id": MEDICATION_ID.hex(), "verb": "withdraw"},
    )

    assert ledger.catalog[medication_address(MEDICATION_ID)].status is CatalogStatus.WITHDRAWN
    assert "MedicationNotActive" in dispense(client, rx, 1).content.decode()
    assert "Frozen" in client.get("/dispenser/", {"rx": rx}).content.decode()
    client.logout()
    assert "Frozen · medication withdrawn" in client.get(f"/rx/{rx}/").content.decode()


def test_a_product_recall_leaves_the_other_versions_dispensable(client, cast, ledger):
    _, rx = issue(client)
    client.login(username="registry", password="pw")
    client.post(
        "/catalog-office/status/", {"kind": "product", "id": REFERENCE_ID.hex(), "verb": "withdraw"}
    )

    assert "ProductNotActive" in dispense(client, rx, 1).content.decode()
    assert "(withdrawn)" in client.get("/dispenser/", {"rx": rx}).content.decode()
    dispense(client, rx, 1, product=GENERIC_ID)
    assert ledger.prescriptions[bytes.fromhex(rx)].quantity_dispensed == 1


def test_only_the_catalog_authority_keeps_the_catalog(client, cast, ledger):
    client.login(username="council", password="pw")

    response = client.post(
        "/catalog-office/status/",
        {"kind": "medication", "id": MEDICATION_ID.hex(), "verb": "withdraw"},
    )

    assert response["Location"] == "/home/"
    assert ledger.catalog[medication_address(MEDICATION_ID)].status is CatalogStatus.ACTIVE


def test_the_medication_is_public_but_the_patient_is_not(client, cast):
    _, rx = issue(client)
    dispense(client, rx, 5)
    client.logout()

    page = client.get(f"/rx/{rx}/").content.decode()

    assert "Clonazepam 2 mg tablet" in page and "Calmazen 2 mg" in page
    assert "Maria Silva" not in page


def test_the_public_catalog_and_its_open_data(client, cast):
    page = client.get("/catalog/").content.decode()
    assert "Clonazepam 2 mg tablet" in page and "Download (JSON)" in page

    data = client.get("/catalog.json").json()

    (medication,) = data["medications"]
    assert medication["id"] == MEDICATION_ID.hex()
    assert medication["address"] == medication_address(MEDICATION_ID)
    assert {p["brand_name"] for p in medication["products"]} == {"Calmazen 2 mg", "Clonazepam Beta"}
    assert data["identity_fields"]["medication"] == ["active_ingredient", "strength", "form"]
