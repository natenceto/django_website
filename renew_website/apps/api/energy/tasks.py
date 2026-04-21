import logging
from celery import shared_task

from renew_website.apps.api.energy.models import InverterReading
from renew_website.apps.api.weather.models import WeatherLog
from renew_website.apps.charging_stations.models import Station, Transaction

# Импорт на изпълнителната задача към зарядните станции
from renew_website.apps.charging_stations.tasks import set_charging_power_limit

# Импорт за управление на инвертора (ако се наложи аварийна смяна на режим)
from renew_website.apps.api.deye.tasks import set_inverter_work_mode

logger = logging.getLogger(__name__)

# -- КОНСТАНТИ ПО АЛГОРИТЪМА --
MIN_BATTERY_SOC = 35.0       # Критичен минимум на батерията
TARGET_RESERVE_SOC = 50.0    # Резерв за през нощта или лошо време
MAX_POWER_PER_STATION = 22000 # 11kW максимално зареждане
MIN_SAFE_CHARGE_POWER = 1380  # 6A * 230V (Минимум стандарт за AC зареждане)


@shared_task
def run_energy_management_algorithm():
    """
    "Мозъкът" на системата (EDA Event processor).
    Събира информация от всички датчици (Инвертор, Време, Станции)
    и взима решение как да разпредели мощността.
    """
    logger.info("Стартиране на Energy Management алгоритъма...")
    try:
        # 1. Вземане на последното състояние на инвертора (PV мощност, Батерия, Товар)
        latest_reading = InverterReading.objects.order_by('-timestamp').first()
        if not latest_reading:
            logger.warning("Няма данни от инвертора. Алгоритъмът спира.")
            return

        pv_power = latest_reading.generation_power or 0
        battery_soc = latest_reading.battery_soc or 0
        station_data = latest_reading.station_data or {}
        
        # Общият товар на къщата/обекта
        load_power = station_data.get('load_power', 0)

        # 2. Вземане на прогнозата за времето (облачност)
        latest_weather = WeatherLog.objects.order_by('-timestamp').first()
        cloud_cover = latest_weather.cloud_cover if latest_weather else 0

        # 3. Вземане на текущите активни зарядни сесии
        active_transactions = Transaction.objects.filter(stopped_at__isnull=True)
        if not active_transactions.exists():
            logger.debug("Няма активни зарядни станции. PV излишъкът ще зарежда батерията.")
            return

        active_stations = Station.objects.filter(
            id__in=active_transactions.values_list('connector__station_id', flat=True)
        )

        # ==========================================
        # 4. ЛОГИКА ЗА ВЗИМАНЕ НА РЕШЕНИЯ (ALGORITHM)
        # ==========================================
        
        # СЦЕНАРИЙ А: Критично ниска батерия
        if battery_soc <= MIN_BATTERY_SOC:
            logger.warning(f"Критично ниска батерия ({battery_soc}%). Спираме EV зареждането (Изпращаме 0W)!")
            for station in active_stations:
                set_charging_power_limit.delay(station.id, 0)
            return

        # СЦЕНАРИЙ Б: Лошо време очаквано и батерията не е заредена
        if cloud_cover > 80 and battery_soc < TARGET_RESERVE_SOC:
            logger.info(f"Лошо време ({cloud_cover}% облаци), батерията пада ({battery_soc}%). Режим ECO.")
            for station in active_stations:
                set_charging_power_limit.delay(station.id, MIN_SAFE_CHARGE_POWER)
            return

        # СЦЕНАРИЙ В: Добро слънце, излишък от PV мощност
        available_excess_power = pv_power - load_power
        if available_excess_power > MIN_SAFE_CHARGE_POWER:
            # Излишъкът се разпределя между станциите и батерията
            # (Батерията винаги се зарежда приоритетно от инвертора по default)
            power_per_station = int(available_excess_power / active_stations.count())
            power_per_station = min(power_per_station, MAX_POWER_PER_STATION) 
            
            logger.info(f"PV излишък: {available_excess_power}W. EV Станции: {power_per_station}W/всяка.")
            for station in active_stations:
                set_charging_power_limit.delay(station.id, power_per_station)
            return

        # СЦЕНАРИЙ Г: Балансиран режим (Няма слънце, но батерията е пълна)
        # Разрешаваме "зареждане по подразбиране" без да източваме мрежата умишлено
        default_power = MIN_SAFE_CHARGE_POWER * 2  # напр. към 3kW
        logger.info(f"Балансиран режим. EV Станции: {default_power}W/всяка.")
        for station in active_stations:
            set_charging_power_limit.delay(station.id, default_power)
            
    except Exception as e:
        logger.error(f"Грешка при изпълнение на Energy Management алгоритъма: {e}")
