"""Django adapters for the domain's DocumentVault, PatientDirectory and
CatalogDirectory ports."""

from records.models import (
    CatalogMedication,
    CatalogProduct,
    Manufacturer,
    Patient,
    PrescriptionRecord,
)
from rxtrail.domain import MedicationDetails, PrescriptionDocument, ProductDetails, new_id

_MEDICATION_FIELDS = MedicationDetails.__slots__


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

    async def record_closure_note(self, prescription_id: bytes, note: str) -> None:
        await PrescriptionRecord.objects.filter(prescription_id=prescription_id.hex()).aupdate(
            closure_note=note
        )


class DjangoCatalog:
    async def add_medication(
        self, medication_id: bytes, address: str, details: MedicationDetails, identity_hash: bytes
    ) -> None:
        await CatalogMedication.objects.acreate(
            medication_id=medication_id.hex(),
            address=address,
            identity_hash=identity_hash.hex(),
            **{field: getattr(details, field) for field in _MEDICATION_FIELDS},
        )

    async def add_product(
        self, product_id: bytes, address: str, details: ProductDetails, identity_hash: bytes
    ) -> None:
        medication = await CatalogMedication.objects.aget(medication_id=details.medication_id)
        manufacturer, _ = await Manufacturer.objects.aget_or_create(name=details.manufacturer)
        await CatalogProduct.objects.acreate(
            product_id=product_id.hex(),
            address=address,
            identity_hash=identity_hash.hex(),
            medication=medication,
            manufacturer=manufacturer,
            brand_name=details.brand_name,
            kind=details.kind,
        )

    async def medication(self, medication_id: bytes) -> MedicationDetails | None:
        record = await CatalogMedication.objects.filter(medication_id=medication_id.hex()).afirst()
        return None if record is None else medication_details(record)


def medication_details(record: CatalogMedication) -> MedicationDetails:
    return MedicationDetails(**{field: getattr(record, field) for field in _MEDICATION_FIELDS})


def product_details(record: CatalogProduct) -> ProductDetails:
    """Needs `medication` and `manufacturer` loaded (select_related)."""
    return ProductDetails(
        medication_id=record.medication.medication_id,
        manufacturer=record.manufacturer.name,
        brand_name=record.brand_name,
        kind=record.kind,
    )
