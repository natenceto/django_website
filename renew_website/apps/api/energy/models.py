"""
Energy management models for EV charging optimization.
"""
from django.db import models
from django.utils import timezone
import json


class Inverter(models.Model):
    """Solar inverter device information."""
    device_sn = models.CharField(max_length=50, unique=True)
    device_id = models.IntegerField()
    device_type = models.CharField(max_length=50)
    product_id = models.CharField(max_length=50)
    # station_id = models.IntegerField()
    station = models.ForeignKey(
        'charging_stations.Station', 
        on_delete=models.CASCADE, 
        related_name='inverters',
        null=True, blank=True
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Inverter {self.device_sn}"


class InverterReading(models.Model):
    """Real-time inverter data readings."""
    inverter = models.ForeignKey(Inverter, on_delete=models.CASCADE, related_name='readings')
    timestamp = models.DateTimeField(default=timezone.now)
    
    # Power metrics
    generation_power = models.FloatField(null=True, help_text="Current power generation in watts")
    battery_soc = models.FloatField(null=True, help_text="Battery state of charge percentage")
    grid_power = models.FloatField(null=True, help_text="Grid power flow in watts")
    
    # Station-level data
    station_data = models.JSONField(default=dict, help_text="Raw station data from API")
    connect_status = models.IntegerField(default=1, help_text="Device connection status")
    collection_time = models.DateTimeField(null=True, help_text="Last data collection time")
    
    class Meta:
        indexes = [
            models.Index(fields=['inverter', 'timestamp']),
            models.Index(fields=['timestamp']),
        ]
        ordering = ['-timestamp']

    def __str__(self):
        return f"{self.inverter.device_sn} at {self.timestamp}"






class GridPricing(models.Model):
    """Electricity grid pricing data."""
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()
    price_per_kwh = models.FloatField(help_text="Price in local currency per kWh")
    is_peak = models.BooleanField(default=False)
    
    class Meta:
        ordering = ['start_time']

    def __str__(self):
        return f"Grid pricing {self.price_per_kwh}/kWh"


class WorkMode(models.Model):
    """Energy management work modes configuration."""
    
    WORK_MODE_CHOICES = [
        ('selling_first', 'Selling First'),
        ('zero_export_load', 'Zero Export to Load'),
        ('zero_export_ct', 'Zero Export to CT'),
    ]
    
    CONTROL_MODE_CHOICES = [
        ('automatic', 'Automatic'),
        ('manual', 'Manual'),
    ]
    
    mode = models.CharField(
        max_length=20, 
        choices=WORK_MODE_CHOICES,
        help_text="Current work mode"
    )
    control_mode = models.CharField(
        max_length=10,
        choices=CONTROL_MODE_CHOICES,
        default='manual',
        help_text="Control mode (automatic or manual)"
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Whether this work mode configuration is active"
    )
    algorithm_selected_mode = models.CharField(
        max_length=20,
        choices=WORK_MODE_CHOICES,
        blank=True,
        null=True,
        help_text="Mode selected by algorithm when in automatic mode"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-updated_at']
    
    def __str__(self):
        return f"{self.get_mode_display()} ({self.get_control_mode_display()})"
    
    @classmethod
    def get_current_config(cls):
        """Get the current active work mode configuration."""
        try:
            return cls.objects.filter(is_active=True).latest('updated_at')
        except cls.DoesNotExist:
            # Create default configuration if none exists
            return cls.objects.create(
                mode='selling_first',
                control_mode='manual',
                is_active=True
            )


class EnergyRecommendation(models.Model):
    """Algorithm recommendations for energy management."""
    
    RECOMMENDATION_STATUS = [
        ('pending', 'Pending'),
        ('applied', 'Applied'),
        ('ignored', 'Ignored'),
        ('expired', 'Expired'),
    ]
    
    # Algorithm decision data
    mode = models.CharField(max_length=50, help_text="Recommended mode by algorithm")
    ev_power_limit_kw = models.FloatField(help_text="Total power limit for EV charging")
    power_per_station_kw = models.FloatField(help_text="Power per station")
    
    # System state snapshot
    battery_soc = models.FloatField(help_text="Battery SOC at time of recommendation")
    pv_production_kw = models.FloatField(help_text="PV production at time of recommendation")
    building_load_kw = models.FloatField(help_text="Building load at time of recommendation")
    active_ev_sessions = models.IntegerField(help_text="Number of active EV sessions")
    
    # Status and tracking
    status = models.CharField(
        max_length=10,
        choices=RECOMMENDATION_STATUS,
        default='pending'
    )
    applied_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(help_text="When this recommendation expires")
    
    # Additional data
    algorithm_data = models.JSONField(default=dict, help_text="Additional algorithm data")
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', 'created_at']),
            models.Index(fields=['expires_at']),
        ]
    
    def __str__(self):
        return f"Recommendation: {self.mode} - {self.status}"
    
    def apply_recommendation(self):
        """Apply this recommendation to all active stations."""
        if self.status != 'pending':
            return False, "Recommendation already processed"
        
        try:
            from renew_website.apps.charging_stations.tasks import set_charging_power_limit
            from renew_website.apps.charging_stations.models import Station, Transaction
            
            # Get active stations
            active_transactions = Transaction.objects.filter(
                stopped_at__isnull=True
            )
            active_stations = Station.objects.filter(
                id__in=active_transactions.values_list('connector__station_id', flat=True)
            )
            
            # Apply power limit to each station
            power_per_station_w = int(self.power_per_station_kw * 1000)
            
            for station in active_stations:
                set_charging_power_limit.delay(station.id, power_per_station_w)
            
            # Update status
            self.status = 'applied'
            self.applied_at = timezone.now()
            self.save()
            
            return True, f"Applied to {len(active_stations)} stations"
            
        except Exception as e:
            return False, str(e)
    
    @classmethod
    def get_latest_pending(cls):
        """Get the latest pending recommendation."""
        return cls.objects.filter(status='pending').order_by('-created_at').first()
    
    @classmethod
    def expire_old_recommendations(cls):
        """Mark old recommendations as expired."""
        cutoff_time = timezone.now()
        cls.objects.filter(
            status='pending',
            expires_at__lt=cutoff_time
        ).update(status='expired')