from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("charging_stations", "0031_vehicle_transaction_vehicle"),
    ]

    operations = [
        migrations.AddField(
            model_name="vehicle",
            name="color",
            field=models.CharField(blank=True, max_length=50, null=True),
        ),
        migrations.AddField(
            model_name="vehicle",
            name="last_known_soc_percent",
            field=models.FloatField(blank=True, help_text="Latest known vehicle State of Charge (%) received during charging.", null=True),
        ),
        migrations.AddField(
            model_name="vehicle",
            name="model_year",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="vehicle",
            name="trim",
            field=models.CharField(blank=True, max_length=100, null=True),
        ),
    ]