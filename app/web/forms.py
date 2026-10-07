from django import forms
from django.core.validators import RegexValidator

from records.models import CatalogProduct
from rxtrail.domain import Standing

HEX_ID = RegexValidator(r"^[0-9a-f]{64}$", "Not a catalog id.")


def _hex_id(**kwargs) -> forms.CharField:
    return forms.CharField(max_length=64, validators=[HEX_ID], **kwargs)


class IssueForm(forms.Form):
    patient_name = forms.CharField(max_length=200)
    patient_document = forms.CharField(max_length=64, label="Patient ID document")
    medication_id = _hex_id(error_messages={"required": "Choose a medication from the catalog."})
    locked_product_id = _hex_id(required=False)
    dosage = forms.CharField(max_length=200)
    instructions = forms.CharField(max_length=500, required=False)
    quantity = forms.IntegerField(min_value=1, max_value=10_000)
    valid_days = forms.IntegerField(min_value=1, max_value=365, initial=30)


class DispenseForm(forms.Form):
    prescription_id = forms.CharField(max_length=64, min_length=64)
    product_id = _hex_id(error_messages={"required": "Choose the product handed out."})
    quantity = forms.IntegerField(min_value=1)


class MedicationForm(forms.Form):
    name = forms.CharField(max_length=200, help_text="e.g. Clonazepam 2 mg tablet")
    active_ingredient = forms.CharField(max_length=200)
    strength = forms.CharField(max_length=64)
    form = forms.CharField(max_length=64, label="Pharmaceutical form")
    atc_code = forms.CharField(max_length=7, required=False, label="ATC code")
    unit = forms.CharField(max_length=32, initial="tablet")
    regulatory_list = forms.CharField(max_length=16, required=False)
    dosage_guidance = forms.CharField(max_length=500, required=False)
    usual_max_daily_units = forms.IntegerField(min_value=1, required=False)
    max_quantity = forms.IntegerField(min_value=1, required=False)
    max_validity_days = forms.IntegerField(min_value=1, required=False)


class ProductForm(forms.Form):
    medication_id = _hex_id()
    manufacturer = forms.CharField(max_length=200)
    brand_name = forms.CharField(max_length=200)
    kind = forms.ChoiceField(choices=CatalogProduct.Kind.choices)


class EnableParticipantForm(forms.Form):
    display_name = forms.CharField(max_length=200)
    username = forms.SlugField(max_length=63, help_text="Also the name of their key.")
    license_number = forms.CharField(max_length=64, required=False)
    password = forms.CharField(min_length=8, widget=forms.PasswordInput)


class PrescriptionFilterForm(forms.Form):
    """Search and sort a prescriber's list. Every field is optional."""

    SORTS = {
        "newest": "Newest first",
        "oldest": "Oldest first",
        "expiring": "Expiring soonest",
        "remaining": "Most units left",
        "patient": "Patient, A to Z",
        "medication": "Medication, A to Z",
    }

    q = forms.CharField(max_length=200, required=False, label="Patient or medication")
    standing = forms.ChoiceField(
        choices=[("", "Any status"), *((s.value, s.value.title()) for s in Standing)],
        required=False,
        label="Status",
    )
    issued_from = forms.DateField(required=False, label="Issued from")
    issued_to = forms.DateField(required=False, label="Issued to")
    sort = forms.ChoiceField(choices=list(SORTS.items()), required=False)

    def active_count(self) -> int:
        """How many filters narrow the list (sorting does not count)."""
        if not self.is_valid():
            return 0
        return sum(
            1 for name in ("q", "standing", "issued_from", "issued_to") if self.cleaned_data[name]
        )
