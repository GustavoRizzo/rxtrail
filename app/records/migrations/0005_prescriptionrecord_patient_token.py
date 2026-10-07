"""Give every prescription a patient token; existing ones get a fresh one each."""

from django.db import migrations, models

import records.models


def fill_tokens(apps, schema_editor):
    PrescriptionRecord = apps.get_model("records", "PrescriptionRecord")
    for record in PrescriptionRecord.objects.all():
        record.patient_token = records.models.new_patient_token()
        record.save(update_fields=["patient_token"])


class Migration(migrations.Migration):
    dependencies = [("records", "0004_catalog")]

    operations = [
        migrations.AddField(
            model_name="prescriptionrecord",
            name="patient_token",
            field=models.CharField(max_length=32, null=True),
        ),
        migrations.RunPython(fill_tokens, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="prescriptionrecord",
            name="patient_token",
            field=models.CharField(
                default=records.models.new_patient_token, max_length=32, unique=True
            ),
        ),
    ]
