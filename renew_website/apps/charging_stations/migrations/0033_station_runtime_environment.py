from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("charging_stations", "0032_vehicle_profile_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="station",
            name="runtime_environment",
            field=models.CharField(
                choices=[
                    ("unknown", "Unknown / Unverified"),
                    ("physical", "Physical Hardware"),
                    ("simulated", "Simulator / Test Bench"),
                ],
                default="unknown",
                help_text="Operational provenance used for reporting authenticity classification.",
                max_length=20,
            ),
        ),
    ]