import logging
from datetime import datetime
from django.utils import timezone
from celery import shared_task

from renew_website.apps.api.energy.models import InverterReading
from renew_website.apps.api.weather.models import WeatherLog
from renew_website.apps.charging_stations.models import Station, Transaction

# Импорт за логиката на новия алгоритъм
from renew_website.apps.algorithm.conditions import SystemState
from renew_website.apps.algorithm.engine import DecisionEngine
from renew_website.apps.api.energy.models import EnergyRecommendation

logger = logging.getLogger(__name__)

# -- КОНСТАНТИ ПО АЛГОРИТЪМА --
MAX_POWER_PER_STATION = 22000 # 22kW максимално зареждане
MIN_SAFE_CHARGE_POWER = 1380  # 6A * 230V (Минимум стандарт за AC зареждане)


@shared_task
def run_energy_management_algorithm():
    """
    "Мозъкът" на системата (EDA Event processor).
    Събира информация от всички датчици (Инвертор, Време, Станции)
    и взима решение как да разпредели мощността.
    """
    logger.info("Стартиране на Energy Management алгоритъма чрез DecisionEngine...")
    try:
        # 1. Вземане на последното състояние на инвертора
        latest_reading = InverterReading.objects.order_by('-timestamp').first()
        if not latest_reading:
            logger.warning("Няма данни от инвертора. Алгоритъмът спира.")
            return

        pv_power_kw = (latest_reading.generation_power or 0) / 1000.0  # W към kW
        battery_soc = float(latest_reading.battery_soc or 0)
        station_data = latest_reading.station_data or {}
        
        load_power_kw = station_data.get('load_power', 0) / 1000.0
        grid_voltage = station_data.get('grid_voltage', 230.0)
        is_grid_available = bool(grid_voltage > 190.0)

        # 2. Вземане на прогнозата за времето
        latest_weather = WeatherLog.objects.order_by('-timestamp').first()
        cloud_cover = float(latest_weather.cloud_cover) if latest_weather else 0.0
        is_raining = False
        weather_cond = "clear" # DUMMY condition, since it was removed
        precipitation = float(latest_weather.precipitation_mm) if latest_weather else 0.0
        if precipitation > 0:
            is_raining = True

        # Проверка за нощна тарифа (приблизително 22:00 до 06:00)
        current_hour = timezone.localtime().hour
        is_night_tariff = (current_hour >= 22 or current_hour < 6)

        # 3. Активни станции (всички активни сесии, не само автоматични)
        active_transactions = Transaction.objects.filter(
            stopped_at__isnull=True  # Всички активни сесии
        )
        
        active_count = active_transactions.count()
        total_ev_demand_kw = active_count * 11.0 # Пример: Очакваме, че всяка иска поне 11kW, ако може

        if active_count == 0:
            logger.debug("Няма активни зарядни авто-сесии.")
            return

        # 4. Формиране на текущия SystemState
        state = SystemState(
            battery_soc=battery_soc,
            is_grid_available=is_grid_available,
            pv_production_kw=pv_power_kw,
            building_load_kw=load_power_kw,
            active_ev_sessions=active_count,
            total_ev_demand_kw=total_ev_demand_kw,
            cloud_cover_percent=cloud_cover,
            is_raining=is_raining,
            weather_condition=weather_cond,
            is_night_tariff=is_night_tariff
        )

        # 5. Изчисление на лимитите с новия модул Algorithm Engine
        decision = DecisionEngine.evaluate(state)
        mode = decision.get("mode")
        total_ev_allowed_kw = decision.get("ev_power_limit_kw", 0.0)
        
        logger.info(f"Engine Decision: Mode={mode}, Allowed UV Total Power: {total_ev_allowed_kw:.2f}kW")

        # 6. Разпределяне на мощността
        power_per_station_kw = total_ev_allowed_kw / active_count
        
        # Ако алгоритъмът е пуснал малко мощност (подобно на капка), което е под минимума 6A, спираме.
        if power_per_station_kw > 0 and power_per_station_kw < (MIN_SAFE_CHARGE_POWER / 1000):
            power_per_station_kw = 0  # Спираме изцяло
            
        power_per_station_kw = min(power_per_station_kw, MAX_POWER_PER_STATION / 1000)

        # 7. Създаване на recommendation вместо автоматично изпълнение
        recommendation = EnergyRecommendation.objects.create(
            mode=str(mode),
            ev_power_limit_kw=total_ev_allowed_kw,
            power_per_station_kw=power_per_station_kw,
            battery_soc=battery_soc,
            pv_production_kw=pv_power_kw,
            building_load_kw=load_power_kw,
            active_ev_sessions=active_count,
            expires_at=timezone.now() + timezone.timedelta(minutes=15),  # Изтича след 15 минути
            algorithm_data={
                "decision": decision,
                "state": {
                    "is_grid_available": is_grid_available,
                    "cloud_cover_percent": cloud_cover,
                    "is_raining": is_raining,
                    "weather_condition": weather_cond,
                    "is_night_tariff": is_night_tariff
                }
            }
        )
        
        # Изчисти стари recommendations
        EnergyRecommendation.expire_old_recommendations()
        
        logger.info(f"Created recommendation {recommendation.id}: {mode} at {power_per_station_kw:.2f}kW per station")
        logger.info(f"Recommendation expires at: {recommendation.expires_at}")
            
    except Exception as e:
        logger.error(f"Грешка при изпълнение на Energy Management алгоритъма: {e}")
