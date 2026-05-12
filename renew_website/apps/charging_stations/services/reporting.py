from datetime import timedelta

from django.db.models import Avg, Count, DecimalField, DurationField, ExpressionWrapper, F, IntegerField, Sum, Value
from django.db.models.functions import Coalesce, ExtractHour
from django.utils import timezone

from renew_website.apps.api.deye.manager import DeyeManager, DeyeManagerError
from renew_website.apps.api.energy.models import InverterReading

from .exports import _align_datetime_for_project_timezone, serialize_transaction_report
from ..models import Connector, Station, Transaction


def _energy_kwh(queryset) -> float:
    energy_expr = ExpressionWrapper(
        F("meter_stop") - F("meter_start"),
        output_field=IntegerField(),
    )
    total_wh = queryset.filter(
        meter_start__isnull=False,
        meter_stop__isnull=False,
    ).aggregate(total_wh=Coalesce(Sum(energy_expr), Value(0, output_field=IntegerField())))["total_wh"]
    return round((total_wh or 0) / 1000, 2)


def _format_currency(value) -> str:
    return f"${float(value or 0):.2f}"


def _station_metric(station_data, *keys) -> float:
    if not station_data:
        return 0.0

    for key in keys:
        value = station_data.get(key)
        if value not in (None, ""):
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
    return 0.0


def _format_snapshot_time(value) -> str:
    if not value:
        return "No live feed"

    aligned_value = _align_datetime_for_project_timezone(value)
    if timezone.is_aware(aligned_value):
        aligned_value = timezone.localtime(aligned_value)
    return aligned_value.strftime("%H:%M")


def _derive_battery_state(solar_kw: float, load_kw: float, battery_soc: float) -> str:
    if battery_soc <= 0:
        return "Unavailable"
    if solar_kw > load_kw + 0.2 and battery_soc < 98:
        return "Charging"
    if load_kw > solar_kw + 0.2 and battery_soc > 5:
        return "Discharging"
    return "Standby"


def _build_live_energy_snapshot(connectors) -> dict:
    active_charger_power_kw = round(
        sum(float(connector.current_power_kw or 0) for connector in connectors if connector.status == "charging"),
        2,
    )

    snapshot = {
        "solar_kw": 0.0,
        "grid_kw": 0.0,
        "grid_direction": "Import",
        "load_kw": active_charger_power_kw,
        "battery_soc": 0.0,
        "battery_state": "Unavailable",
        "active_charger_power_kw": active_charger_power_kw,
        "daily_solar_kwh": 0.0,
        "lifetime_solar_kwh": 0.0,
        "renewable_ratio": 0.0,
        "data_source": "Database",
        "inverter_status": "Archive",
        "updated_at": "No live feed",
    }

    try:
        normalized_data = DeyeManager().get_latest_data()
        solar_kw = round(float(normalized_data.get("generation_power") or 0) / 1000, 2)
        grid_kw_raw = round(float(normalized_data.get("grid_power") or 0) / 1000, 2)
        load_kw = round(float(normalized_data.get("load_power") or 0) / 1000, 2)
        battery_soc = round(float(normalized_data.get("battery_soc") or 0), 1)

        snapshot.update({
            "solar_kw": solar_kw,
            "grid_kw": abs(grid_kw_raw),
            "grid_direction": "Export" if grid_kw_raw < 0 else "Import",
            "load_kw": load_kw or active_charger_power_kw,
            "battery_soc": battery_soc,
            "battery_state": _derive_battery_state(solar_kw, load_kw or active_charger_power_kw, battery_soc),
            "daily_solar_kwh": round(float(normalized_data.get("daily_energy") or normalized_data.get("today_from_pv") or 0), 2),
            "lifetime_solar_kwh": round(float(normalized_data.get("total_energy") or normalized_data.get("total_from_pv") or 0), 2),
            "data_source": str(normalized_data.get("source") or "cloud").title(),
            "inverter_status": "Online",
            "updated_at": _format_snapshot_time(timezone.now()),
        })
    except (DeyeManagerError, Exception):
        latest_reading = InverterReading.objects.select_related("inverter").order_by("-timestamp").first()
        if latest_reading:
            station_data = latest_reading.station_data or {}
            solar_kw = round(float(latest_reading.generation_power or _station_metric(station_data, "generationPower", "generation_power")) / 1000, 2)
            grid_kw_raw = round(float(latest_reading.grid_power or _station_metric(station_data, "gridPower", "grid_power", "total_grid_power")) / 1000, 2)
            load_kw = round(_station_metric(station_data, "loadPower", "load_power", "totalLoadPower", "total_load_power", "total_to_load") / 1000, 2)
            battery_soc = round(float(latest_reading.battery_soc or _station_metric(station_data, "batterySOC", "battery_soc")), 1)
            snapshot.update({
                "solar_kw": solar_kw,
                "grid_kw": abs(grid_kw_raw),
                "grid_direction": "Export" if grid_kw_raw < 0 else "Import",
                "load_kw": load_kw or active_charger_power_kw,
                "battery_soc": battery_soc,
                "battery_state": _derive_battery_state(solar_kw, load_kw or active_charger_power_kw, battery_soc),
                "daily_solar_kwh": round(_station_metric(station_data, "dailyEnergy", "daily_energy"), 2),
                "lifetime_solar_kwh": round(_station_metric(station_data, "totalEnergy", "total_energy"), 2),
                "data_source": "Database",
                "inverter_status": "Archive",
                "updated_at": _format_snapshot_time(latest_reading.timestamp),
            })

    load_reference = snapshot["load_kw"] or snapshot["active_charger_power_kw"]
    if load_reference > 0:
        snapshot["renewable_ratio"] = round(min(100.0, (snapshot["solar_kw"] / load_reference) * 100), 1)
    return snapshot


