from django import forms

from rxtrail.domain import Standing


class IssueForm(forms.Form):
    patient_name = forms.CharField(max_length=200)
    patient_document = forms.CharField(max_length=64, label="Patient ID document")
    medication = forms.CharField(max_length=200)
    dosage = forms.CharField(max_length=200)
    instructions = forms.CharField(max_length=500, required=False)
    quantity = forms.IntegerField(min_value=1, max_value=10_000)
    valid_days = forms.IntegerField(min_value=1, max_value=365, initial=30)


class DispenseForm(forms.Form):
    prescription_id = forms.CharField(max_length=64, min_length=64)
    quantity = forms.IntegerField(min_value=1)


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
