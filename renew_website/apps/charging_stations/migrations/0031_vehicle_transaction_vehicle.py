from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


def backfill_vehicles(apps, schema_editor):
    Transaction = apps.get_model("charging_stations", "Transaction")
    Vehicle = apps.get_model("charging_stations", "Vehicle")
    db_alias = schema_editor.connection.alias

    transaction_rows = (
        Transaction.objects.using(db_alias)
        .exclude(id_tag__isnull=True)
        .exclude(id_tag="")
        .order_by("id_tag", "started_at", "id")
    )

    seen_identifiers = {}
    for tx in transaction_rows.iterator():
        identifier = (tx.id_tag or "").strip()[:64]
        if not identifier:
            continue

        vehicle = seen_identifiers.get(identifier)
        if vehicle is None:
            vehicle, _ = Vehicle.objects.using(db_alias).get_or_create(
                vehicle_identifier=identifier,
                defaults={
                    "first_seen_at": tx.started_at or django.utils.timezone.now(),
                    "last_seen_at": tx.stopped_at or tx.started_at or django.utils.timezone.now(),
                },
            )
            seen_identifiers[identifier] = vehicle

        update_fields = []
        first_seen_at = tx.started_at or vehicle.first_seen_at
        last_seen_at = tx.stopped_at or tx.started_at or vehicle.last_seen_at
        if first_seen_at and (vehicle.first_seen_at is None or first_seen_at < vehicle.first_seen_at):
            vehicle.first_seen_at = first_seen_at
            update_fields.append("first_seen_at")
        if last_seen_at and (vehicle.last_seen_at is None or last_seen_at > vehicle.last_seen_at):
            vehicle.last_seen_at = last_seen_at
            update_fields.append("last_seen_at")
        if update_fields:
            vehicle.save(update_fields=update_fields)

        if tx.vehicle_id != vehicle.id:
            tx.vehicle_id = vehicle.id
            tx.save(update_fields=["vehicle"])


class Migration(migrations.Migration):

    dependencies = [
        ("charging_stations", "0030_alter_commandlog_status"),
    ]

    operations = [
        migrations.CreateModel(
            name="Vehicle",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("vehicle_identifier", models.CharField(db_index=True, help_text="Primary vehicle identifier known to the platform. Defaults to the station-provided idTag when no richer identity is available.", max_length=64, unique=True)),
                ("vin", models.CharField(blank=True, help_text="Vehicle Identification Number when provided by the station or an upstream integration.", max_length=64, null=True, unique=True)),
                ("registration_number", models.CharField(blank=True, db_index=True, help_text="Registration or license plate when known.", max_length=32, null=True)),
                ("manufacturer", models.CharField(blank=True, max_length=100, null=True)),
                ("model_name", models.CharField(blank=True, max_length=100, null=True)),
                ("battery_capacity_kwh", models.DecimalField(blank=True, decimal_places=2, max_digits=7, null=True)),
                ("metadata", models.JSONField(blank=True, default=dict, help_text="Additional vehicle metadata received from the station.")),
                ("first_seen_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("last_seen_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "ordering": ["vehicle_identifier"],
            },
        ),
        migrations.AddField(
            model_name="transaction",
            name="vehicle",
            field=models.ForeignKey(blank=True, help_text="Vehicle associated with this charging session.", null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="transactions", to="charging_stations.vehicle"),
        ),
        migrations.RunPython(backfill_vehicles, migrations.RunPython.noop),
    ]