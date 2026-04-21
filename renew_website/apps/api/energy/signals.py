import logging
from django.dispatch import receiver
from .models import Inverter, InverterReading

# Импортираме сигнала от deye/tasks.py
from renew_website.apps.api.deye.tasks import inverter_data_received

logger = logging.getLogger(__name__)

@receiver(inverter_data_received)
def save_inverter_reading(sender, data_dict, **kwargs):
    """
    Прихваща събитието за получени нови данни от инвертора (deye модула)
    и ги записва в таблицата InverterReading.
    """
    try:
        # Извличаме device_sn
        device_sn = data_dict.get('device_sn')
        if not device_sn:
            logger.warning("Пропуснато записване на InverterReading: Липсва device_sn")
            return

        # Намираме или създаваме инвертора в базата
        inverter, created = Inverter.objects.get_or_create(
            device_sn=device_sn,
            defaults={'name': f"Inverter {device_sn}"}
        )

        # Създаваме записа (телеметрията)
        InverterReading.objects.create(
            inverter=inverter,
            generation_power=data_dict.get('generation_power', 0),
            battery_soc=data_dict.get('battery_soc', 0),
            grid_power=data_dict.get('grid_power', 0),
            station_data=data_dict  # Запазваме целия суров/нормализиран речник за пълнота
        )
        
        logger.debug(f"Успешно записани данни за инвертор {device_sn} в базата.")
        
        # --- Извикваме Алгоритъма! ---
        from .tasks import run_energy_management_algorithm
        # Отлагаме го с 1-2 секунди, за да сме сигурни, че базата е commited
        run_energy_management_algorithm.apply_async(countdown=2)

    except Exception as e:
        logger.error(f"Грешка при записване на InverterReading от сигнал: {e}")
