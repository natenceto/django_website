from datetime import timedelta

from django.db.models import Avg, Count, DecimalField, DurationField, ExpressionWrapper, F, IntegerField, Sum, Value
from django.db.models.functions import Coalesce, ExtractHour
from django.utils import timezone

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