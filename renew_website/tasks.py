from celery import shared_task
import logging
from django.utils import timezone

from renew_website.apps.charging_stations.models import CommandLog, Connector, Station

logger = logging.getLogger(__name__)

@shared_task
def sample_task():
    """
    A sample task for demonstration.
    """
    logger.info("Sample task executed successfully.")
    return "Done"


@shared_task
def reset_station_runtime_state():
    """Reset stale station runtime state outside the ASGI startup path."""
    updated_stations = Station.objects.filter(status='active').update(status='inactive')
    updated_connectors = Connector.objects.exclude(status='available').update(status='offline')
    logger.info(
        "Reset station runtime state: stations=%s connectors=%s",
        updated_stations,
        updated_connectors,
    )
    return {
        'stations': updated_stations,
        'connectors': updated_connectors,
    }


@shared_task
def mark_command_timeout(command_id: str):
    """Mark a dispatched command as timed out if the station never answered."""
    command_log = CommandLog.objects.filter(command_id=command_id).first()
    if not command_log:
        return {"updated": False, "reason": "not_found"}
    if command_log.status != 'sent':
        return {"updated": False, "reason": f"already_{command_log.status}"}

    command_log.status = 'timeout'
    command_log.detail = 'No station response received before timeout threshold'
    command_log.error_message = 'Command timed out waiting for station response'
    command_log.executed_at = timezone.now()
    command_log.save(update_fields=['status', 'detail', 'error_message', 'executed_at'])
    logger.warning('Command %s timed out waiting for station response', command_id)
    return {"updated": True, "status": "timeout"}
