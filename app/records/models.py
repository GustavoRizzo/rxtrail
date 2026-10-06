from django.db import models


class Patient(models.Model):
    """A real person, and the random id that stands for them on-chain."""

    # National id, passport... whatever the country uses. Unique per patient.
    document_number = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=200)
    # Hex of the random 32-byte id used on-chain. Never derived from the above.
    patient_id = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class PrescriptionRecord(models.Model):
    """The full prescription document behind an on-chain prescription."""

    prescription_id = models.CharField(max_length=64, unique=True)
    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="prescriptions")
    # The document exactly as hashed (see rxtrail.documents.canonical_bytes).
    document = models.JSONField()
    # Hex of the random salt mixed into the on-chain hash.
    salt = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.prescription_id


class ChainBinding(models.Model):
    """Which chain this database belongs to. One row, written on first use.

    Off-chain records point at on-chain prescriptions that exist on exactly
    one chain. The genesis hash identifies it: devnet and a local validator
    have different ones, and resetting a local validator creates a new one.
    The app refuses to run when they disagree, instead of silently mixing.
    """

    network = models.CharField(max_length=32)
    genesis_hash = models.CharField(max_length=64)
    program_id = models.CharField(max_length=64)
    bound_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.network} ({self.genesis_hash[:8]}…)"
