from django.db import migrations, models
import django.db.models.deletion


def ensure_commandlog_table(apps, schema_editor):
    CommandLog = apps.get_model('charging_stations', 'CommandLog')
    existing_tables = set(schema_editor.connection.introspection.table_names())
    if CommandLog._meta.db_table in existing_tables:
        return
    schema_editor.create_model(CommandLog)


class Migration(migrations.Migration):

    dependencies = [
        ('charging_stations', '0028_metervalue_energy_wh_metervalue_power_w_and_more'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunPython(ensure_commandlog_table, migrations.RunPython.noop),
            ],
            state_operations=[
                migrations.CreateModel(
                    name='CommandLog',
                    fields=[
                        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                        ('command_id', models.CharField(max_length=64, unique=True)),
                        ('command_type', models.CharField(choices=[('start', 'Start'), ('stop', 'Stop'), ('reset', 'Reset'), ('update', 'Update')], max_length=20)),
                        ('status', models.CharField(choices=[('pending', 'Pending'), ('sent', 'Sent'), ('success', 'Success'), ('failed', 'Failed')], default='pending', max_length=20)),
                        ('payload', models.JSONField(blank=True, default=dict)),
                        ('detail', models.TextField(blank=True, null=True)),
                        ('error_message', models.TextField(blank=True, null=True)),
                        ('created_at', models.DateTimeField(auto_now_add=True)),
                        ('executed_at', models.DateTimeField(blank=True, null=True)),
                        ('station', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='command_logs', to='charging_stations.station')),
                    ],
                    options={
                        'ordering': ['-created_at'],
                    },
                ),
            ],
        ),
    ]