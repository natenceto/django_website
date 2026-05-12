import logging
from celery import shared_task
from django.dispatch import Signal
from django.utils import timezone

from renew_website.apps.api.deye.manager import DeyeManager, DeyeManagerError
from .components import DeyeInverterComponent, DeyeBatteryComponent

logger = logging.getLogger(__name__)

# ==========================================
# 1. СИГНАЛИ (Event Signals) към други модули
# ==========================================
# Излъчва се при успешно прочитане на данни
inverter_data_received = Signal()  # args: [sender, inverter_comp, battery_comp]

# Излъчва се, ако инверторът не отговаря дълго време
inverter_offline = Signal()        # args: [sender, error_msg]


# ==========================================
# 2. ЗАДАЧИ ЗА СЪБИРАНЕ НА ДАННИ (Polling)
# ==========================================
@shared_task
def fetch_inverter_telemetry():
    """
    Периодична задача (изпълнява се на всеки 1-5 минути от Celery Beat).
    Чете данните от инвертора, създава Компоненти и излъчва глобално събитие (`inverter_data_received`).
    Модулът `energy` ще слуша за това събитие.
    """
    try:
        manager = DeyeManager()
        data = manager.get_latest_data()
        
        if not data:
            logger.warning("Не бяха получени данни от инвертора.")
            inverter_offline.send(sender="deye_telemetry", error_msg="No data returned")
            return

        # Създаваме "умните" обекти (Компоненти)
        inverter_comp = DeyeInverterComponent(
            grid_voltage=data.get('grid_voltage', 230.0),
            pv_production_kw=data.get('generation_power', 0) / 1000.0,
            building_load_kw=data.get('load_power', 0) / 1000.0
        )

        battery_comp = DeyeBatteryComponent(
            soc_percentage=data.get('battery_soc', 0.0),
            temperature=data.get('battery_temperature', 20.0),
            power_kw=data.get('battery_power', 0) / 1000.0
        )

        # 1. Изпращаме събитието към цялата система
        inverter_data_received.send(
            sender="deye_telemetry", 
            inverter_comp=inverter_comp, 
            battery_comp=battery_comp,
            data_dict=data
        )

        logger.debug(f"Прочетени данни от Deye: PV={inverter_comp.pv_production_kw}kW, SOC={battery_comp.soc_percentage}%")
        
    except DeyeManagerError as e:
        logger.error(f"Грешка при комуникация с Deye: {e}")
        inverter_offline.send(sender="deye_telemetry", error_msg=str(e))
    except Exception as e:
        logger.error(f"Критична грешка в Deye задачата за събиране: {e}")


# ==========================================
# 3. ИЗПЪЛНИТЕЛНИ ЗАДАЧИ (Commands)
# ==========================================
@shared_task
def set_inverter_work_mode(mode_name):
    """
    Извиква се от 'energy' модула (алгоритъма) асинхронно, 
    когато алгоритъмът е взел решение за промяна на базов режим на инвертора.
    """
    try:
        manager = DeyeManager()
        success = manager.set_work_mode(mode_name)
        
        if success:
            logger.info(f"Базовият режим на инвертора успешно сменен на: {mode_name}")
        else:
            logger.warning(f"Неуспешен опит за смяна на базов режим на инвертора към: {mode_name}")
            
    except Exception as e:
        logger.error(f"Грешка при смяна на Deye режим ({mode_name}): {e}")

@shared_task
def apply_system_work_mode(system_mode_str):
    """
    Backwards-compatible wrapper for the older task name.
    The EMS layer now applies allocation constraints instead of treating strategy as an inverter mode.
    """
    try:
        allocation_plan = system_mode_str if isinstance(system_mode_str, dict) else {}
        from .control import build_modbus_commands_for_allocation
        commands = build_modbus_commands_for_allocation(allocation_plan)

        if not commands:
            logger.info("Няма поддържани Modbus constraint команди за текущия EMS план.")
            return
            
        manager = DeyeManager()
        success = manager.apply_modbus_commands(commands)
        
        if success:
            logger.info(f"Успешно приложени {len(commands)} Modbus constraint регистри за EMS плана")
        else:
            logger.warning("Грешка при прилагане на Modbus constraint регистри за EMS плана.")
            
    except Exception as e:
        logger.error(f"Критична грешка при прилагане на EMS allocation constraints: {e}")
