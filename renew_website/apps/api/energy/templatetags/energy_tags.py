"""
Template tags for energy management.
"""
from django import template

register = template.Library()


@register.filter
def format_power(value):
    """Format power value with appropriate unit."""
    if value is None:
        return "0 W"
    
    if value >= 1000:
        return f"{value/1000:.1f} kW"
    else:
        return f"{value:.0f} W"


@register.filter
def format_percentage(value):
    """Format percentage value."""
    if value is None:
        return "0%"
    return f"{value:.1f}%"


@register.simple_tag
def get_battery_color(soc):
    """Get color based on battery state of charge."""
    if soc is None:
        return "gray"
    elif soc >= 80:
        return "green"
    elif soc >= 50:
        return "yellow"
    elif soc >= 20:
        return "orange"
    else:
        return "red"
