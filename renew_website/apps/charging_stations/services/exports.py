import csv
from datetime import datetime, timedelta

from django.http import HttpResponse
from django.utils import timezone

from ..models import Transaction


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
            start_date = timezone.make_aware(datetime.combine(target_date, datetime.min.time()))
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
        duration_minutes = round(tx.duration_seconds / 60, 2) if tx.duration_seconds > 0 else ''
        peak_power = tx.requested_power_kw or "—"
        
        writer.writerow([
            tx.transaction_id or tx.id,
            tx.connector.station.address,
            tx.connector.connector_id,
            tx.id_tag,
            tx.started_at.strftime('%Y-%m-%d %H:%M:%S'),
            tx.stopped_at.strftime('%Y-%m-%d %H:%M:%S') if tx.stopped_at else '',
            duration_minutes,
            tx.formatted_energy,
            tx.avg_power_kw,
            peak_power,
            tx.session_result,
            tx.session_stop_reason
        ])
        
    return response