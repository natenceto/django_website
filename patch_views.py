import re
with open('renew_website/apps/api/energy/views.py', 'r') as f:
    text = f.read()

new_view = """
@api_view(['POST'])
def start_charging_session(request):
    \"""
    Starts a simulated charging session in the chosen mode (Auto/Manual).
    This tells the background algorithm that a car is connected and charging should be managed dynamically.
    \"""
    from renew_website.apps.charging_stations.models import Transaction, Connector
    
    mode = request.data.get('mode', 'DYNAMIC_ECO_SOLAR_ONLY')
    
    # Just take the first available connector to simulate
    connector = Connector.objects.first()
    if not connector:
        return Response({'success': False, 'message': 'Няма налични зарядни конектори в системата.'})
        
    # Check if a session already exists for this connector
    active_txn = Transaction.objects.filter(connector=connector, stopped_at__isnull=True).first()
    if active_txn:
        return Response({'success': False, 'message': 'Вече има активна зарядна сесия на този конектор.'})
        
    # Create the new dynamic session (requested_power_kw=None means "Auto Mode" for algorithm)
    Transaction.objects.create(
        connector=connector,
        id_tag='SIMULATED_DASHBOARD_USER',
        requested_power_kw=None,
        status='active'
    )
    
    return Response({
        'success': True, 
        'message': f'Успешно стартирано зареждане в режим: {mode}. Алгоритъмът вече управлява мощността динамично.'
    })
"""

# Append it
with open('renew_website/apps/api/energy/views.py', 'a') as f:
    f.write(new_view)

print("Appended start_charging_session to views.py")
