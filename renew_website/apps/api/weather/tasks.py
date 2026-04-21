import logging
from celery import shared_task
from django.dispatch import Signal
from .services import WeatherService
from .components import WeatherConditionComponent

logger = logging.getLogger(__name__)

# ==========================================
# 1. СИГНАЛИ (Event Signals) към други модули
# ==========================================
# Излъчва се при успешно записване на нови данни за времето
weather_data_updated = Signal()  # args: [sender, weather_comp]


# ==========================================
# 2. ЗАДАЧИ ЗА СЪБИРАНЕ НА ДАННИ (Polling)
# ==========================================
@shared_task
def fetch_weather_task():
    """
    Периодична задача (изпълнява се на всеки 15 минути от Celery Beat).
    Извлича данните от Open-Meteo, създава Компонент и излъчва глобално събитие.
    """
    try:
        logger.info("Стартиране на задача за събиране на метеорологични данни.")
        svc = WeatherService()
        log = svc.store_weather_log()
        
        if log:
            logger.info(f"Метео данни успешно записани: {log.id} (Облачност: {log.cloud_cover}%, GHI: {log.irradiance_wm2} W/m2)")
            
            # Създаваме "умния" обект
            weather_comp = WeatherConditionComponent(
                cloud_cover_percentage=float(log.cloud_cover),
                is_raining=getattr(log, 'is_raining', False),  # ако има такова поле, иначе False
                forecast_solar_irradiation=float(log.irradiance_wm2)
            )

            # Изпращаме събитието към "Мозъка" (energy модула)
            weather_data_updated.send(sender="weather_telemetry", weather_comp=weather_comp)
            
            return f"Success: {log.id}"
        else:
            logger.warning("Неуспешно събиране на метеорологични данни (Service върна None).")
            return "Failed"
            
    except Exception as e:
        logger.error(f"Критична грешка в weather задачата за събиране: {e}")
        return f"Error: {e}"
