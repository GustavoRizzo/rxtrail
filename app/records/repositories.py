"""Django adapters for the domain's DocumentVault and PatientDirectory ports."""

from records.models import Patient, PrescriptionRecord
from rxtrail.domain import PrescriptionDocument, new_id


class DjangoPatientDirectory:
    async def patient_id_for(self, document_number: str, name: str) -> bytes:
        patient, _ = await Patient.objects.aget_or_create(
            document_number=document_number,
            defaults={"name": name, "patient_id": new_id().hex()},
        )
        return bytes.fromhex(patient.patient_id)


class DjangoDocumentVault:
    async def store(
        self,
        prescription_id: bytes,
        patient_id: bytes,
        prescriber: str,
        document: PrescriptionDocument,
        salt: bytes,
    ) -> None:
        patient = await Patient.objects.aget(patient_id=patient_id.hex())
        await PrescriptionRecord.objects.acreate(
            prescription_id=prescription_id.hex(),
            prescriber=prescriber,
            patient=patient,
            document={field: getattr(document, field) for field in PrescriptionDocument.__slots__},
            salt=salt.hex(),
        )

    async def fetch(self, prescription_id: bytes) -> tuple[PrescriptionDocument, bytes] | None:
        record = await PrescriptionRecord.objects.filter(
            prescription_id=prescription_id.hex()
        ).afirst()
        if record is None:
            return None
        return PrescriptionDocument(**record.document), bytes.fromhex(record.salt)
