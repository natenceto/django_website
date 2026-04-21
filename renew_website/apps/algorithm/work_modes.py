from django.db import models
from django.utils.translation import gettext_lazy as _

class SystemWorkMode(models.TextChoices):

    # --- 1. Dynamic Local Balancing (Zero Export To Load) ---
    # These modes rely on the Deye inverter automatically handling PV/Battery flow. 
    # The algorithm controls exactly how much load the EV chargers represent.

    # Solar ONLY for EVs. Assumes: Priority 1: Building, Priority 2: Battery (until a certain %), Priority 3: EVs.
    # Algorithm calculates (PV - Building_Load), and restricts EV. Battery does not discharge to EV.
    ECO_CHARGE = 'ECO_CHARGE', _('Eco Charge (Solar Only)')
    
    # Solar + Small Battery Buffer. Priority 1: Building, Priority 2: EVs, Priority 3: Batteries.
    # EV chargers dynamically get (PV + Allowed_Battery_Discharge - Building_Load). Smooths out clouds.
    SMART_CHARGE = 'SMART_CHARGE', _('Smart Charge (Solar + Minimal Battery)')
    
    # Maximum requested power. EV chargers unrestricted up to max site limit. 
    # Deye fulfills it automatically from PV -> Battery -> Grid.
    FAST_CHARGE = 'FAST_CHARGE', _('Fast Charge (Grid + PV + Battery)')
    
    # --- 2. Macro Hardware Overrides (EEPROM Writes) ---
    # Only use these modes for critical environment changes.

    # EVs are completely paused or limited to minimum to reserve power. 
    # Inverter is forced to charge batteries via Grid Charge Enable (Night Tariff / Expecting Storm).
    PROTECT_BATTERY = 'PROTECT_BATTERY', _('Protect Battery (Grid Charge Enabled)')
    
    # Grid is down. Island mode. EV chargers are restricted/paused automatically.
    EMERGENCY_BACKUP = 'EMERGENCY_BACKUP', _('Emergency Backup (Off-Grid)')
