"""Demo data: participants for every role, enabled on-chain, a medication
catalog, and a few prescriptions to look at. Safe to run again: existing data
is kept.

Demo only. The cast, the catalog and the sample prescriptions will change as
the product does; nothing depends on them but the login page's account cards.
Active ingredients and ATC codes are real; every manufacturer and brand is
made up, because the demo plants suspicious patterns and must not point at a
real company.
"""

from datetime import UTC, datetime, timedelta

from asgiref.sync import sync_to_async
from django.conf import settings
from django.contrib.auth import get_user_model

from config import container
from records.models import CatalogMedication, CatalogProduct, Participant, PrescriptionRecord
from rxtrail.domain import MedicationDetails, PrescriptionDocument, ProductDetails, ProductKind

Role = Participant.Role

# (username, role, key name, display name, licence)
CAST = [
    (
        "council",
        Role.PROFESSIONAL_AUTHORITY,
        "professional-authority",
        "Regional Medical Council",
        "",
    ),
    ("health-agency", Role.HEALTH_AUTHORITY, "health-authority", "National Health Agency", ""),
    (
        "catalog-office",
        Role.CATALOG_AUTHORITY,
        "catalog-authority",
        "National Medication Registry",
        "",
    ),
    ("dr-ana", Role.PRESCRIBER, "dr-ana", "Dr. Ana Souza", "MED-123456"),
    ("dr-bruno", Role.PRESCRIBER, "dr-bruno", "Dr. Bruno Lima", "MED-654321"),
    ("pharmacy-one", Role.DISPENSER, "pharmacy-one", "Central Pharmacy", "PH-0001"),
    ("pharmacy-two", Role.DISPENSER, "pharmacy-two", "Corner Pharmacy", "PH-0002"),
    ("auditor", Role.AUDITOR, "", "Health Inspector", ""),
]

R, G = ProductKind.REFERENCE, ProductKind.GENERIC

# (medication, [(manufacturer, brand, kind)])
CATALOG = [
    (
        MedicationDetails(
            "Clonazepam 2 mg tablet",
            "clonazepam",
            "2 mg",
            "tablet",
            "N03AE01",
            "tablet",
            "B1",
            "0.5 to 4 mg a day, in divided doses",
            2,
            60,
            30,
        ),
        [
            ("Acme Pharma", "Calmazen 2 mg", R),
            ("Beta Labs", "Clonazepam Beta 2 mg", G),
            ("Gama Generics", "Clonazepam Gama 2 mg", G),
        ],
    ),
    (
        MedicationDetails(
            "Alprazolam 0.5 mg tablet",
            "alprazolam",
            "0.5 mg",
            "tablet",
            "N05BA12",
            "tablet",
            "B1",
            "0.25 to 0.5 mg three times a day; up to 4 mg a day",
            6,
            60,
            30,
        ),
        [("Acme Pharma", "Serenix 0.5 mg", R), ("Beta Labs", "Alprazolam Beta 0.5 mg", G)],
    ),
    (
        MedicationDetails(
            "Methylphenidate 10 mg tablet",
            "methylphenidate",
            "10 mg",
            "tablet",
            "N06BA04",
            "tablet",
            "A3",
            "5 to 60 mg a day, in the morning and at noon",
            6,
            60,
            30,
        ),
        [("Delta Pharma", "Focalis 10 mg", R), ("Gama Generics", "Methylphenidate Gama 10 mg", G)],
    ),
    (
        MedicationDetails(
            "Zolpidem 10 mg tablet",
            "zolpidem",
            "10 mg",
            "tablet",
            "N05CF02",
            "tablet",
            "B1",
            "10 mg at bedtime, for the shortest time possible",
            1,
            30,
            30,
        ),
        [("Delta Pharma", "Dormirex 10 mg", R), ("Beta Labs", "Zolpidem Beta 10 mg", G)],
    ),
    (
        MedicationDetails(
            "Citalopram 20 mg tablet",
            "citalopram",
            "20 mg",
            "tablet",
            "N06AB04",
            "tablet",
            "C1",
            "20 to 40 mg once a day",
            2,
            60,
            30,
        ),
        [("Gama Generics", "Citalopram Gama 20 mg", G)],
    ),
    (
        MedicationDetails(
            "Escitalopram 10 mg tablet",
            "escitalopram",
            "10 mg",
            "tablet",
            "N06AB10",
            "tablet",
            "C1",
            "10 to 20 mg once a day",
            2,
            60,
            30,
        ),
        [("Acme Pharma", "Lexacor 10 mg", R)],
    ),
]

