from django import forms


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
