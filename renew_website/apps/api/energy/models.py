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
    station_id = models.IntegerField()
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


<<<<<<< Updated upstream
class WeatherForecast(models.Model):
    """Weather data for solar generation prediction."""
    timestamp = models.DateTimeField()
    cloud_cover = models.FloatField(null=True, help_text="Cloud coverage percentage")
    solar_irradiance = models.FloatField(null=True, help_text="Solar irradiance in W/m²")
    temperature = models.FloatField(null=True, help_text="Temperature in Celsius")
    
    class Meta:
        ordering = ['-timestamp']

    def __str__(self):
        return f"Weather at {self.timestamp}"
=======
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
>>>>>>> Stashed changes
