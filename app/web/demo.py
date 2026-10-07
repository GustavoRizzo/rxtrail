"""Demo data: participants for every role, enabled on-chain, and a few
prescriptions to look at. Safe to run again: existing data is kept.

Demo only. The cast and the sample prescriptions will change as the product
does; nothing depends on them but the login page's account cards.
"""

from datetime import UTC, datetime, timedelta

from asgiref.sync import sync_to_async
from django.conf import settings
from django.contrib.auth import get_user_model

from config import container
from records.models import Participant, PrescriptionRecord
from rxtrail.domain import PrescriptionDocument

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
    ("dr-ana", Role.PRESCRIBER, "dr-ana", "Dr. Ana Souza", "MED-123456"),
    ("dr-bruno", Role.PRESCRIBER, "dr-bruno", "Dr. Bruno Lima", "MED-654321"),
    ("pharmacy-one", Role.DISPENSER, "pharmacy-one", "Central Pharmacy", "PH-0001"),
    ("pharmacy-two", Role.DISPENSER, "pharmacy-two", "Corner Pharmacy", "PH-0002"),
    ("auditor", Role.AUDITOR, "", "Health Inspector", ""),
]

SAMPLES = [
    # prescriber, patient doc, patient, medication, dosage, quantity, dispensed by pharmacy-one
    ("dr-ana", "123.456.789-00", "Maria Silva", "Clonazepam 2mg", "1 tablet at night", 30, [20]),
    (
        "dr-ana",
        "987.654.321-00",
        "João Pereira",
        "Methylphenidate 10mg",
        "1 tablet in the morning",
        60,
        [],
    ),
    (
        "dr-bruno",
        "555.444.333-22",
        "Carla Mendes",
        "Alprazolam 0.5mg",
        "1 tablet if anxious",
        20,
        [10, 10],
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

        if await PrescriptionRecord.objects.aexists():
            log("  sample prescriptions already exist")
            return
        today = datetime.now(UTC).date().isoformat()
        for prescriber, doc, patient, medication, dosage, quantity, dispensed in SAMPLES:
            document = PrescriptionDocument(
                medication=medication,
                dosage=dosage,
                instructions="",
                quantity=quantity,
                prescriber_name=next(c[3] for c in CAST if c[2] == prescriber),
                patient_name=patient,
                issued_on=today,
            )
            issued = await app.issue(prescriber, doc, document, timedelta(days=30))
            for amount in dispensed:
                await app.dispense("pharmacy-one", issued.prescription_id, amount)
            log(f"  {medication} for {patient}: {issued.prescription_id.hex()}")
