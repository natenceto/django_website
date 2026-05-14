import csv
import json
from collections import defaultdict
from datetime import datetime, time, timedelta
from urllib.parse import urlencode

from django.core.paginator import Paginator
from django.shortcuts import render, redirect
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.contrib import messages
from django.db.models import F, Sum
from django.utils import timezone

from .models import Station, MeterValue, Transaction, StationStatusHistory

from .services import execute_station_action


STATISTICS_RANGE_CHOICES = [
    ('24h', 'Last 24 Hours'),
    ('week', 'Last Week'),
    ('month', 'Last Month'),
    ('date', 'Specific Date'),
]


def _format_power_value(power_kw):
    if power_kw is None:
        return "--"
    return f"{float(power_kw):.2f} kW"


def _build_requested_power_label(transaction):
    if not transaction:
        return "--"
    if transaction.requested_power_mode == 'auto' and transaction.requested_power_kw is None:
        return "Auto"
    if transaction.requested_power_kw is not None:
        return f"{float(transaction.requested_power_kw):.2f} kW"
    return "Station default"


def _attach_station_live_power_state(stations_list):
    active_transactions = list(
        Transaction.objects
        .filter(status='active')
        .select_related('connector', 'vehicle')
        .order_by('-started_at', '-id')
    )

    latest_tx_by_station = {}
    latest_meter_by_tx = {}
    for transaction in active_transactions:
        latest_tx_by_station.setdefault(transaction.connector.station_id, transaction)
        latest_meter_by_tx[transaction.id] = transaction.meter_values.order_by('-timestamp', '-id').first()

    latest_session_snapshot = {
        'vehicle_soc': None,
        'requested_power_display': '--',
        'requested_power_mode_label': '--',
        'actual_power_display': '--',
        'ems_limit_display': '--',
    }

    if active_transactions:
        latest_transaction = active_transactions[0]
        latest_meter = latest_meter_by_tx.get(latest_transaction.id)
        latest_soc = None
        if latest_meter and latest_meter.soc_percentage is not None:
            latest_soc = round(float(latest_meter.soc_percentage), 2)
        elif latest_transaction.vehicle and latest_transaction.vehicle.last_known_soc_percent is not None:
            latest_soc = round(float(latest_transaction.vehicle.last_known_soc_percent), 2)

        latest_actual_power_kw = None
        if latest_meter and latest_meter.power_w is not None:
            latest_actual_power_kw = round(float(latest_meter.power_w) / 1000, 2)

        latest_session_snapshot = {
            'vehicle_soc': latest_soc,
            'requested_power_display': _build_requested_power_label(latest_transaction),
            'requested_power_mode_label': latest_transaction.get_requested_power_mode_display(),
            'actual_power_display': _format_power_value(latest_actual_power_kw),
            'ems_limit_display': _format_power_value(latest_transaction.last_applied_ems_limit_kw),
        }

    for station in stations_list:
        transaction = latest_tx_by_station.get(station.id)
        latest_meter = latest_meter_by_tx.get(transaction.id) if transaction else None

        station.vehicle_soc = None
        station.requested_power_label = '--'
        station.requested_power_mode = '--'
        station.actual_power_kw = None
        station.ems_limit_kw = None

        if transaction:
            if latest_meter and latest_meter.soc_percentage is not None:
                station.vehicle_soc = round(float(latest_meter.soc_percentage), 2)
            elif transaction.vehicle and transaction.vehicle.last_known_soc_percent is not None:
                station.vehicle_soc = round(float(transaction.vehicle.last_known_soc_percent), 2)

            if latest_meter and latest_meter.power_w is not None:
                station.actual_power_kw = round(float(latest_meter.power_w) / 1000, 2)

            station.requested_power_label = _build_requested_power_label(transaction)
            station.requested_power_mode = transaction.get_requested_power_mode_display()
            station.ems_limit_kw = float(transaction.last_applied_ems_limit_kw) if transaction.last_applied_ems_limit_kw is not None else None

    return latest_session_snapshot


