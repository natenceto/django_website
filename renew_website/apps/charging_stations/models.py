from decimal import Decimal
from django.db import models
from django.utils import timezone

class Station(models.Model):
    # Location
    address = models.CharField(max_length=255)
    latitude = models.DecimalField(max_digits=18, decimal_places=14)
    longitude = models.DecimalField(max_digits=18, decimal_places=14)

    # Charger Info
    model = models.CharField(max_length=50, blank=True, null=True, help_text='Model identifier for the charging station (e.g., TACW22-G0135)')
    connector_type = models.CharField(max_length=50)
    power_output = models.IntegerField()

    # Timestamps
    last_seen = models.DateTimeField(null=True, blank=True, help_text="When this station was last online")

    # Operations
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('inactive', 'Inactive'),
        ('maintenance', 'Under Maintenance'),
    ]
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='inactive')

    # operations
    ocpp_identity = models.CharField(max_length=255, blank=True, null=True, help_text="OCPP Identity (ChargeBox Identity)")
    RUNTIME_ENVIRONMENT_CHOICES = [
        ('unknown', 'Unknown / Unverified'),
        ('physical', 'Physical Hardware'),
        ('simulated', 'Simulator / Test Bench'),
    ]
    runtime_environment = models.CharField(
        max_length=20,
        choices=RUNTIME_ENVIRONMENT_CHOICES,
        default='unknown',
        help_text='Operational provenance used for reporting authenticity classification.',
    )

    # Owner Info
    email = models.EmailField()

    class Meta:
        ordering = ['id']  # Oldest first, newest last

    def __str__(self):
        return f"{self.formatted_serial()} - {self.short_address()}"
        
    def formatted_serial(self):
        """Return a formatted version of the serial number from the first connector's vendor_connector_id"""
        if not hasattr(self, '_formatted_serial'):
            model_name = self.model or "Unknown Model"
            first_connector = self.connectors.first()
            if first_connector and first_connector.vendor_connector_id:
                # If vendor_connector_id is in format "TACW2245324G0135" -> format as "TACW22-G0135"
                serial = first_connector.vendor_connector_id
                if len(serial) >= 11:  # Ensure it's long enough to split
                    prefix = serial[:6]  # First 6 chars
                    suffix = serial[-5:]  # Last 5 chars
                    self._formatted_serial = f"{model_name} ({prefix}-{suffix})"
                else:
                    self._formatted_serial = f"{model_name} ({serial})"
            else:
                self._formatted_serial = f"{model_name} - Station {self.id}"
        return self._formatted_serial
    
    def short_address(self):
        """Return a shortened version of the address for display"""
        if not self.address:
            return "No address"
        return (self.address[:30] + "...") if len(self.address) > 30 else self.address

    def get_main_connector(self):
        """Get the primary connector for this station"""
        return self.connectors.filter(is_primary=True).first() or self.connectors.first()

    def get_connector_count(self):
        """Get the number of connectors for this station"""
        return self.connectors.count()

    @property
    def is_online(self):
        """Check if station is currently online based on status and last_seen."""
        from django.utils import timezone
        if self.status != 'active':
            return False
        if self.last_seen:
            # Consider online if seen in the last 5 minutes
            return (timezone.now() - self.last_seen).total_seconds() < 300
        return False

    @property
    def serial_number(self):
        """Get serial number from primary connector"""
        connector = self.get_main_connector()
        return connector.vendor_connector_id if connector else None
    def status_badge(self):
        """Return HTML for status badge"""
        if not self.last_seen:
            return "Unknown"
        
        from django.utils.timezone import now
        from django.utils.html import format_html
        
        time_diff = (now() - self.last_seen).total_seconds()
        
        if time_diff < 300:  # 5 minutes
            return format_html('<span style="color: green;">Online</span>')
        elif time_diff < 86400:  # 24 hours
            return format_html('<span style="color: orange;">Idle</span>')
        else:
            return format_html('<span style="color: red;">Offline</span>')
            
    def delete(self, *args, **kwargs):
        """Override delete to reset the sequence after deletion"""
        # Call the original delete method
        result = super().delete(*args, **kwargs)
        
        # Reset the sequence for PostgreSQL
        from django.db import connection
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT setval(
                    pg_get_serial_sequence('"charging_stations_station"','id'),
                    COALESCE((SELECT MAX(id) FROM "charging_stations_station"), 1),
                    false
                );
            """)
        return result
    

class Connector(models.Model):
    station = models.ForeignKey(Station, on_delete=models.CASCADE, related_name="connectors")
    connector_id = models.IntegerField(
        help_text="Physical connector number at this station as defined by the charge point (OCPP connectorId)."
    )
    
    # Human-readable connector number (1-based for display)
    connector_number = models.IntegerField(
        default=1,
        help_text="Human-readable connector number (1-based: 1, 2, 3...)"
    )

    # Primary connector flag (for single-connector stations)
    is_primary = models.BooleanField(
        default=False,
        help_text="This is the primary connector for the station"
    )
    vendor_connector_id = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        help_text="Vendor's alphanumeric identifier for this connector. For single-connector stations, this is typically the station's serial number from the WebSocket URL."
    )
    last_updated = models.DateTimeField(auto_now=True, help_text="When this connector's status was last updated")
    STATUS_CHOICES = [
        ('available', 'Available'),
        ('preparing', 'Preparing'),
        ('charging', 'Charging'),
        ('suspendedEV', 'SuspendedEV'),
        ('suspendedEVSE', 'SuspendedEVSE'),
        ('finishing', 'Finishing'),
        ('reserved', 'Reserved'),
        ('faulted', 'Faulted'),
        ('offline', 'Offline'),
    ]
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="available")
    
    # OCPP Availability Status (Operative/Inoperative)
    AVAILABILITY_CHOICES = [
        ('operative', 'Operative'),  # Can charge
        ('inoperative', 'Inoperative'),  # Cannot charge (maintenance/disabled)
    ]
    availability = models.CharField(max_length=20, choices=AVAILABILITY_CHOICES, default="operative")
    # Power/electrical
    max_power_kw = models.DecimalField(max_digits=6, decimal_places=2, default=Decimal("22.0"), help_text="Maximum power this connector can deliver (kW)")
    max_current_a = models.DecimalField(max_digits=6, decimal_places=2, default=Decimal("32.0"), help_text="Maximum current this connector can draw (A)")
    voltage_v = models.IntegerField(default=230, help_text="Voltage this connector operates at (V)")

    # Phase configuration
    PHASE_CHOICES = [
        ('1', 'Single Phase'),
        ('3', 'Three Phase'),
    ]
    phases = models.CharField(max_length=1, choices=PHASE_CHOICES, default='1')

    # Connector type (physical plug type)
    CONNECTOR_TYPE_CHOICES = [
        ("type2", "Type 2"),
        ("ccs", "CCS"),
        ("chademo", "CHAdeMO"),
        ("type1", "Type 1"),
        ("tesla", "Tesla"),
        ("schuko", "Schuko"),
    ]
    connector_type = models.CharField(
        max_length=20,
        choices=CONNECTOR_TYPE_CHOICES,
        default="type2",
        help_text="Physical connector type"
    )

    # Smart charging
    supports_smart_charging = models.BooleanField(default=True, help_text="Connector supports smart charging/load balancing")
    current_power_kw = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    energy_delivered_kwh = models.DecimalField(max_digits=10, decimal_places=4, default=Decimal("0.0"))
    class Meta:
        unique_together = ['station', 'connector_id']
        ordering = ['station', 'connector_id']

    def __str__(self):
        return f"Connector {self.connector_id} at {self.station.address}"


class Vehicle(models.Model):
    """Vehicle identity and core capabilities known to the platform."""

    vehicle_identifier = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
        help_text="Primary vehicle identifier known to the platform. Defaults to the station-provided idTag when no richer identity is available.",
    )
    vin = models.CharField(
        max_length=64,
        unique=True,
        null=True,
        blank=True,
        help_text="Vehicle Identification Number when provided by the station or an upstream integration.",
    )
    registration_number = models.CharField(
        max_length=32,
        null=True,
        blank=True,
        db_index=True,
        help_text="Registration or license plate when known.",
    )
    manufacturer = models.CharField(max_length=100, null=True, blank=True)
    model_name = models.CharField(max_length=100, null=True, blank=True)
    model_year = models.PositiveIntegerField(null=True, blank=True)
    trim = models.CharField(max_length=100, null=True, blank=True)
    color = models.CharField(max_length=50, null=True, blank=True)
    battery_capacity_kwh = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)
    last_known_soc_percent = models.FloatField(
        null=True,
        blank=True,
        help_text="Latest known vehicle State of Charge (%) received during charging.",
    )
    metadata = models.JSONField(default=dict, blank=True, help_text="Additional vehicle metadata received from the station.")
    first_seen_at = models.DateTimeField(default=timezone.now)
    last_seen_at = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["vehicle_identifier"]

    def __str__(self):
        if self.registration_number:
            return self.registration_number
        if self.vin:
            return self.vin
        return self.vehicle_identifier


class Transaction(models.Model):
    """OCPP charging transaction - core charging session data."""
    connector = models.ForeignKey(Connector, on_delete=models.CASCADE, related_name="transactions")
    vehicle = models.ForeignKey(
        Vehicle,
        on_delete=models.SET_NULL,
        related_name="transactions",
        null=True,
        blank=True,
        help_text="Vehicle associated with this charging session.",
    )
    
    # OCPP Core Fields
    id_tag = models.CharField(max_length=50, help_text="RFID tag used for this transaction")
    transaction_id = models.CharField(max_length=36, unique=True, null=True, blank=True, 
                                    help_text="OCPP transaction UUID")
    started_at = models.DateTimeField(auto_now_add=True)
    stopped_at = models.DateTimeField(null=True, blank=True)
    
    # Meter Values (OCPP Standard)
    meter_start = models.IntegerField(default=0, help_text="Starting meter value in Wh")
    meter_stop = models.IntegerField(null=True, blank=True, help_text="Ending meter value in Wh")
    
    # Power Management
    requested_power_kw = models.IntegerField(null=True, blank=True, help_text="Requested charging power in kW")
    
    # Transaction Status (OCPP Standard)
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('completed', 'Completed'),
        ('stopped', 'Stopped'),
        ('error', 'Error'),
    ]
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="active")
    
    # Cost and Billing
    cost = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True,
                             help_text="Total cost of charging session")
    pricing_plan = models.CharField(max_length=50, null=True, blank=True,
                                   help_text="Pricing plan used")

    class Meta:
        ordering = ['-started_at']  # Newest first for transactions
    
    def __str__(self):
        return f"Transaction #{self.id} ({self.id_tag}) on {self.connector}"
    
    @property
    def duration(self):
        """Calculate transaction duration."""
        if self.started_at and self.stopped_at:
            return self.stopped_at - self.started_at
        return None
    
    @property
    def energy_consumed(self):
        """Calculate energy consumed in kWh."""
        if self.meter_start is not None and self.meter_stop is not None:
            return (self.meter_stop - self.meter_start) / 1000  # Convert Wh to kWh
        return None


class MeterValue(models.Model):
    transaction = models.ForeignKey(Transaction, on_delete=models.CASCADE, related_name="meter_values")
    timestamp = models.DateTimeField(default=timezone.now, help_text="Момент на измерването")
    value = models.IntegerField(null=True, blank=True, help_text="Стойноста на брояча (ако не се ползва energy_wh)")
    
    # Нови полета за графиките:
    energy_wh = models.IntegerField(null=True, blank=True, help_text="Total energy consumed (Wh)")
    power_w = models.IntegerField(null=True, blank=True, help_text="Current charging power (W)")
    soc_percentage = models.FloatField(null=True, blank=True, help_text="State of Charge (%)")
    
    data = models.JSONField(default=dict, blank=True)  # Store dictionary data for algorithms
    
    def __str__(self):
        return f"Meter {self.energy_wh or self.value}Wh at {self.timestamp}"
    

class UserRFID(models.Model):
    tag = models.CharField(
        max_length=50, 
        unique=True,
        help_text="The RFID tag number"
    )
    owner_name = models.CharField(
        max_length=100, 
        blank=True,
        help_text="Name of the RFID card owner"
    )
    stations = models.ManyToManyField(
        'Station',
        related_name='authorized_users',
        blank=True,
        help_text="Stations this RFID can access"
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        help_text="When this RFID was registered"
    )
    last_updated = models.DateTimeField(
        auto_now=True,
        help_text="When this record was last updated"
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Whether this RFID is currently active"
    )
    notes = models.TextField(
        blank=True,
        help_text="Any additional notes about this RFID"
    )

    class Meta:
        verbose_name = "User RFID"
        verbose_name_plural = "User RFIDs"
        ordering = ['owner_name', 'tag']

    def __str__(self):
        return f"{self.owner_name} ({self.tag})" if self.owner_name else f"RFID: {self.tag}"


class PricingPlan(models.Model):
    """Pricing configuration for charging stations."""
    name = models.CharField(max_length=100, help_text="Name of the pricing plan")
    description = models.TextField(blank=True)
    
    # Pricing structure
    price_per_kwh = models.DecimalField(
        max_digits=6, decimal_places=4,
        help_text="Price per kWh in local currency"
    )
    connection_fee = models.DecimalField(
        max_digits=6, decimal_places=2, default=0,
        help_text="One-time fee for connecting (session start)"
    )
    idle_fee_per_minute = models.DecimalField(
        max_digits=6, decimal_places=4, default=0,
        help_text="Fee per minute after charging completes (to discourage overstaying)"
    )
    
    # Currency
    CURRENCY_CHOICES = [
        ('EUR', 'Euro'),
        ('USD', 'US Dollar'),
        ('GBP', 'British Pound'),
        ('BGN', 'Bulgarian Lev'),
    ]
    currency = models.CharField(max_length=3, choices=CURRENCY_CHOICES, default='EUR')
    
    # Time-based pricing (optional)
    peak_multiplier = models.DecimalField(
        max_digits=4, decimal_places=2, default=1.0,
        help_text="Multiplier for peak hours (e.g., 1.5 = 50% more)"
    )
    peak_hours_start = models.TimeField(null=True, blank=True, help_text="Start of peak hours")
    peak_hours_end = models.TimeField(null=True, blank=True, help_text="End of peak hours")
    
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "Pricing Plan"
        verbose_name_plural = "Pricing Plans"
        ordering = ['name']
    
    def __str__(self):
        return f"{self.name} ({self.price_per_kwh} {self.currency}/kWh)"


class StationPricing(models.Model):
    """Links pricing plans to stations."""
    station = models.ForeignKey(
        Station, on_delete=models.CASCADE, related_name='pricing_configs'
    )
    pricing_plan = models.ForeignKey(
        PricingPlan, on_delete=models.CASCADE, related_name='station_configs'
    )
    is_default = models.BooleanField(default=False, help_text="Default pricing for this station")
    valid_from = models.DateTimeField(null=True, blank=True)
    valid_until = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        verbose_name = "Station Pricing"
        verbose_name_plural = "Station Pricing"
        unique_together = ['station', 'pricing_plan']
    
    def __str__(self):
        return f"{self.station} - {self.pricing_plan}"


class ChargingSession(models.Model):
    """Extended transaction model with billing information."""
    transaction = models.OneToOneField(
        Transaction, on_delete=models.CASCADE, related_name='billing'
    )
    
    # User association
    # user = models.ForeignKey(
    #     'auth.User', on_delete=models.SET_NULL, null=True, blank=True,
    #     related_name='charging_sessions'
    # )
    user_id = models.IntegerField(
        null=True, blank=True,
        help_text="Reference to auth.User ID (SQLite)"
    )
    
    # Pricing used
    pricing_plan = models.ForeignKey(
        PricingPlan, on_delete=models.SET_NULL, null=True,
        related_name='sessions'
    )
    
    # Calculated costs
    energy_cost = models.DecimalField(
        max_digits=10, decimal_places=2, default=0,
        help_text="Cost for energy consumed"
    )
    connection_fee = models.DecimalField(
        max_digits=10, decimal_places=2, default=0,
        help_text="Connection/session start fee"
    )
    idle_fee = models.DecimalField(
        max_digits=10, decimal_places=2, default=0,
        help_text="Fee for idle time after charging"
    )
    total_cost = models.DecimalField(
        max_digits=10, decimal_places=2, default=0,
        help_text="Total cost for this session"
    )
    currency = models.CharField(max_length=3, default='EUR')
    
    # Payment status
    PAYMENT_STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('paid', 'Paid'),
        ('failed', 'Failed'),
        ('refunded', 'Refunded'),
    ]
    payment_status = models.CharField(
        max_length=20, choices=PAYMENT_STATUS_CHOICES, default='pending'
    )
    payment_reference = models.CharField(max_length=100, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    
    # Session details
    energy_kwh = models.DecimalField(
        max_digits=10, decimal_places=3, default=0,
        help_text="Energy delivered in kWh"
    )
    duration_minutes = models.IntegerField(default=0)
    idle_minutes = models.IntegerField(default=0)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "Charging Session"
        verbose_name_plural = "Charging Sessions"
        ordering = ['-created_at']
    
    def __str__(self):
        return f"Session {self.transaction_id} - {self.total_cost} {self.currency}"
    
    def calculate_cost(self):
        """Calculate the total cost for this session."""
        if not self.pricing_plan:
            return
        
        # Energy cost
        self.energy_cost = self.energy_kwh * self.pricing_plan.price_per_kwh
        
        # Connection fee
        self.connection_fee = self.pricing_plan.connection_fee
        
        # Idle fee (if applicable)
        if self.idle_minutes > 0 and self.pricing_plan.idle_fee_per_minute > 0:
            self.idle_fee = self.idle_minutes * self.pricing_plan.idle_fee_per_minute
        
        # Total
        self.total_cost = self.energy_cost + self.connection_fee + self.idle_fee
        self.currency = self.pricing_plan.currency


class PaymentMethod(models.Model):
    """User payment methods for charging sessions."""
    # user = models.ForeignKey(
    #     'auth.User', on_delete=models.CASCADE, related_name='payment_methods'
    # )
    user_id = models.IntegerField(null=True, blank=True, db_index=True, help_text="Reference to auth.User ID (SQLite)")
    
    TYPE_CHOICES = [
        ('card', 'Credit/Debit Card'),
        ('wallet', 'Digital Wallet'),
        ('invoice', 'Invoice'),
    ]
    type = models.CharField(max_length=20, choices=TYPE_CHOICES, default='card')
    
    # Card details (encrypted/tokenized - only last 4 digits stored)
    card_last_four = models.CharField(max_length=4, blank=True)
    card_brand = models.CharField(max_length=20, blank=True)  # visa, mastercard, etc.
    card_expiry_month = models.IntegerField(null=True, blank=True)
    card_expiry_year = models.IntegerField(null=True, blank=True)
    
    # Payment provider reference
    provider = models.CharField(max_length=50, default='stripe')
    provider_payment_method_id = models.CharField(max_length=100, blank=True)
    
    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "Payment Method"
        verbose_name_plural = "Payment Methods"
        ordering = ['-is_default', '-created_at']
    
    def __str__(self):
        if self.type == 'card':
            return f"{self.card_brand} ****{self.card_last_four}"
        return f"{self.type} - User {self.user_id}"


class Invoice(models.Model):
    """Invoices for charging sessions."""
    # user = models.ForeignKey(
    #     'auth.User', on_delete=models.CASCADE, related_name='invoices'
    # )
    user_id = models.IntegerField(null=True, blank=True, db_index=True, help_text="Reference to auth.User ID (SQLite)")
    
    # Invoice details
    invoice_number = models.CharField(max_length=50, unique=True)
    issue_date = models.DateField(auto_now_add=True)
    due_date = models.DateField()
    
    # Sessions included
    sessions = models.ManyToManyField(ChargingSession, related_name='invoices')
    
    # Totals
    subtotal = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    tax_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    tax_rate = models.DecimalField(max_digits=5, decimal_places=2, default=20.0)  # VAT %
    total = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    currency = models.CharField(max_length=3, default='EUR')
    
    # Status
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('sent', 'Sent'),
        ('paid', 'Paid'),
        ('overdue', 'Overdue'),
        ('cancelled', 'Cancelled'),
    ]
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    
    # Payment
    paid_at = models.DateTimeField(null=True, blank=True)
    payment_method = models.ForeignKey(
        PaymentMethod, on_delete=models.SET_NULL, null=True, blank=True
    )
    
    notes = models.TextField(blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "Invoice"
        verbose_name_plural = "Invoices"
        ordering = ['-issue_date']
    
    def __str__(self):
        return f"Invoice {self.invoice_number} - {self.total} {self.currency}"
    
    def calculate_totals(self):
        """Calculate invoice totals from sessions."""
        self.subtotal = sum(s.total_cost for s in self.sessions.all())
        self.tax_amount = self.subtotal * (self.tax_rate / 100)
        self.total = self.subtotal + self.tax_amount