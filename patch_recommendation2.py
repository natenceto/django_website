import re

with open('renew_website/apps/api/energy/views.py', 'r') as f:
    code = f.read()

pattern = re.compile(r'@api_view\(\[\'POST\'\]\)\s+@permission_classes\(\[IsAuthenticated\]\)\s+def charging_recommendation\(request\):.*?except Exception as e:.*?return Response\(\s*\{"error": str\(e\)\},\s*status=status\.HTTP_503_SERVICE_UNAVAILABLE\s*\)', re.DOTALL)

# Let's check what decorators are around charging_recommendation
m = re.search(r'(@[^\n]+\n)*def charging_recommendation', code)
if m:
    pass

import sys

lines = code.split('\n')
start = -1
end = -1
for i, l in enumerate(lines):
    if 'def charging_recommendation' in l:
        start = i - 2 if '@api_view' in lines[i-2] else i
        # find the next @api_view
        for j in range(i+1, len(lines)):
            if lines[j].startswith('@api_view') or lines[j].startswith('def '):
                end = j
                break
        break

if start != -1 and end != -1:
    new_view = """@api_view(['GET'])
@permission_classes([IsAuthenticated])
def charging_recommendation(request):
    \"\"\"
    Get EV charging recommendations simulating the actual DecisionEngine based on real-time data (PV, Battery, Weather).
    \"\"\"
    from renew_website.apps.api.energy.models import InverterReading
    from renew_website.apps.api.weather.models import WeatherLog
    from renew_website.apps.algorithm.conditions import SystemState
    from renew_website.apps.algorithm.engine import DecisionEngine
    from django.utils import timezone

    try:
        # Gather Realtime Data
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

        cloudy_msg = "дъждовно" if is_raining else ("облачно" if cloud_cover > 50 else "слънчево")
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

        # Sub-scenario helpers
        def evaluate_scenario(num_evs, demand):
            st = SystemState(**base_state, active_ev_sessions=num_evs, total_ev_demand_kw=demand)
            decision = DecisionEngine.evaluate(st)
            power_allowed = decision.get("ev_power_limit_kw", 0)
            mode = decision.get("mode")

            if power_allowed >= demand:
                adv = f"Отлични условия за зареждане. Спрямо данни от панелите ({pv_power_kw:.1f}kW) и батерията ({battery_soc}%), алгоритъмът позволява пълна мощност на зареждане."
            elif power_allowed > 0:
                per_car = power_allowed / num_evs
                adv = f"Лимитирана мощност. За да се предпази батерията, алгоритъмът ограничава зареждането до {power_allowed:.1f}kW общо (или {per_car:.1f}kW на автомобил)."
            else:
                adv = f"В момента няма свободен зелен капацитет. Алгоритъмът спира зареждането, за да не натоварва мрежата / изтощава батерията ненужно."
            
            return {
                'mode': mode,
                'power_allowed': round(power_allowed, 1),
                'advice': adv
            }

        sc1 = evaluate_scenario(1, 11)
        sc2 = evaluate_scenario(2, 22)

        return Response({
            'context': f"Текущи условия: Времето е {cloudy_msg}. Фотоволтаиците генерират {pv_power_kw:.2f}kW, а батерията е на {battery_soc:.1f}%. Консумацията на сградата е {load_power_kw:.2f}kW.",
            'scenario_1_ev': sc1,
            'scenario_2_ev': sc2
        })

    except Exception as e:
        logger.error(f"Failed to get dynamic charging recommendation: {e}")
        return Response({"error": str(e)}, status=500)
"""
    new_lines = lines[:start] + [new_view] + lines[end:]
    with open('renew_website/apps/api/energy/views.py', 'w') as f:
        f.write('\n'.join(new_lines))
    print("Patched!")
else:
    print("Not found start/end", start, end)

