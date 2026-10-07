"""The off-chain store on Postgres."""

import psycopg
import pytest
from django.conf import settings
from django.db import IntegrityError

from records.models import Patient, PrescriptionRecord
from records.repositories import DjangoDocumentVault, DjangoPatientDirectory
from tests.fakes import a_document

pytestmark = pytest.mark.django_db(transaction=True)


async def test_a_patient_gets_one_random_id_on_first_sight():
    directory = DjangoPatientDirectory()

    first = await directory.patient_id_for("123.456.789-00", "Maria Silva")
    again = await directory.patient_id_for("123.456.789-00", "Maria Silva")
    other = await directory.patient_id_for("987.654.321-00", "João Souza")

    assert first == again != other
    assert len(first) == 32
    # The on-chain id is random: nothing of the document number is in it.
    assert b"123" not in first


async def test_documents_round_trip_with_their_salt():
    patient_id = await DjangoPatientDirectory().patient_id_for("1", "Maria")
    vault = DjangoDocumentVault()

    await vault.store(b"\x01" * 32, patient_id, "dr", a_document(), b"\x07" * 32)

    assert await vault.fetch(b"\x01" * 32) == (a_document(), b"\x07" * 32)
    assert await vault.fetch(b"\x02" * 32) is None


async def test_a_prescription_id_is_stored_once():
    patient_id = await DjangoPatientDirectory().patient_id_for("1", "Maria")
    vault = DjangoDocumentVault()
    await vault.store(b"\x01" * 32, patient_id, "dr", a_document(), b"\x07" * 32)

    with pytest.raises(IntegrityError):
        await vault.store(b"\x01" * 32, patient_id, "dr", a_document(), b"\x08" * 32)


def test_deleting_a_patient_with_prescriptions_is_refused():
    # Anonymization unlinks identity; it must not orphan prescription documents.
    from asgiref.sync import async_to_sync

    patient_id = async_to_sync(DjangoPatientDirectory().patient_id_for)("1", "Maria")
    async_to_sync(DjangoDocumentVault().store)(
        b"\x01" * 32, patient_id, "dr", a_document(), b"\x07" * 32
    )

    with pytest.raises(Exception, match="protected"):
        Patient.objects.get(patient_id=patient_id.hex()).delete()
    assert PrescriptionRecord.objects.count() == 1


def test_the_app_user_cannot_create_tables_outside_its_schema():
    cfg = settings.DATABASES["default"]
    with (
        psycopg.connect(
            dbname=cfg["NAME"],
            user=cfg["USER"],
            password=cfg["PASSWORD"],
            host=cfg["HOST"],
            port=cfg["PORT"],
            autocommit=True,
        ) as conn,
        pytest.raises(psycopg.errors.InsufficientPrivilege),
    ):
        conn.execute("create table public.sneaky (id int)")