def _build_energy_trends(connectors) -> dict:
    since = timezone.now() - timedelta(hours=12)
    readings = list(
        InverterReading.objects.filter(timestamp__gte=since)
        .select_related("inverter")
        .order_by("timestamp")
    )

    if len(readings) > 24:
        step = max(1, len(readings) // 24)
        readings = readings[::step][-24:]

    labels = []
    solar_series = []
    load_series = []
    grid_series = []
    for reading in readings:
        station_data = reading.station_data or {}
        aligned_timestamp = _align_datetime_for_project_timezone(reading.timestamp)
        if timezone.is_aware(aligned_timestamp):
            aligned_timestamp = timezone.localtime(aligned_timestamp)

        labels.append(aligned_timestamp.strftime("%H:%M"))
        solar_series.append(round(float(reading.generation_power or _station_metric(station_data, "generationPower", "generation_power")) / 1000, 2))
        load_series.append(round(_station_metric(station_data, "loadPower", "load_power", "totalLoadPower", "total_load_power", "total_to_load") / 1000, 2))
        grid_series.append(round(abs(float(reading.grid_power or _station_metric(station_data, "gridPower", "grid_power", "total_grid_power"))) / 1000, 2))

    charger_usage = {
        "labels": ["Charging", "Available", "Offline", "Faulted"],
        "values": [
            sum(1 for connector in connectors if connector.status == "charging"),
            sum(1 for connector in connectors if connector.status == "available"),
            sum(1 for connector in connectors if connector.status == "offline"),
            sum(1 for connector in connectors if connector.status == "faulted"),
        ],
    }

    return {
        "labels": labels,
        "solar_kw": solar_series,
        "load_kw": load_series,
        "grid_kw": grid_series,
        "charger_usage": charger_usage,
    }


def build_quick_stats(transactions) -> dict:
    tx_list = list(transactions)
    return {
        "successful": sum(1 for tx in tx_list if tx.session_result == "Successful"),
        "failed": sum(1 for tx in tx_list if tx.session_result in {"Failed", "Aborted", "No Energy"}),
        "avg_energy": round(sum(float(tx.energy_kwh or 0) for tx in tx_list) / len(tx_list), 2) if tx_list else 0,
        "avg_duration": round(sum(tx.duration_seconds for tx in tx_list) / len(tx_list) / 60, 1) if tx_list else 0,
        "total_energy": round(sum(float(tx.energy_kwh or 0) for tx in tx_list), 2),
    }


def get_transaction_window(request, now):
    timerange = request.GET.get("timerange", "24h")
    selected_date = request.GET.get("date", "")

    if timerange == "week":
        start_date = now - timedelta(days=7)
        end_date = now
    elif timerange == "month":
        start_date = now - timedelta(days=30)
        end_date = now
    elif timerange == "date" and selected_date:
        try:
            parsed_date = timezone.datetime.strptime(selected_date, "%Y-%m-%d").date()
            start_date = _align_datetime_for_project_timezone(
                timezone.datetime.combine(parsed_date, timezone.datetime.min.time())
            )
            end_date = start_date + timedelta(days=1)
        except ValueError:
            timerange = "24h"
            selected_date = ""
            start_date = now - timedelta(days=1)
            end_date = now
    else:
        timerange = "24h"
        selected_date = ""
        start_date = now - timedelta(days=1)
        end_date = now

    return timerange, selected_date, start_date, end_date


def get_chart_window(request, now):
    time_range = request.GET.get("range", "24h")
    selected_date = request.GET.get("date", "")

    if time_range == "lastMonth":
        start_date = now - timedelta(days=30)
        end_date = now
        bucket = "day"
    elif time_range == "specificDay" and selected_date:
        try:
            parsed_date = timezone.datetime.strptime(selected_date, "%Y-%m-%d").date()
            start_date = _align_datetime_for_project_timezone(
                timezone.datetime.combine(parsed_date, timezone.datetime.min.time())
            )
            end_date = start_date + timedelta(days=1)
            bucket = "hour"
        except ValueError:
            time_range = "24h"
            selected_date = ""
            start_date = now - timedelta(days=1)
            end_date = now
            bucket = "hour"
    else:
        time_range = "24h"
        selected_date = ""
        start_date = now - timedelta(days=1)
        end_date = now
        bucket = "hour"

    return time_range, selected_date, start_date, end_date, bucket


def build_public_dashboard_context(request) -> dict:
    now = timezone.now()
    today = now.date()
    week_start = now - timedelta(days=7)
    month_start = now - timedelta(days=30)

    stations = list(Station.objects.prefetch_related("connectors").all())
    connectors = list(Connector.objects.select_related("station").all())
    transactions = Transaction.objects.select_related("connector__station").all()

    total_stations = len(stations)
    online_stations = sum(1 for station in stations if station.is_online)
    total_chargers = len(connectors)

    charger_status_counts = {
        "available": 0,
        "charging": 0,
        "faulted": 0,
        "offline": 0,
    }
    for connector in connectors:
        status_key = (connector.status or "offline").lower()
        if status_key in charger_status_counts:
            charger_status_counts[status_key] += 1
        elif status_key != "available":
            charger_status_counts["offline"] += 1

    active_sessions_count = transactions.filter(status="active").count()
    total_sessions_today = transactions.filter(started_at__date=today).count()
    completed_transactions = transactions.exclude(stopped_at__isnull=True)
    today_transactions = transactions.filter(started_at__date=today)
    week_transactions = transactions.filter(started_at__gte=week_start)
    month_transactions = transactions.filter(started_at__gte=month_start)
    txn_timerange, txn_selected_date, txn_start_date, txn_end_date = get_transaction_window(request, now)
    filtered_transactions = transactions.filter(started_at__gte=txn_start_date, started_at__lt=txn_end_date).order_by("-started_at")
    recent_transactions = list(filtered_transactions[:20])

    avg_duration = completed_transactions.aggregate(
        avg_duration=Avg(
            ExpressionWrapper(
                F("stopped_at") - F("started_at"),
                output_field=DurationField(),
            )
        )
    )["avg_duration"]
    avg_session_duration = round(avg_duration.total_seconds() / 60, 1) if avg_duration else 0

    peak_hour = transactions.annotate(hour=ExtractHour("started_at")).values("hour").annotate(
        total=Count("id")
    ).order_by("-total", "hour").first()

    for station in stations:
        station.prefetched_connectors = list(station.connectors.all())
        for connector in station.prefetched_connectors:
            connector.status_class = (connector.status or "offline").lower()

    quick_stats = build_quick_stats(recent_transactions)
    recent_transaction_rows = [serialize_transaction_report(tx) for tx in recent_transactions]

    zero_currency = Value(0, output_field=DecimalField(max_digits=10, decimal_places=2))
    today_revenue_total = today_transactions.aggregate(total=Coalesce(Sum("cost"), zero_currency))["total"]
    month_revenue_total = month_transactions.aggregate(total=Coalesce(Sum("cost"), zero_currency))["total"]
    utilization_percent = round((charger_status_counts["charging"] / total_chargers) * 100, 1) if total_chargers else 0
    live_energy_snapshot = _build_live_energy_snapshot(connectors)
    energy_trends = _build_energy_trends(connectors)

    return {
        "active_sessions_count": active_sessions_count,
        "total_sessions_today": total_sessions_today,
        "energy_delivered_today": _energy_kwh(today_transactions),
        "online_stations": online_stations,
        "total_stations": total_stations,
        "today_revenue": _format_currency(today_revenue_total),
        "total_chargers": total_chargers,
        "charger_status_counts": charger_status_counts,
        "stations_with_connectors": stations,
        "utilization_percent": utilization_percent,
        "avg_session_duration": avg_session_duration,
        "peak_hour": peak_hour["hour"] if peak_hour and peak_hour["hour"] is not None else None,
        "energy_week_kwh": _energy_kwh(week_transactions),
        "energy_month_kwh": _energy_kwh(month_transactions),
        "month_revenue": _format_currency(month_revenue_total),
        "avg_revenue_per_session": _format_currency((month_revenue_total or 0) / month_transactions.count()) if month_transactions.exists() else _format_currency(0),
        "live_energy_snapshot": live_energy_snapshot,
        "energy_trends": energy_trends,
        "quick_stats": quick_stats,
        "recent_transactions": recent_transactions,
        "recent_transaction_rows": recent_transaction_rows,
        "txn_time_filter": txn_timerange,
        "txn_date_filter": txn_selected_date,
    }


def build_recent_transactions_payload(request) -> dict:
    now = timezone.now()
    _, selected_date, start_date, end_date = get_transaction_window(request, now)
    queryset = Transaction.objects.select_related("connector__station").filter(
        started_at__gte=start_date,
        started_at__lt=end_date,
    ).order_by("-started_at")[:20]
    tx_list = list(queryset)

    return {
        "date": selected_date,
        "transactions": [serialize_transaction_report(tx) for tx in tx_list],
        "quick_stats": build_quick_stats(tx_list),
    }


def build_session_chart_payload(request) -> dict:
    now = timezone.now()
    time_range, selected_date, start_date, end_date, bucket = get_chart_window(request, now)
    txs = Transaction.objects.filter(started_at__gte=start_date, started_at__lt=end_date).order_by("started_at")

    labels = []
    success_data = []
    failed_data = []
    partial_data = []

    buckets_map = {}
    curr = start_date
    step = timedelta(hours=1) if bucket == "hour" else timedelta(days=1)
    while curr < end_date:
        label = curr.strftime("%H:00") if bucket == "hour" else curr.strftime("%a, %b %d")
        buckets_map[label] = {"success": 0, "failed": 0, "partial": 0}
        curr += step

    for tx in txs:
        aligned_started_at = _align_datetime_for_project_timezone(tx.started_at)
        if timezone.is_aware(aligned_started_at):
            aligned_started_at = timezone.localtime(aligned_started_at)
        label = aligned_started_at.strftime("%H:00") if bucket == "hour" else aligned_started_at.strftime("%a, %b %d")
        if label in buckets_map:
            res = tx.session_result
            if res == "Successful":
                buckets_map[label]["success"] += 1
            elif res in ["Failed", "Aborted", "No Energy"]:
                buckets_map[label]["failed"] += 1
            else:
                buckets_map[label]["partial"] += 1

    for label, counts in buckets_map.items():
        labels.append(label)
        success_data.append(counts["success"])
        failed_data.append(counts["failed"])
        partial_data.append(counts["partial"])

    return {
        "range": time_range,
        "date": selected_date,
        "labels": labels,
        "datasets": {
            "success": success_data,
            "failed": failed_data,
            "partial": partial_data,
        },
    }