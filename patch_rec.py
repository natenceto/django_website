import re
with open('renew_website/apps/api/energy/views.py', 'r') as f:
    content = f.read()

old_block = r"""@api_view\(\['POST'\]\)
@permission_classes\(\[IsAuthenticated\]\)
def charging_recommendation\(request\):.*?        return Response\(
            \{"error": f"Invalid data format: \{e\}"\},
            status=status\.HTTP_400_BAD_REQUEST
        \)"""

new_block = """@api_view(['GET'])
@permission_classes([IsAuthenticated])
def charging_recommendation(request):
    \"\"\"
    Get EV charging recommendation based on real-time conditions (mocked 1 and 2 EV scenarios).
    \"\"\"
    from django.utils import timezone
    from renew_website.apps.api.energy.models import InverterReading
    from renew_website.apps.api.weather.models import WeatherLog
    from renew_website.apps.algorithm.conditions import SystemState
    from renew_website.apps.algorithm.engine import DecisionEngine
    from renew_website.apps.algorithm.work_modes import SystemWorkMode

    try:
        latest_reading = InverterReading.objects.order_by('-timestamp').first()
        pv_power_kw = (latest_reading.generation_power or 0) / 1000.0 if latest_reading else 0.0
        battery_soc = float(latest_reading.battery_soc or 0) if latest_reading else 0.0
        station_data = latest_reading.station_data or {} if latest_reading else {}
        
        load_power_kw = station_data.get('load_power', 0) / 1000.0
        grid_voltage = station_data.get('grid_voltage', 230.0)
        is_grid_available = bool(grid_voltage > 190.0)

        latest_weather = WeatherLog.objects.order_by('-timestamp').first()
        cloud_cover = float(latest_weather.cloud_cover) if latest_weather else 0.0
        precipitation = float(latest_weather.precipitation_mm) if latest_weather else 0.0
        is_raining = precipitation > 0

        current_hour = timezone.localtime().hour
        is_night_tariff = (current_hour >= 22 or current_hour < 6)

        # Baseline common attributes
        base_kwargs = {
            'battery_soc': battery_soc,
            'is_grid_available': is_grid_available,
            'pv_production_kw': pv_power_kw,
            'building_load_kw': load_power_kw,
            'cloud_cover_percent': cloud_cover,
            'is_raining': is_raining,
            'weather_condition': 'clear',
            'is_night_tariff': is_night_tariff,
        }

        # Scenario 1: 1 EV (Demand = 11kW)
        state_1 = SystemState(
            active_ev_sessions=1,
            total_ev_demand_kw=11.0,
            **base_kwargs
        )
        decision_1 = DecisionEngine.evaluate(state_1)
        
        # Scenario 2: 2 EVs (Demand = 22kW)
        state_2 = SystemState(
            active_ev_sessions=2,
            total_ev_demand_kw=22.0,
            **base_kwargs
        )
        decision_2 = DecisionEngine.evaluate(state_2)

        def mode_to_str(m):
            if isinstance(m, SystemWorkMode):
                return m.name
            return str(m)

        def get_advice(power_allowed, target):
            if power_allowed >= target:
                return "Оптимално зареждане. Налична е достатъчно енергия."
            elif power_allowed > 0:
                return "Ограничено зареждане за предпазване на батерията."
            else:
                return "Липса на излишък. Зареждането ще бъде изчакване."

        info_context = (f"Текуща PV мощност: {pv_power_kw:.2f}kW, "
                        f"Консумация: {load_power_kw:.2f}kW, "
                        f"Батерия: {battery_soc:.1f}%")

        response_data = {
            "context": info_context,
            "scenario_1_ev": {
                "mode": mode_to_str(decision_1.get("mode")),
                "power_allowed": round(decision_1.get("ev_power_limit_kw", 0), 2),
                "advice": get_advice(decision_1.get("ev_power_limit_kw", 0), 11.0)
            },
            "scenario_2_ev": {
                "mode": mode_to_str(decision_2.get("mode")),
                "power_allowed": round(decision_2.get("ev_power_limit_kw", 0), 2),
                "advice": get_advice(decision_2.get("ev_power_limit_kw", 0), 22.0)
            }
        }
        
        return Response(response_data)
        
    except Exception as e:
        import traceback
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Charging recommendation error: {e}\\n{traceback.format_exc()}")
        return Response(
            {"error": f"Грешка при генериране на препоръка: {e}"},
            status=500
        )"""

content, count = re.subn(old_block, new_block, content, flags=re.DOTALL)
if count > 0:
    with open('renew_website/apps/api/energy/views.py', 'w') as f:
        f.write(content)
    print("Patched successfully")
else:
    print("Regex failed to match")
