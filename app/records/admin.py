from django.contrib import admin

from records.models import Patient, PrescriptionRecord


@admin.register(Patient)
class PatientAdmin(admin.ModelAdmin):
    list_display = ["name", "document_number", "patient_id", "created_at"]
    search_fields = ["name", "document_number"]


@admin.register(PrescriptionRecord)
class PrescriptionRecordAdmin(admin.ModelAdmin):
    list_display = ["prescription_id", "patient", "created_at"]
