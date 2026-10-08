import secrets

from django.conf import settings
from django.db import models


def new_patient_token() -> str:
    """The secret in the patient's link to their copy: random, unguessable."""
    return secrets.token_urlsafe(18)


class Patient(models.Model):
    """A real person, and the random id that ties their documents together.

    Nothing about the patient goes on-chain, not even this id.
    """

    # National id, passport... whatever the country uses. Unique per patient.
    document_number = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=200)
    # Hex of a random 32-byte id. Never derived from the above.
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
    # Opens the patient's copy (/p/<token>/) without an account: whoever holds
    # the link reads the document, like whoever holds a paper prescription.
    patient_token = models.CharField(max_length=32, unique=True, default=new_patient_token)
    # The prescriber's private note when cancelling or stopping it: may hold
    # health data, so it stays here. The act itself (and its reason) is on-chain.
    closure_note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.prescription_id


class Manufacturer(models.Model):
    """A pharmaceutical manufacturer (laboratory): who makes a product."""

    name = models.CharField(max_length=200, unique=True)
    country = models.CharField(max_length=64, blank=True)

    def __str__(self):
        return self.name


class CatalogMedication(models.Model):
    """A medication in the public catalog, behind an on-chain Medication.

    Active ingredient, strength and form define it: their hash is on-chain
    (rxtrail.catalog.identity_hash) and they never change. Everything else is
    guidance. Whether it is withdrawn lives on-chain only.
    """

    medication_id = models.CharField(max_length=64, unique=True)
    address = models.CharField(max_length=64, unique=True)
    identity_hash = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=200)
    active_ingredient = models.CharField(max_length=200)
    strength = models.CharField(max_length=64)
    form = models.CharField(max_length=64)
    atc_code = models.CharField(max_length=7, blank=True, db_index=True)
    unit = models.CharField(max_length=32, default="unit")
    regulatory_list = models.CharField(max_length=16, blank=True)
    dosage_guidance = models.TextField(blank=True)
    usual_max_daily_units = models.PositiveIntegerField(null=True, blank=True)
    max_quantity = models.PositiveIntegerField(null=True, blank=True)
    max_validity_days = models.PositiveIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class CatalogProduct(models.Model):
    """One manufacturer's version of a catalog medication, behind an on-chain Product."""

    class Kind(models.TextChoices):
        REFERENCE = "reference", "Reference"
        GENERIC = "generic", "Generic"
        SIMILAR = "similar", "Similar"

    product_id = models.CharField(max_length=64, unique=True)
    address = models.CharField(max_length=64, unique=True)
    identity_hash = models.CharField(max_length=64, unique=True)
    medication = models.ForeignKey(
        CatalogMedication, on_delete=models.PROTECT, related_name="products"
    )
    manufacturer = models.ForeignKey(
        Manufacturer, on_delete=models.PROTECT, related_name="products"
    )
    brand_name = models.CharField(max_length=200)
    kind = models.CharField(max_length=16, choices=Kind.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["brand_name"]

    def __str__(self):
        return f"{self.brand_name} ({self.manufacturer})"


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
        CATALOG_AUTHORITY = "catalog_authority", "Catalog authority"
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
