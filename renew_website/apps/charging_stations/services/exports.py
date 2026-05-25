import csv
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from django.http import HttpResponse
from django.utils import timezone

from ..models import Transaction


SIMULATOR_MODEL_SIGNATURES = ("simulator", "simulation", "avt-express")
MIN_REAL_CHARGE_KWH = Decimal("0.05")
LONG_SESSION_NO_ENERGY_SECONDS = 300
DEFAULT_TEST_RFID_TAG = None  # Disabled: was "000000010160897" but this is a real station RFID


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


def _normalized_text(value: Any) -> str:
    return str(value or "").strip().lower()


def _latest_transaction_meter_data(tx: Transaction) -> dict:
    meter_values = list(tx.meter_values.all())
    if not meter_values:
        return {}
    return meter_values[-1].data or {}


def _transaction_session_context(tx: Transaction) -> dict:
    for meter_value in reversed(list(tx.meter_values.all())):
        data = meter_value.data or {}
        session_context = data.get("session_context")
        if isinstance(session_context, dict) and session_context:
            return session_context
    return {}


def _transaction_has_any_power_measurements(tx: Transaction) -> bool:
    return any(mv.power_w is not None for mv in tx.meter_values.all())


def _transaction_has_power_samples(tx: Transaction) -> bool:
    return any(mv.power_w not in (None, 0) for mv in tx.meter_values.all())


def _transaction_has_meter_delta(tx: Transaction) -> bool:
    if get_transaction_energy_kwh(tx) >= MIN_REAL_CHARGE_KWH:
        return True

    for meter_value in tx.meter_values.all():
        if meter_value.energy_wh not in (None, 0):
            return True
        data = meter_value.data or {}
        meter_start = data.get("meter_start")
        meter_stop = data.get("meter_stop")
        if meter_start is not None and meter_stop is not None and meter_stop > meter_start:
            return True
    return False


def _transaction_has_meter_telemetry(tx: Transaction) -> bool:
    for meter_value in tx.meter_values.all():
        if meter_value.power_w not in (None, 0):
            return True
        if meter_value.energy_wh not in (None, 0):
            return True
        data = meter_value.data or {}
        meter_start = data.get("meter_start")
        meter_stop = data.get("meter_stop")
        if meter_start is not None and meter_stop is not None and meter_stop > meter_start:
            return True
        samples = data.get("samples")
        if isinstance(samples, list) and samples:
            return True
    return False


def _is_simulated_station(tx: Transaction) -> bool:
    session_context = _transaction_session_context(tx)
    station = getattr(getattr(tx, "connector", None), "station", None)
    if _normalized_text(getattr(station, "runtime_environment", "")) == "simulated":
        return True

    source = _normalized_text(
        session_context.get("session_source")
        or session_context.get("source")
        or session_context.get("runtime_type")
    )
    # Platform-commanded sessions (RemoteStart) are NOT simulated; they are real charging
    if source == "platform":
        return False
    if source in {"simulator", "simulation", "simulated"}:
        return True

    if _normalized_text(getattr(tx, "id_tag", "")) == DEFAULT_TEST_RFID_TAG:
        return True

    if _normalized_text(getattr(tx, "id_tag", "")).startswith("simulated_"):
        return True
    model_signature = " ".join(
        part for part in [
            session_context.get("runtime_charge_point_model"),
            session_context.get("runtime_charge_point_vendor"),
            getattr(station, "model", None),
            getattr(station, "ocpp_identity", None),
            getattr(station, "connector_type", None),
        ] if part
    ).lower()
    return any(signature in model_signature for signature in SIMULATOR_MODEL_SIGNATURES)


def _is_verified_physical_station(tx: Transaction) -> bool:
    station = getattr(getattr(tx, "connector", None), "station", None)
    return _normalized_text(getattr(station, "runtime_environment", "")) == "physical"


def get_transaction_source(tx: Transaction) -> tuple[str, str]:
    if _is_simulated_station(tx):
        return "Simulated", "secondary"
    if _transaction_has_power_samples(tx):
        return "Measured", "success"
    if _transaction_has_meter_telemetry(tx):
        return "Metered Only", "info"
    return "Limited Telemetry", "warning"


def get_transaction_telemetry_status(tx: Transaction) -> str:
    if _transaction_has_power_samples(tx):
        return "Power + energy telemetry"
    if _transaction_has_meter_telemetry(tx):
        return "Energy-only telemetry"
    return "No power or meter telemetry"