def _build_station_stats(stations_list, latest_session_snapshot):
    from .consumers import ACTIVE_STATIONS
    from django.db.models import Sum
    from django.utils import timezone

    total_stations = len(stations_list)
    online_stations = sum(
        1 for station in stations_list if station.id in ACTIVE_STATIONS or str(station.id) in ACTIVE_STATIONS
    )
    active_sessions = Transaction.objects.filter(status='active').count()

    today = timezone.now().date()
    today_transactions = Transaction.objects.filter(
        started_at__date=today,
        meter_stop__isnull=False,
    )
    energy_today_wh = today_transactions.aggregate(total=Sum('meter_stop') - Sum('meter_start'))['total'] or 0
    return {
        'total_stations': total_stations,
        'online_stations': online_stations,
        'active_sessions': active_sessions,
        'energy_today_kwh': round(energy_today_wh / 1000, 1),
        'vehicle_soc': latest_session_snapshot['vehicle_soc'],
        'requested_power_display': latest_session_snapshot['requested_power_display'],
        'requested_power_mode_label': latest_session_snapshot['requested_power_mode_label'],
        'actual_power_display': latest_session_snapshot['actual_power_display'],
        'ems_limit_display': latest_session_snapshot['ems_limit_display'],
    }

def stations(request: HttpRequest) -> HttpResponse:
    """Operational charging stations view; CRUD is handled via Django admin."""
    stations_list = list(Station.objects.prefetch_related('connectors'))

    latest_session_snapshot = _attach_station_live_power_state(stations_list)
    stats = _build_station_stats(stations_list, latest_session_snapshot)

    if request.method == "POST":
        if "action" in request.POST:
            station_ids = request.POST.getlist("station_ids")
            action = request.POST.get("action")
            power = request.POST.get("power")
            is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

            if not station_ids:
                message = "No station selected."
                if is_ajax:
                    return JsonResponse({'success': False, 'message': message})
                messages.error(request, message)
                return redirect(request.path)

            success_count, error_count, message = execute_station_action(
                action=action,
                station_ids=station_ids,
                power=power,
            )
            overall_success = success_count > 0 and error_count == 0
            
            if is_ajax:
                return JsonResponse({
                    'success': overall_success,
                    'message': message,
                    'success_count': success_count,
                    'error_count': error_count
                })
            
            # Non-AJAX response
            if overall_success:
                messages.success(request, message)
            elif success_count > 0:
                messages.warning(request, message)
            else:
                messages.error(request, message)

            return redirect(request.path)

        messages.info(request, 'Use the Add/ Edit Station button to manage stations in Django admin.')
        return redirect('admin:charging_stations_station_changelist')

    return render(
        request,
        "charging_stations/stations.html",
        {
            "stations_list": stations_list,
            "stats": stats,
        }
    )



