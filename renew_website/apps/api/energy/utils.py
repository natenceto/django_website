"""
Energy management utility functions.
"""
import logging
from django.utils import timezone
from .models import WorkMode

logger = logging.getLogger(__name__)

def run_work_mode_algorithm(inverter=None):
    """
    Determines the optimal work mode based on current conditions.
    
    Returns:
        str: one of ['selling_first', 'zero_export_load', 'zero_export_ct']
    """
    # Simple logic for now: default to selling_first
    # In a real implementation, this would check battery SOC, grid price, weather, etc.
    return 'selling_first'