def get_transaction_summary_bucket(tx: Transaction) -> str:
    classification = classify_transaction(tx)
    return classification["summary"]


def _get_data_quality(tx: Transaction, duration_seconds: int, has_meter_delta: bool, has_power_samples: bool, has_any_power_measurements: bool, has_meter_telemetry: bool, requested_power: bool) -> tuple[str, str]:
    if has_power_samples and has_meter_delta:
        return "Good", "success"
    if (has_any_power_measurements or requested_power) and not has_meter_delta and duration_seconds >= LONG_SESSION_NO_ENERGY_SECONDS:
        return "Inconsistent", "danger"
    if has_meter_delta or has_meter_telemetry or has_any_power_measurements:
        return "Partial", "warning"
    return "Missing", "secondary"


def _get_authenticity(is_simulated: bool, is_verified_physical: bool, status: str, duration_seconds: int, has_meter_delta: bool, has_any_power_measurements: bool, has_meter_telemetry: bool, requested_power: bool, data_quality: str) -> tuple[str, str]:
    if is_simulated:
        return "Simulated", "secondary"
    # Treat completed/stopped sessions with telemetry as real even when
    # runtime_environment metadata is missing on the station record.
    if status in {"completed", "stopped"} and (has_meter_delta or has_any_power_measurements or has_meter_telemetry):
        return "Real Charge", "success"
    if is_verified_physical and has_meter_delta:
        return "Real Charge", "success"
    if data_quality == "Inconsistent":
        return "Unknown", "danger"
    if status in {"completed", "stopped"} and not has_any_power_measurements and duration_seconds < LONG_SESSION_NO_ENERGY_SECONDS:
        return "No Energy", "warning"
    if status == "error" and not has_any_power_measurements and duration_seconds < 60:
        return "No Energy", "warning"
    if has_meter_telemetry and not has_any_power_measurements:
        return "No Energy", "warning"
    return "Unknown", "dark"


def _get_confidence_score(authenticity: str, data_quality: str) -> str:
    score_map = {
        ("Simulated", "Good"): "1.00",
        ("Simulated", "Partial"): "1.00",
        ("Simulated", "Missing"): "1.00",
        ("Real Charge", "Good"): "0.98",
        ("Real Charge", "Partial"): "0.90",
        ("Real Charge", "Missing"): "0.75",
        ("No Energy", "Partial"): "0.55",
        ("No Energy", "Missing"): "0.40",
        ("Unknown", "Partial"): "0.40",
        ("Unknown", "Missing"): "0.20",
        ("Unknown", "Inconsistent"): "0.15",
    }
    return score_map.get((authenticity, data_quality), "0.50")


def classify_transaction(tx: Transaction) -> dict[str, str]:
    duration_seconds = get_transaction_duration_seconds(tx)
    status = _normalized_text(tx.status)
    is_simulated = _is_simulated_station(tx)
    is_verified_physical = _is_verified_physical_station(tx)
    has_meter_delta = _transaction_has_meter_delta(tx)
    has_power_samples = _transaction_has_power_samples(tx)
    has_any_power_measurements = _transaction_has_any_power_measurements(tx)
    has_meter_telemetry = _transaction_has_meter_telemetry(tx)
    requested_power = tx.requested_power_kw not in (None, "", 0)
    data_quality, data_quality_badge = _get_data_quality(
        tx=tx,
        duration_seconds=duration_seconds,
        has_meter_delta=has_meter_delta,
        has_power_samples=has_power_samples,
        has_any_power_measurements=has_any_power_measurements,
        has_meter_telemetry=has_meter_telemetry,
        requested_power=requested_power,
    )
    authenticity, authenticity_badge = _get_authenticity(
        is_simulated=is_simulated,
        is_verified_physical=is_verified_physical,
        status=status,
        duration_seconds=duration_seconds,
        has_meter_delta=has_meter_delta,
        has_any_power_measurements=has_any_power_measurements,
        has_meter_telemetry=has_meter_telemetry,
        requested_power=requested_power,
        data_quality=data_quality,
    )
    confidence_score = _get_confidence_score(authenticity, data_quality)

    if is_simulated:
        return {
            "label": "Test / Simulated",
            "summary": "simulated",
            "badge": "secondary",
            "authenticity": authenticity,
            "authenticity_badge": authenticity_badge,
            "data_quality": data_quality,
            "data_quality_badge": data_quality_badge,
            "confidence_score": confidence_score,
        }

    if status == "active":
        label = "In Progress"
        summary = "partial"
        badge = "info"
    elif status == "error":
        if has_meter_delta or has_power_samples:
            label = "Interrupted"
            summary = "partial"
            badge = "warning"
        else:
            label = "Failed"
            summary = "failed"
            badge = "danger"
    elif status == "stopped":
        if has_meter_delta or has_power_samples:
            label = "Interrupted"
            summary = "partial"
            badge = "warning"
        else:
            label = "Aborted"
            summary = "partial"
            badge = "warning"
    elif status == "completed":
        # For completed sessions, mark as successful if any telemetry exists
        # Real physical charging stations should always report success if completed
        if has_meter_delta or has_meter_telemetry or has_any_power_measurements:
            label = "Completed"
            summary = "successful"
            badge = "success"
        else:
            label = "Aborted"
            summary = "partial"
            badge = "warning"
    elif has_meter_delta:
        label = "Completed"
        summary = "successful"
        badge = "success"
    else:
        label = "Unknown"
        summary = "failed"
        badge = "secondary"

    return {
        "label": label,
        "summary": summary,
        "badge": badge,
        "authenticity": authenticity,
        "authenticity_badge": authenticity_badge,
        "data_quality": data_quality,
        "data_quality_badge": data_quality_badge,
        "confidence_score": confidence_score,
    }