def _bucket_timestamp(timestamp, minutes=15):
    bucket_minute = (timestamp.minute // minutes) * minutes
    return timestamp.replace(minute=bucket_minute, second=0, microsecond=0)


def _statistics_csv_response(filename, header, rows):
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    writer = csv.writer(response)
    writer.writerow(header)
    for row in rows:
        writer.writerow(row)
    return response


def _build_querystring(params, exclude=None):
    exclude = set(exclude or [])
    cleaned = {
        key: value
        for key, value in params.items()
        if key not in exclude and value not in (None, '')
    }
    return urlencode(cleaned)


def _resolve_statistics_window(request: HttpRequest):
    timerange = request.GET.get('timerange', '24h')
    selected_date = request.GET.get('date', '').strip()
    now = timezone.now()

    if timerange == 'week':
        start = now - timedelta(days=7)
        end = now
        bucket_minutes = 180
        label_format = '%m-%d %H:%M'
        label = 'Last week'
    elif timerange == 'month':
        start = now - timedelta(days=30)
        end = now
        bucket_minutes = 720
        label_format = '%m-%d'
        label = 'Last month'
    elif timerange == 'date' and selected_date:
        try:
            target_date = datetime.strptime(selected_date, '%Y-%m-%d').date()
        except ValueError:
            timerange = '24h'
            selected_date = ''
            start = now - timedelta(hours=24)
            end = now
            bucket_minutes = 15
            label_format = '%H:%M'
            label = 'Last 24 hours'
        else:
            start = timezone.make_aware(datetime.combine(target_date, time.min))
            end = start + timedelta(days=1)
            bucket_minutes = 15
            label_format = '%H:%M'
            label = target_date.strftime('%Y-%m-%d')
    else:
        timerange = '24h'
        selected_date = ''
        start = now - timedelta(hours=24)
        end = now
        bucket_minutes = 15
        label_format = '%H:%M'
        label = 'Last 24 hours'

    return {
        'timerange': timerange,
        'selected_date': selected_date,
        'start': start,
        'end': end,
        'bucket_minutes': bucket_minutes,
        'label_format': label_format,
        'label': label,
        'show_date_input': timerange == 'date',
        'choices': STATISTICS_RANGE_CHOICES,
    }


def _safe_energy_value(meter_value):
    if meter_value.energy_wh is not None:
        return meter_value.energy_wh
    return meter_value.value


def _format_duration_compact(total_seconds):
    if not total_seconds:
        return "0m"

    total_minutes = int(total_seconds // 60)
    days, rem_minutes = divmod(total_minutes, 1440)
    hours, minutes = divmod(rem_minutes, 60)

    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes or not parts:
        parts.append(f"{minutes}m")
    return " ".join(parts)


def _extract_measurand(payload, measurands):
    for meter_entry in payload or []:
        for sampled_value in meter_entry.get('sampled_value') or []:
            if sampled_value.get('measurand') in measurands:
                return sampled_value.get('value'), sampled_value.get('unit')
    return None, None


def _format_measurement(value, unit, decimals=2):
    if value in (None, ""):
        return "--"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)

    rendered = f"{number:.{decimals}f}"
    if unit:
        return f"{rendered} {unit}"
    return rendered


def _build_power_energy_timeline(meter_values, bucket_minutes=15, label_format='%H:%M'):
    bucketed_by_time = defaultdict(dict)
    for meter_value in meter_values:
        bucket = _bucket_timestamp(timezone.localtime(meter_value.timestamp), minutes=bucket_minutes)
        bucketed_by_time[bucket][meter_value.transaction_id] = meter_value

    last_energy_by_transaction = {}
    labels = []
    total_power_kw = []
    energy_delta_kwh = []
    rows = []

    for bucket in sorted(bucketed_by_time.keys()):
        bucket_power_w = 0
        bucket_energy_wh = 0

        for transaction_id, meter_value in bucketed_by_time[bucket].items():
            if meter_value.power_w is not None:
                bucket_power_w += meter_value.power_w

            current_energy = _safe_energy_value(meter_value)
            previous_energy = last_energy_by_transaction.get(transaction_id)
            if current_energy is not None:
                if previous_energy is not None:
                    bucket_energy_wh += max(current_energy - previous_energy, 0)
                last_energy_by_transaction[transaction_id] = current_energy

        bucket_label = bucket.strftime(label_format)
        total_power_value = round(bucket_power_w / 1000, 2)
        energy_delta_value = round(bucket_energy_wh / 1000, 3)
        labels.append(bucket_label)
        total_power_kw.append(total_power_value)
        energy_delta_kwh.append(energy_delta_value)
        rows.append({
            'bucket_start': bucket,
            'label': bucket_label,
            'total_power_kw': total_power_value,
            'energy_delta_kwh': energy_delta_value,
        })

    return {
        'labels': labels,
        'total_power_kw': total_power_kw,
        'energy_delta_kwh': energy_delta_kwh,
        'rows': rows,
        'peak_load_kw': round(max(total_power_kw), 2) if total_power_kw else 0,
        'average_load_kw': round(
            sum(total_power_kw) / len([value for value in total_power_kw if value is not None]) if total_power_kw else 0,
            2,
        ),
    }


def _build_timeline_preview(rows):
    preview_rows = rows[-12:]
    max_power = max((row['total_power_kw'] for row in preview_rows), default=0)
    max_energy = max((row['energy_delta_kwh'] for row in preview_rows), default=0)

    rendered = []
    for row in preview_rows:
        rendered.append({
            'label': row['label'],
            'total_power_kw': row['total_power_kw'],
            'energy_delta_kwh': row['energy_delta_kwh'],
            'power_pct': round((row['total_power_kw'] / max_power) * 100, 1) if max_power else 0,
            'energy_pct': round((row['energy_delta_kwh'] / max_energy) * 100, 1) if max_energy else 0,
        })
    return rendered


def _build_session_analytics(transactions):
    duration_bins = [
        ('0-1 min', 0, 1),
        ('1-5 min', 1, 5),
        ('5-15 min', 5, 15),
        ('15-30 min', 15, 30),
        ('30+ min', 30, None),
    ]
    duration_counts = {label: 0 for label, _, _ in duration_bins}
    energy_points = []
    session_rows = []

    for transaction in transactions:
        if not transaction.started_at or not transaction.stopped_at:
            continue

        duration_minutes = max((transaction.stopped_at - transaction.started_at).total_seconds() / 60, 0)
        for label, minimum, maximum in duration_bins:
            if maximum is None and duration_minutes >= minimum:
                duration_counts[label] += 1
                break
            if minimum <= duration_minutes < maximum:
                duration_counts[label] += 1
                break

        if transaction.energy_consumed is not None:
            energy_points.append({
                'label': f"S{transaction.connector.station_id} · {timezone.localtime(transaction.started_at).strftime('%m/%d %H:%M')}",
                'value_kwh': round(float(transaction.energy_consumed), 2),
            })

        session_rows.append({
            'station_label': transaction.connector.station.formatted_serial(),
            'status': transaction.status,
            'started_at': timezone.localtime(transaction.started_at),
            'stopped_at': timezone.localtime(transaction.stopped_at),
            'duration_minutes': round(duration_minutes, 2),
            'energy_kwh': round(float(transaction.energy_consumed or 0), 2),
        })

    energy_points = list(reversed(energy_points[:12]))

    duration_max = max(duration_counts.values(), default=0)
    duration_chart_rows = [
        {
            'label': label,
            'count': duration_counts[label],
            'pct': round((duration_counts[label] / duration_max) * 100, 1) if duration_max else 0,
        }
        for label, _, _ in duration_bins
    ]
    energy_max = max((point['value_kwh'] for point in energy_points), default=0)
    energy_chart_rows = [
        {
            'label': point['label'],
            'value_kwh': point['value_kwh'],
            'pct': round((point['value_kwh'] / energy_max) * 100, 1) if energy_max else 0,
        }
        for point in energy_points
    ]

    return {
        'duration_labels': [label for label, _, _ in duration_bins],
        'duration_counts': [duration_counts[label] for label, _, _ in duration_bins],
        'energy_labels': [point['label'] for point in energy_points],
        'energy_values_kwh': [point['value_kwh'] for point in energy_points],
        'session_rows': session_rows,
        'duration_chart_rows': duration_chart_rows,
        'energy_chart_rows': energy_chart_rows,
    }


def _compute_non_active_seconds(history_entries, window_start, window_end):
    current_status = None
    cursor = window_start
    offline_seconds = 0

    for entry in history_entries:
        if entry.observed_at <= window_start:
            current_status = entry.status
            continue
        if current_status is None:
            current_status = entry.status
            cursor = entry.observed_at
            continue
        if current_status != 'active':
            offline_seconds += max((entry.observed_at - cursor).total_seconds(), 0)
        cursor = entry.observed_at
        current_status = entry.status

    if current_status is None:
        return None
    if current_status != 'active':
        offline_seconds += max((window_end - cursor).total_seconds(), 0)
    return int(offline_seconds)


def _build_charger_utilization(stations, transactions, meter_values, status_history, window_start, window_end):
    transactions_by_station = defaultdict(list)
    for transaction in transactions:
        transactions_by_station[transaction.connector.station_id].append(transaction)

    power_samples_by_station = defaultdict(list)
    for meter_value in meter_values:
        if meter_value.power_w is not None:
            power_samples_by_station[meter_value.transaction.connector.station_id].append(meter_value.power_w)

    history_by_station = defaultdict(list)
    for entry in status_history:
        history_by_station[entry.station_id].append(entry)

    rows = []
    for station in stations:
        station_transactions = transactions_by_station.get(station.id, [])
        total_active_seconds = 0
        for transaction in station_transactions:
            if transaction.started_at and transaction.stopped_at:
                total_active_seconds += max((transaction.stopped_at - transaction.started_at).total_seconds(), 0)

        power_samples = power_samples_by_station.get(station.id, [])
        avg_power_kw = round((sum(power_samples) / len(power_samples)) / 1000, 2) if power_samples else 0
        peak_power_kw = round(max(power_samples) / 1000, 2) if power_samples else 0
        offline_seconds = _compute_non_active_seconds(history_by_station.get(station.id, []), window_start, window_end)

        rows.append({
            'station_label': station.formatted_serial(),
            'station_address': station.short_address(),
            'sessions': len(station_transactions),
            'avg_power_kw': avg_power_kw,
            'peak_power_kw': peak_power_kw,
            'active_time_display': _format_duration_compact(total_active_seconds),
            'active_seconds': total_active_seconds,
            'offline_time_display': _format_duration_compact(offline_seconds) if offline_seconds is not None else '--',
            'offline_seconds': offline_seconds,
            'last_seen_display': timezone.localtime(station.last_seen).strftime('%Y-%m-%d %H:%M') if station.last_seen else '--',
        })

    max_active_seconds = max((row['active_seconds'] for row in rows), default=0)
    for row in rows:
        row['utilization_pct'] = round((row['active_seconds'] / max_active_seconds) * 100, 1) if max_active_seconds else 0

    return sorted(rows, key=lambda row: (-row['active_seconds'], -row['peak_power_kw'], row['station_label']))


def _build_meter_explorer_page(page_obj):
    explorer_rows = []
    for meter_value in page_obj.object_list:
        payload = meter_value.data.get('raw_payload', []) if isinstance(meter_value.data, dict) else []
        session_context = meter_value.data.get('session_context', {}) if isinstance(meter_value.data, dict) else {}
        current_value, current_unit = _extract_measurand(payload, {'Current.Import', 'Current.Offered'})
        voltage_value, voltage_unit = _extract_measurand(payload, {'Voltage'})

        explorer_rows.append({
            'id': meter_value.id,
            'timestamp': timezone.localtime(meter_value.timestamp),
            'timestamp_display': timezone.localtime(meter_value.timestamp).strftime('%Y-%m-%d %H:%M:%S'),
            'station_label': meter_value.transaction.connector.station.formatted_serial(),
            'station_address': meter_value.transaction.connector.station.short_address(),
            'power_display': _format_measurement(
                meter_value.power_w / 1000 if meter_value.power_w is not None else None,
                'kW',
            ),
            'current_display': _format_measurement(current_value, current_unit or 'A'),
            'voltage_display': _format_measurement(voltage_value, voltage_unit or 'V'),
            'energy_display': _format_measurement(
                (_safe_energy_value(meter_value) / 1000) if _safe_energy_value(meter_value) is not None else None,
                'kWh',
                decimals=3,
            ),
            'soc_display': f"{float(meter_value.soc_percentage):.2f} %" if meter_value.soc_percentage is not None else '--',
            'status': meter_value.transaction.status,
            'power_value_kw': round(meter_value.power_w / 1000, 2) if meter_value.power_w is not None else '',
            'current_value': current_value or '',
            'voltage_value': voltage_value or '',
            'energy_value_kwh': round((_safe_energy_value(meter_value) / 1000), 3) if _safe_energy_value(meter_value) is not None else '',
            'soc_value': round(float(meter_value.soc_percentage), 2) if meter_value.soc_percentage is not None else '',
            'raw_payload_pretty': json.dumps(payload, indent=2, ensure_ascii=True, default=str),
            'session_context_pretty': json.dumps(session_context, indent=2, ensure_ascii=True, default=str),
        })

    return explorer_rows


def _collect_statistics_data(request: HttpRequest, paginate: bool = True):
    range_filters = _resolve_statistics_window(request)
    stations = list(Station.objects.prefetch_related('connectors').order_by('id'))

    transactions_queryset = (
        Transaction.objects
        .select_related('connector__station')
        .filter(started_at__gte=range_filters['start'], started_at__lt=range_filters['end'])
        .order_by('-started_at')
    )
    completed_transactions = list(transactions_queryset.filter(stopped_at__isnull=False))
    timeline_meter_values = list(
        MeterValue.objects
        .select_related('transaction__connector__station')
        .filter(timestamp__gte=range_filters['start'], timestamp__lt=range_filters['end'])
        .order_by('timestamp', 'id')
    )
    utilization_meter_values = [meter_value for meter_value in timeline_meter_values if meter_value.power_w is not None]
    status_history = list(
        StationStatusHistory.objects
        .filter(observed_at__lt=range_filters['end'])
        .order_by('station_id', 'observed_at', 'id')
    )

    total_energy_wh = (
        transactions_queryset
        .filter(meter_stop__isnull=False)
        .aggregate(total=Sum(F('meter_stop') - F('meter_start')))
        .get('total')
        or 0
    )
    timeline = _build_power_energy_timeline(
        timeline_meter_values,
        bucket_minutes=range_filters['bucket_minutes'],
        label_format=range_filters['label_format'],
    )
    session_analytics = _build_session_analytics(completed_transactions)
    utilization_rows = _build_charger_utilization(
        stations,
        completed_transactions,
        utilization_meter_values,
        status_history,
        range_filters['start'],
        range_filters['end'],
    )

    station_filter = request.GET.get('station', '').strip()
    status_filter = request.GET.get('status', '').strip()
    explorer_queryset = (
        MeterValue.objects
        .select_related('transaction__connector__station')
        .filter(timestamp__gte=range_filters['start'], timestamp__lt=range_filters['end'])
        .order_by('-timestamp', '-id')
    )
    if station_filter:
        explorer_queryset = explorer_queryset.filter(transaction__connector__station__address__icontains=station_filter)
    if status_filter:
        explorer_queryset = explorer_queryset.filter(transaction__status=status_filter)

    if paginate:
        meter_page = Paginator(explorer_queryset, 10).get_page(request.GET.get('page', 1))
    else:
        meter_page = None

    meter_explorer_rows = _build_meter_explorer_page(meter_page) if paginate else _build_meter_explorer_page(type('Page', (), {'object_list': list(explorer_queryset)})())
    base_querystring = _build_querystring({
        'timerange': range_filters['timerange'],
        'date': range_filters['selected_date'],
        'station': station_filter,
        'status': status_filter,
    })

    return {
        'kpis': {
            'total_energy_kwh': round(total_energy_wh / 1000, 2),
            'avg_load_kw': timeline['average_load_kw'],
            'sessions': transactions_queryset.count(),
            'peak_load_kw': timeline['peak_load_kw'],
        },
        'timeline': timeline,
        'timeline_preview_rows': _build_timeline_preview(timeline['rows']),
        'session_analytics': session_analytics,
        'utilization_rows': utilization_rows,
        'meter_page': meter_page,
        'meter_explorer_rows': meter_explorer_rows,
        'explorer_filters': {
            'station': station_filter,
            'status': status_filter,
        },
        'range_filters': range_filters,
        'base_querystring': base_querystring,
    }


def statistics(request: HttpRequest) -> HttpResponse:
    """
    Historical telemetry view for charging analytics.
    Focuses on aggregated power, energy, session quality and compact meter exploration.
    """
    try:
        context = _collect_statistics_data(request, paginate=True)
        return render(request, "charging_stations/statistics.html", context)

    except Exception as e:
        context = {
            'kpis': {
                'total_energy_kwh': 0,
                'avg_load_kw': 0,
                'sessions': 0,
                'peak_load_kw': 0,
            },
            'timeline': {'labels': [], 'total_power_kw': [], 'energy_delta_kwh': []},
            'timeline_preview_rows': [],
            'session_analytics': {
                'duration_labels': [],
                'duration_counts': [],
                'energy_labels': [],
                'energy_values_kwh': [],
                'duration_chart_rows': [],
                'energy_chart_rows': [],
            },
            'utilization_rows': [],
            'meter_page': None,
            'meter_explorer_rows': [],
            'explorer_filters': {'station': '', 'status': ''},
            'range_filters': {
                'timerange': '24h',
                'selected_date': '',
                'label': 'Last 24 hours',
                'show_date_input': False,
                'choices': STATISTICS_RANGE_CHOICES,
            },
            'base_querystring': '',
            'error_message': f"Unable to load statistics: {str(e)}",
        }
        return render(request, "charging_stations/statistics.html", context)


def statistics_export(request: HttpRequest, export_kind: str) -> HttpResponse:
    dataset = _collect_statistics_data(request, paginate=False)

    if export_kind == 'timeline':
        rows = [
            [
                row['bucket_start'].strftime('%Y-%m-%d %H:%M:%S'),
                row['total_power_kw'],
                row['energy_delta_kwh'],
            ]
            for row in dataset['timeline']['rows']
        ]
        return _statistics_csv_response(
            'statistics_timeline.csv',
            ['Bucket Start', 'Total Charging Power (kW)', 'Delivered Energy Delta (kWh)'],
            rows,
        )

    if export_kind == 'sessions':
        rows = [
            [
                row['station_label'],
                row['status'],
                row['started_at'].strftime('%Y-%m-%d %H:%M:%S'),
                row['stopped_at'].strftime('%Y-%m-%d %H:%M:%S'),
                row['duration_minutes'],
                row['energy_kwh'],
            ]
            for row in dataset['session_analytics']['session_rows']
        ]
        return _statistics_csv_response(
            'statistics_sessions.csv',
            ['Charger', 'Status', 'Started At', 'Stopped At', 'Duration (min)', 'Energy (kWh)'],
            rows,
        )

    if export_kind == 'utilization':
        rows = [
            [
                row['station_label'],
                row['station_address'],
                row['sessions'],
                row['avg_power_kw'],
                row['peak_power_kw'],
                row['active_seconds'],
                row['offline_seconds'] if row['offline_seconds'] is not None else '',
                row['last_seen_display'],
            ]
            for row in dataset['utilization_rows']
        ]
        return _statistics_csv_response(
            'statistics_utilization.csv',
            ['Charger', 'Address', 'Sessions', 'Avg Power (kW)', 'Peak Power (kW)', 'Active Time (s)', 'Offline Time (s)', 'Last Seen'],
            rows,
        )

    if export_kind == 'meter-values':
        rows = [
            [
                row['timestamp'].strftime('%Y-%m-%d %H:%M:%S'),
                row['station_label'],
                row['station_address'],
                row['status'],
                row['power_value_kw'],
                row['current_value'],
                row['voltage_value'],
                row['energy_value_kwh'],
                row['soc_value'],
                row['raw_payload_pretty'],
                row['session_context_pretty'],
            ]
            for row in dataset['meter_explorer_rows']
        ]
        return _statistics_csv_response(
            'statistics_meter_values.csv',
            ['Timestamp', 'Charger', 'Address', 'Session Status', 'Power (kW)', 'Current', 'Voltage', 'Energy (kWh)', 'SoC (%)', 'Raw Payload', 'Session Context'],
            rows,
        )

    return JsonResponse({'status': 'error', 'message': 'Unsupported export type'}, status=400)


def tables(request: HttpRequest) -> HttpResponse:
    return render(request, "charging_stations/tables.html")

def get_current_soc(request: HttpRequest, station_id: int) -> JsonResponse:
    return JsonResponse({"status": "error", "message": "Not implemented"}, status=501)

def get_soc_history(request: HttpRequest, station_id: int) -> JsonResponse:
    return JsonResponse({"status": "error", "message": "Not implemented"}, status=501)

def update_station_soc_config(request: HttpRequest, station_id: int) -> JsonResponse:
    return JsonResponse({"status": "error", "message": "Not implemented"}, status=501)