SAMPLES = [
    # prescriber, patient doc, patient, medication, dosage, quantity, locked brand,
    # [(brand handed out by pharmacy-one, quantity)]
    (
        "dr-ana",
        "123.456.789-00",
        "Maria Silva",
        "Clonazepam 2 mg tablet",
        "1 tablet at night",
        30,
        None,
        [("Clonazepam Beta 2 mg", 20)],
    ),
    (
        "dr-ana",
        "987.654.321-00",
        "João Pereira",
        "Methylphenidate 10 mg tablet",
        "1 tablet in the morning",
        60,
        None,
        [],
    ),
    (
        "dr-bruno",
        "555.444.333-22",
        "Carla Mendes",
        "Alprazolam 0.5 mg tablet",
        "1 tablet if anxious",
        20,
        None,
        [("Serenix 0.5 mg", 10), ("Alprazolam Beta 0.5 mg", 10)],
    ),
    (
        "dr-bruno",
        "222.333.444-55",
        "Pedro Alves",
        "Zolpidem 10 mg tablet",
        "1 tablet at bedtime",
        30,
        "Dormirex 10 mg",
        [("Dormirex 10 mg", 10)],
    ),
]


def _ensure_users() -> list[str]:
    User = get_user_model()
    keys = container.key_store()
    created = []
    for username, role, key_name, display, licence in CAST:
        if key_name and not keys.exists(key_name):
            keys.create(key_name)
        if User.objects.filter(username=username).exists():
            continue
        user = User.objects.create_user(username, password=settings.RXTRAIL_DEMO_PASSWORD)
        Participant.objects.create(
            user=user, role=role, key_name=key_name, display_name=display, license_number=licence
        )
        created.append(username)
    return created


async def seed(log) -> None:
    for username in await sync_to_async(_ensure_users)():
        log(f"  login {username}")

    async with container.open_rxtrail() as (app, ledger):
        for _username, role, key_name, display, _ in CAST:
            kind = {Role.PRESCRIBER: "prescriber", Role.DISPENSER: "dispenser"}.get(role)
            if kind and await ledger.participant_status(kind, key_name) is None:
                authority = "professional-authority" if kind == "prescriber" else "health-authority"
                await getattr(app, f"enable_{kind}")(authority, key_name)
                log(f"  enabled {display} on-chain")

        if await CatalogMedication.objects.aexists():
            log("  catalog already exists")
        else:
            for medication, products in CATALOG:
                entry = await app.register_medication("catalog-authority", medication)
                for manufacturer, brand, kind in products:
                    await app.register_product(
                        "catalog-authority",
                        ProductDetails(entry.id.hex(), manufacturer, brand, kind),
                    )
                log(f"  catalog: {medication.name} ({len(products)} products)")

        if await PrescriptionRecord.objects.aexists():
            log("  sample prescriptions already exist")
            return
        today = datetime.now(UTC).date().isoformat()
        for prescriber, doc, patient, name, dosage, quantity, locked, dispensed in SAMPLES:
            medication = await CatalogMedication.objects.aget(name=name)
            document = PrescriptionDocument(
                medication_id=medication.medication_id,
                medication=medication.name,
                dosage=dosage,
                instructions="",
                quantity=quantity,
                prescriber_name=next(c[3] for c in CAST if c[2] == prescriber),
                patient_name=patient,
                issued_on=today,
                locked_product_id=locked and await _product_id(locked) or "",
            )
            issued = await app.issue(prescriber, doc, document, timedelta(days=30))
            for brand, amount in dispensed:
                product = bytes.fromhex(await _product_id(brand))
                await app.dispense("pharmacy-one", issued.prescription_id, product, amount)
            log(f"  {name} for {patient}: {issued.prescription_id.hex()}")


async def _product_id(brand: str) -> str:
    return (await CatalogProduct.objects.aget(brand_name=brand)).product_id
