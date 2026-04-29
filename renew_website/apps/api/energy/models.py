"""
Energy management models for EV charging optimization.
"""
from django.db import models, transaction
from django.utils import timezone
from django.db.models import Q
from datetime import timedelta


# ------------------------
# Inverter
# ------------------------
class Inverter(models.Model):
    """Solar inverter device information."""
    device_sn = models.CharField(max_length=50, unique=True)
    device_id = models.IntegerField(unique=True)
    device_type = models.CharField(max_length=50)
    product_id = models.CharField(max_length=50)

    station = models.ForeignKey(
        'charging_stations.Station',
        on_delete=models.CASCADE,
        related_name='inverters',
        null=True,
        blank=True
    )

    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['device_id']),
            models.Index(fields=['device_sn']),
        ]

    def __str__(self):
        return f"Inverter {self.device_sn}"


# ------------------------
# Inverter Reading
# ------------------------
class InverterReading(models.Model):
    """Real-time inverter data readings."""
    inverter = models.ForeignKey(
        Inverter,
        on_delete=models.CASCADE,
        related_name='readings'
    )
    timestamp = models.DateTimeField(default=timezone.now)

    # Power metrics
    generation_power = models.FloatField(null=True)
    battery_soc = models.FloatField(null=True)
    grid_power = models.FloatField(null=True)

    # Raw / external data
    station_data = models.JSONField(default=dict)
    connect_status = models.IntegerField(default=1)
    collection_time = models.DateTimeField(null=True)

    class Meta:
        indexes = [
            models.Index(fields=['inverter', 'timestamp']),
            models.Index(fields=['timestamp']),
        ]
        ordering = ['-timestamp']

    def __str__(self):
        return f"{self.inverter_id} at {self.timestamp}"


# ------------------------
# Grid Pricing
# ------------------------
class GridPricing(models.Model):
    """Electricity grid pricing data."""
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()

    price_per_kwh = models.DecimalField(
        max_digits=10,
        decimal_places=4,
        help_text="Price in local currency per kWh"
    )

    is_peak = models.BooleanField(default=False)

    class Meta:
        ordering = ['start_time']
        indexes = [
            models.Index(fields=['start_time', 'end_time']),
        ]

    def __str__(self):
        return f"{self.price_per_kwh}/kWh"


# ------------------------
# Work Mode
# ------------------------
class WorkMode(models.Model):
    """Energy management work modes configuration."""

    class WorkModeChoices(models.TextChoices):
        SELLING_FIRST = 'selling_first', 'Selling First'
        ZERO_EXPORT_LOAD = 'zero_export_load', 'Zero Export to Load'
        ZERO_EXPORT_CT = 'zero_export_ct', 'Zero Export to CT'

    class ControlModeChoices(models.TextChoices):
        AUTOMATIC = 'automatic', 'Automatic'
        MANUAL = 'manual', 'Manual'

    mode = models.CharField(
        max_length=20,
        choices=WorkModeChoices.choices
    )

    control_mode = models.CharField(
        max_length=10,
        choices=ControlModeChoices.choices,
        default=ControlModeChoices.MANUAL
    )

    is_active = models.BooleanField(default=True)

    algorithm_selected_mode = models.CharField(
        max_length=20,
        choices=WorkModeChoices.choices,
        null=True,
        blank=True
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']
        constraints = [
            models.UniqueConstraint(
                fields=['id'],
                condition=Q(is_active=True),
                name='only_one_active_workmode'
            )
        ]

    def __str__(self):
        return f"{self.get_mode_display()} ({self.get_control_mode_display()})"

    @classmethod
    def get_current_config(cls):
        obj = cls.objects.filter(is_active=True).order_by('-updated_at').first()
        if obj:
            return obj

        return cls.objects.create(
            mode=cls.WorkModeChoices.SELLING_FIRST,
            control_mode=cls.ControlModeChoices.MANUAL,
            is_active=True
        )


# ------------------------
# Energy Recommendation
# ------------------------
class EnergyRecommendation(models.Model):
    """Algorithm recommendations for energy management."""

    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        APPLIED = 'applied', 'Applied'
        IGNORED = 'ignored', 'Ignored'
        EXPIRED = 'expired', 'Expired'

    # Decision
    mode = models.CharField(max_length=50)
    ev_power_limit_kw = models.FloatField()
    power_per_station_kw = models.FloatField()

    # Snapshot
    battery_soc = models.FloatField()
    pv_production_kw = models.FloatField()
    building_load_kw = models.FloatField()
    active_ev_sessions = models.IntegerField()

    # Status
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.PENDING
    )

    applied_at = models.DateTimeField(null=True, blank=True)

    expires_at = models.DateTimeField(
        default=lambda: timezone.now() + timedelta(minutes=5)
    )

    # Extra
    algorithm_data = models.JSONField(default=dict)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', 'created_at']),
            models.Index(fields=['expires_at']),
        ]

    def __str__(self):
        return f"{self.mode} ({self.status})"

    def apply_recommendation(self):
        if self.status != self.Status.PENDING:
            return False, "Already processed"

        try:
            from renew_website.apps.charging_stations.tasks import set_charging_power_limit
            from renew_website.apps.charging_stations.models import Station, Transaction

            with transaction.atomic():
                active_transactions = Transaction.objects.filter(
                    stopped_at__isnull=True
                )

                station_ids = active_transactions.values_list(
                    'connector__station_id',
                    flat=True
                )

                active_stations = Station.objects.filter(
                    id__in=station_ids
                ).distinct()

                power_watts = int(self.power_per_station_kw * 1000)

                for station in active_stations:
                    set_charging_power_limit.delay(station.id, power_watts)

                self.status = self.Status.APPLIED
                self.applied_at = timezone.now()
                self.save(update_fields=['status', 'applied_at'])

                return True, f"Applied to {active_stations.count()} stations"

        except Exception as e:
            return False, str(e)

    @classmethod
    def get_latest_pending(cls):
        return cls.objects.filter(
            status=cls.Status.PENDING
        ).order_by('-created_at').first()

    @classmethod
    def expire_old_recommendations(cls):
        now = timezone.now()
        return cls.objects.filter(
            status=cls.Status.PENDING,
            expires_at__lt=now
        ).update(status=cls.Status.EXPIRED)