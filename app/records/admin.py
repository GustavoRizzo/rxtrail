from django.contrib import admin

from records.models import CatalogMedication, CatalogProduct, Patient, PrescriptionRecord


@admin.register(Patient)
class PatientAdmin(admin.ModelAdmin):
    list_display = ["name", "document_number", "patient_id", "created_at"]
    search_fields = ["name", "document_number"]


@admin.register(PrescriptionRecord)
class PrescriptionRecordAdmin(admin.ModelAdmin):
    list_display = ["prescription_id", "patient", "created_at"]


@admin.register(CatalogMedication)
class CatalogMedicationAdmin(admin.ModelAdmin):
    list_display = ["name", "active_ingredient", "atc_code", "regulatory_list"]
    search_fields = ["name", "active_ingredient", "atc_code"]


@admin.register(CatalogProduct)
class CatalogProductAdmin(admin.ModelAdmin):
    list_display = ["brand_name", "manufacturer", "medication", "kind"]
