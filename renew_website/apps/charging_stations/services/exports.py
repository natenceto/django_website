import csv
from datetime import datetime, timedelta
from decimal import Decimal

from django.http import HttpResponse
from django.utils import timezone

from ..models import Transaction


SUCCESS_STOP_REASONS = {"Local", "Remote", "EVDisconnected", "UnlockCommand"}
FAILURE_STOP_REASONS = {"EmergencyStop", "PowerLoss", "HardReset", "SoftReset", "Reboot", "DeAuthorized"}


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


def get_transaction_energy_kwh(tx: Transaction) -> Decimal:
    if tx.meter_start is None or tx.meter_stop is None:
        return Decimal("0")
    return Decimal(max(tx.meter_stop - tx.meter_start, 0)) / Decimal("1000")


def get_transaction_duration_seconds(tx: Transaction) -> int:
    if not tx.started_at or not tx.stopped_at:
        return 0
    return max(int((tx.stopped_at - tx.started_at).total_seconds()), 0)


def get_transaction_result(tx: Transaction) -> tuple[str, str]:
    energy_kwh = get_transaction_energy_kwh(tx)
    stop_reason = get_transaction_stop_reason(tx)

    if tx.status == "completed":
        if stop_reason in FAILURE_STOP_REASONS:
            if energy_kwh > 0:
                return "Partial", "warning"
            return "Failed", "danger"
        if stop_reason in SUCCESS_STOP_REASONS:
            return "Successful", "success"
        if energy_kwh > 0:
            return "Successful", "success"
        return "Failed", "danger"
    if tx.status == "stopped":
        if energy_kwh > 0:
            return "Partial", "warning"
        return "Failed", "danger"
    if tx.status == "error":
        return "Failed", "danger"
    return "In Progress", "info"


def get_transaction_stop_reason(tx: Transaction) -> str:
    direct_reason = getattr(tx, "stop_reason", None) or getattr(tx, "session_stop_reason", None)
    if direct_reason:
        return direct_reason

    meter_values = list(tx.meter_values.all())
    for meter_value in reversed(meter_values):
        data = meter_value.data or {}
        reason = data.get("reason")
        if reason:
            return reason

    return "—"


def get_transaction_avg_power_kw(tx: Transaction):
    power_values = [mv.power_w for mv in tx.meter_values.all() if mv.power_w is not None]
    if not power_values:
        return "—"
    return Decimal(sum(power_values) / len(power_values) / 1000)


def get_transaction_peak_power_kw(tx: Transaction):
    power_values = [mv.power_w for mv in tx.meter_values.all() if mv.power_w is not None]
    if power_values:
        return Decimal(max(power_values) / 1000)
    if tx.requested_power_kw not in (None, ""):
        return Decimal(str(tx.requested_power_kw))
    return "—"


def _format_duration_minutes(tx: Transaction) -> str:
    duration_seconds = get_transaction_duration_seconds(tx)
    if duration_seconds <= 0:
        return "—"
    return _format_decimal(duration_seconds / 60, places=2)


def serialize_transaction_report(tx: Transaction) -> dict:
    transaction_identifier = tx.transaction_id or tx.id
    stop_reason = get_transaction_stop_reason(tx)
    avg_power = get_transaction_avg_power_kw(tx)
    peak_power = get_transaction_peak_power_kw(tx)
    session_result, result_class = get_transaction_result(tx)

    return {
        "id": tx.id,
        "transaction_id": transaction_identifier,
        "station_name": tx.connector.station.formatted_serial(),
        "connector_id": tx.connector.connector_id,
        "vehicle_id": tx.id_tag,
        "start_time": _format_datetime(tx.started_at),
        "end_time": _format_datetime(tx.stopped_at),
        "duration_minutes": _format_duration_minutes(tx),
        "energy_kwh": _format_decimal(get_transaction_energy_kwh(tx), places=2),
        "avg_power_kw": _format_decimal(avg_power, places=2) if avg_power != "—" else "—",
        "peak_power_kw": _format_decimal(peak_power, places=2) if peak_power != "—" else "—",
        "session_result": session_result,
        "result_class": result_class,
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
    ).select_related('connector__station', 'billing').prefetch_related('meter_values').order_by('-started_at')

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