def get_transaction_result(tx: Transaction) -> tuple[str, str]:
    classification = classify_transaction(tx)
    return classification["label"], classification["badge"]


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
    return "—"


def _format_duration_hms(tx: Transaction) -> str:
    duration_seconds = get_transaction_duration_seconds(tx)
    if duration_seconds <= 0:
        return "—"
    hours, remainder = divmod(duration_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def serialize_transaction_report(tx: Transaction) -> dict:
    transaction_identifier = tx.transaction_id or tx.id
    stop_reason = get_transaction_stop_reason(tx)
    avg_power = get_transaction_avg_power_kw(tx)
    peak_power = get_transaction_peak_power_kw(tx)
    classification = classify_transaction(tx)
    session_result, result_class = get_transaction_result(tx)
    session_source, session_source_class = get_transaction_source(tx)
    telemetry_status = get_transaction_telemetry_status(tx)
    diagnostics = (
        f"Authenticity: {classification['authenticity']} | "
        f"Data Quality: {classification['data_quality']} | "
        f"Confidence: {classification['confidence_score']} | "
        f"Stop Reason: {stop_reason} | Source: {session_source} | Telemetry: {telemetry_status}"
    )

    return {
        "id": tx.id,
        "transaction_id": transaction_identifier,
        "station_name": tx.connector.station.formatted_serial(),
        "connector_id": tx.connector.connector_id,
        "vehicle_id": tx.id_tag,
        "start_time": _format_datetime(tx.started_at),
        "end_time": _format_datetime(tx.stopped_at),
        "duration_display": _format_duration_hms(tx),
        "energy_kwh": _format_decimal(get_transaction_energy_kwh(tx), places=2),
        "avg_power_kw": _format_decimal(avg_power, places=2) if avg_power != "—" else "—",
        "peak_power_kw": _format_decimal(peak_power, places=2) if peak_power != "—" else "—",
        "session_status": classification["label"],
        "status_class": classification["badge"],
        "session_authenticity": classification["authenticity"],
        "authenticity_class": classification["authenticity_badge"],
        "data_quality": classification["data_quality"],
        "data_quality_class": classification["data_quality_badge"],
        "confidence_score": classification["confidence_score"],
        "session_validation": classification["authenticity"],
        "validation_class": classification["authenticity_badge"],
        "session_result": session_result,
        "result_class": result_class,
        "session_source": session_source,
        "session_source_class": session_source_class,
        "telemetry_status": telemetry_status,
        "stop_reason": stop_reason,
        "diagnostics_summary": diagnostics,
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
        'Start Time', 'End Time', 'Duration',
        'Energy (kWh)', 'Avg Power (kW)', 'Peak Power (kW)', 'Session Status', 'Authenticity', 'Data Quality', 'Confidence Score', 'Stop Reason', 'Session Source', 'Telemetry'
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
            row["duration_display"],
            row["energy_kwh"],
            row["avg_power_kw"],
            row["peak_power_kw"],
            row["session_status"],
            row["session_authenticity"],
            row["data_quality"],
            row["confidence_score"],
            row["stop_reason"],
            row["session_source"],
            row["telemetry_status"],
        ])
        
    return response