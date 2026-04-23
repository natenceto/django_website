import re

with open('renew_website/apps/api/energy/views.py', 'r') as f:
    lines = f.readlines()

new_view = """
from renew_website.apps.api.energy.models import InverterReading
from renew_website.apps.api.weather.models import WeatherLog
from renew_website.apps.algorithm.conditions import SystemState
from renew_website.apps.algorithm.engine import DecisionEngine
from django.utils import timezone

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def charging_recommendation(request):
    \"\"\"
    Get intelligent EV charging recommendations based on REAL-TIME system state.
    Simulates 1 EV (11kW) and 2 EVs (22kW).
    \"\"\"
    try:
        # 1. Gather Real-Time Environment Constraints
        latest_reading = InverterReading.objects.order_by('-timestamp').first()
        latest_weather = WeatherLog.objects.order_by('-timestamp').first()
        
        pv_power_kw = (latest_reading.generation_power or 0) / 1000.0 if latest_reading else 0.0
        battery_soc = float(latest_reading.battery_soc or 0) if latest_reading else 0.0
        
        station_data = latest_reading.station_data or {} if latest_reading else {}
        load_power_kw = station_data.get('load_power', 0) / 1000.0
        grid_voltage = station_data.get('grid_voltage', 230.0)
        is_grid_available = bool(grid_voltage > 190.0)

        cloud_cover = float(latest_weather.cloud_cover) if latest_weather else 0.0
        precipitation = float(latest_weather.precipitation_mm) if latest_weather else 0.0
        is_raining = precipitation > 0
        
        current_hour = timezone.localtime().hour
        is_night_tariff = (current_hour >= 22 or current_hour < 6)

        # Base State without active sessions
        base_state = {
            'battery_soc': battery_soc,
            'is_grid_available': is_grid_available,
            'pv_production_kw': pv_power_kw,
            'building_load_kw': load_power_kw,
            'cloud_cover_percent': cloud_cover,
            'is_raining': is_raining,
            'weather_condition': 'rain' if is_raining else 'clear',
            'is_night_tariff': is_night_tariff
        }
        
        # Scenario 1: One Car (11kW demand)
        state_1_ev = SystemState(**base_state, active_ev_sessions=1, total_ev_demand_kw=11.0)
        decision_1_ev = DecisionEngine.evaluate(state_1_ev)
        
        # Scenario 2: Two Cars (22kW demand)
        state_2_ev = SystemState(**base_state, active_ev_sessions=2, total_ev_demand_kw=22.0)
        decision_2_ev = DecisionEngine.evaluate(state_2_ev)

        # Build the final human-readable rationale
        context_str = f"Времето е {'дъждовно / облачно' if is_raining or cloud_cover > 50 else 'слънчево'}, PV Генерира: {pv_power_kw:.1f}kW, Батерия: {battery_soc}%."
        
        # Rationale for 1 EV
        power_1_ev = decision_1_ev.get('ev_power_limit_kw', 0)
        if power_1_ev >= 11:
            adv_1 = "Идеални условия. Можете да зареждате 1 автомобил на пълна мощност (11kW)."
        elif power_1_ev > 0:
            adv_1 = f"Ограничен капацитет. Зареждането ще бъде лимитирано до {power_1_ev:.1f}kW за предотвратяване на претоварване."
        else:
            adv_1 = "Не се препоръчва зареждане в момента (недостатъчна мощност/батерия)."
            
        # Rationale for 2 EVs
        power_2_ev = decision_2_ev.get('ev_power_limit_kw', 0)
        if power_2_ev >= 22:
            adv_2 = "Отлични условия. 2 автомобила могат да зареждат на пълна мощност (11kW + 11kW)."
        elif power_2_ev > 0:
            per_car = power_2_ev / 2
            adv_2 = f"Мощността ще бъде балансирана: {per_car:.1f}kW на автомобил (Общо отпуснати {power_2_ev:.1f}kW)."
        else:
            adv_2 = "Системата ще спре зареждането и на двата автомобила към този момент."

        response_data = {
            'context': context_str,
            'system_metrics': base_state,
            'scenario_1_ev': {
                'recommended_mode': decision_1_ev.get('mode'),
                'allowed_power_kw': power_1_ev,
                'advice': adv_1
            },
            'scenario_2_ev': {
                'recommended_mode': decision_2_ev.get('mode'),
                'allowed_power_kw': power_2_ev,
                'advice': adv_2
            }
        }
        
        return Response(response_data)
        
    except Exception as e:
        logger.error(f"Failed to get dynamic charging recommendation: {e}")
        return Response({"error": str(e)}, status=500)
"""

start_idx = -1
end_idx = -1

for i, line in enumerate(lines):
    if line.startswith('def charging_recommendation(') or line.startswith('@api_view([\''):
        if 'def charging_recommendation' in "".join(lines[i:i+3]):
            # Found the old block
            for j in range(i-2, -1, -1):
                if '@api_view' in lines[j] or '@permission_classes' in lines[j]:
                    start_idx = j
                else:
                    break
            
            # Find end of the function
            for j in range(i+1, len(lines)):
                if lines[j].startswith('@api_view') or lines[j].startswith('def '):
                    end_idx = j
                    break
            break

if start_idx != -1 and end_idx != -1:
    new_content = "".join(lines[:start_idx]) + new_view + "\n" + "".join(lines[end_idx:])
    with open('renew_website/apps/api/energy/views.py', 'w') as f:
        f.write(new_content)
    print("Patched charging_recommendation successfully.")
else:
    print("Could not locate block automatically! Please review.")
