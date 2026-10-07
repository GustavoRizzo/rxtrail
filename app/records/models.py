from django.conf import settings
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
    # Key name of the prescriber who issued it (who may see the document).
    prescriber = models.CharField(max_length=63, db_index=True, default="")
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


class Participant(models.Model):
    """A login bound to a role and to the keypair that signs for it.

    Demo mode: keys are held server-side, so signing in is enough to act. In
    production each participant would sign with a wallet on their own device;
    the program would not notice the difference.
    """

    class Role(models.TextChoices):
        PRESCRIBER = "prescriber", "Prescriber"
        DISPENSER = "dispenser", "Dispenser"
        PROFESSIONAL_AUTHORITY = "professional_authority", "Professional authority"
        HEALTH_AUTHORITY = "health_authority", "Health authority"
        AUDITOR = "auditor", "Auditor"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="participant"
    )
    role = models.CharField(max_length=32, choices=Role.choices)
    # Name of the keypair in the key store; empty for roles that never sign (auditor).
    key_name = models.CharField(max_length=63, blank=True)
    display_name = models.CharField(max_length=200)
    # Professional licence or registration number, as the country issues it.
    license_number = models.CharField(max_length=64, blank=True)

    def __str__(self):
        return f"{self.display_name} ({self.get_role_display()})"


class Activity(models.Model):
    """What each participant did through the app, with its transaction."""

    actor = models.ForeignKey(Participant, on_delete=models.CASCADE, related_name="activities")
    action = models.CharField(max_length=32)
    summary = models.CharField(max_length=300)
    prescription_id = models.CharField(max_length=64, blank=True, db_index=True)
    signature = models.CharField(max_length=128, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.summary
