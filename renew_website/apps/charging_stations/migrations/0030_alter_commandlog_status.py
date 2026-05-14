from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('charging_stations', '0029_commandlog'),
    ]

    operations = [
        migrations.AlterField(
            model_name='commandlog',
            name='status',
            field=models.CharField(choices=[('pending', 'Pending'), ('sent', 'Sent'), ('success', 'Success'), ('failed', 'Failed')], default='pending', max_length=20),
        ),
    ]