import csv
from datetime import datetime, timedelta
from decimal import Decimal

from django.http import HttpResponse
from django.utils import timezone

from ..models import Transaction


def _align_datetime_for_project_timezone(value: datetime) -> datetime:
    if timezone.is_naive(value):
        return value if not timezone.is_aware(timezone.now()) else timezone.make_aware(value)
    return value


def _format_datetime(value: datetime | None) -> str:
    if not value:
        return "—"

    aligned_value = _align_datetime_for_project_timezone(value)
    if timezone.is_aware(aligned_value):
        aligned_value = timezone.localtime(aligned_value)
    return aligned_value.strftime("%Y-%m-%d %H:%M:%S")


def _format_decimal(value, places=2):
    if value in (None, "", "—"):
        return "—"

    quantized = Decimal(str(value)).quantize(Decimal("1." + ("0" * places)))
    normalized = format(quantized.normalize(), "f")
    return normalized if "." in normalized else normalized


def _format_duration_minutes(tx: Transaction) -> str:
    if tx.duration_seconds <= 0:
        return "—"
    return _format_decimal(tx.duration_seconds / 60, places=2)


def serialize_transaction_report(tx: Transaction) -> dict:
    transaction_identifier = tx.transaction_id or tx.id
    stop_reason = tx.stop_reason or tx.session_stop_reason or "—"
    avg_power = tx.avg_power_kw if tx.avg_power_kw != "—" else "—"
    requested_power = tx.requested_power_kw if tx.requested_power_kw not in (None, "") else "—"

    return {
        "id": tx.id,
        "transaction_id": transaction_identifier,
        "station_name": tx.connector.station.address,
        "connector_id": tx.connector.connector_id,
        "vehicle_id": tx.id_tag,
        "start_time": _format_datetime(tx.started_at),
        "end_time": _format_datetime(tx.stopped_at),
        "duration_minutes": _format_duration_minutes(tx),
        "energy_kwh": _format_decimal(tx.energy_kwh or 0, places=2),
        "avg_power_kw": _format_decimal(avg_power, places=2) if avg_power != "—" else "—",
        "peak_power_kw": str(requested_power),
        "session_result": tx.session_result,
        "result_class": tx.result_class,
        "stop_reason": stop_reason,
    }


def get_filtered_transactions(request):
    """Return export queryset based on dashboard timerange/date filters."""
    end_date = timezone.now()
    timerange = request.GET.get('timerange', '24h')
    selected_date = request.GET.get('date')

    if timerange == 'week':
        start_date = end_date - timedelta(days=7)
        end_range = end_date
    elif timerange == 'month':
        start_date = end_date - timedelta(days=30)
        end_range = end_date
    elif timerange == 'date' and selected_date:
        try:
            target_date = datetime.strptime(selected_date, '%Y-%m-%d').date()
            start_date = _align_datetime_for_project_timezone(datetime.combine(target_date, datetime.min.time()))
            end_range = start_date + timedelta(days=1)
        except ValueError:
            start_date = end_date - timedelta(days=1)
            end_range = end_date
    else:
        start_date = end_date - timedelta(days=1)
        end_range = end_date

    return Transaction.objects.filter(
        started_at__gte=start_date,
        started_at__lt=end_range,
    ).select_related('connector__station').order_by('-started_at')

def download_transactions_csv(transactions):
    """Generate and return a CSV response for a given queryset of transactions."""
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="charging_sessions.csv"'
    
    writer = csv.writer(response)
    
    # Write header
    writer.writerow([
        'Transaction ID', 'Station Name', 'Connector', 'Vehicle ID', 
        'Start Time', 'End Time', 'Duration (min)',
        'Energy (kWh)', 'Avg Power (kW)', 'Peak Power (kW)', 'Session Result', 'Stop Reason'
    ])
    
    # Write data
    for tx in transactions:
        row = serialize_transaction_report(tx)

        writer.writerow([
            row["transaction_id"],
            row["station_name"],
            row["connector_id"],
            row["vehicle_id"],
            row["start_time"],
            row["end_time"],
            row["duration_minutes"],
            row["energy_kwh"],
            row["avg_power_kw"],
            row["peak_power_kw"],
            row["session_result"],
            row["stop_reason"],
        ])
        
    return response