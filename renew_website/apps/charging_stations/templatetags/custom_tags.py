from django import template
from django.template.defaultfilters import length

register = template.Library()

@register.filter
def unique_stations(transactions):
    """Count unique stations from transactions"""
    station_ids = set()
    for transaction in transactions:
        station_ids.add(transaction.connector.station.id)
    return len(station_ids)
