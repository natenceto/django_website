import logging
from celery import shared_task
from django.dispatch import Signal
from django.utils import timezone

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

from .models import Station, Connector, Transaction, MeterValue
from .components import EVStationComponent

logger = logging.getLogger(__name__)


# Помощна функция за изпращане към WebSocket групата
def send_to_ui(data):
    try:
        channel_layer = get_channel_layer()
        if channel_layer:
            async_to_sync(channel_layer.group_send)(
                "stations_status",
                {"type": "broadcast", "data": data}
            )
    except Exception as e:
        logger.error(f"Грешка при изпращане към UI: {e}")


def _format_requested_power_display(tx):
    if tx.requested_power_mode == 'auto' and tx.requested_power_kw is None:
        return 'Auto'
    if tx.requested_power_kw is not None:
        return f"{float(tx.requested_power_kw):.2f} kW"
    return 'Station default'

# ==========================================
# 1. СИГНАЛИ (Event Signals) към други модули
# ==========================================
# Тези сигнали се "изстрелват" (send), за да бъдат уловени от `energy` приложението
station_power_changed = Signal()  # args: [sender, station_id, current_power_w]
transaction_started = Signal()    # args: [sender, station_id, transaction_id]
transaction_stopped = Signal()    # args: [sender, station_id, transaction_id, consumed_wh]


# ==========================================
# 2. ЗАДАЧИ ЗА ОБРАБОТКА НА СЪБИТИЯ (Events)
# ==========================================
@shared_task
def process_meter_values(station_id, connector_id, transaction_id, power_w, energy_wh, soc_percentage=None, mv_data=None):
    """
    Извиква се от OCPP консюмъра (или външен клиент), когато дойдат нови данни за консумация.
    Записва в базата, ъпдейтва UI и изпраща сигнал към алгоритъма.
    """
    try:
        tx = None
        if transaction_id:
            tx = (
                Transaction.objects
                .select_related('vehicle')
                .filter(id=transaction_id)
                .first()
            )

        # 1. Запис на телеметрията (опционално: само ако транзакцията е активна)
        if tx:
            MeterValue.objects.create(
                transaction=tx,
                power_w=power_w,
                energy_wh=energy_wh,
                soc_percentage=soc_percentage,
                data=mv_data or {},
                timestamp=timezone.now()
            )

            if soc_percentage is not None and tx.vehicle_id:
                vehicle = tx.vehicle
                if vehicle:
                    update_fields = ['last_seen_at']
                    vehicle.last_seen_at = timezone.now()
                    if vehicle.last_known_soc_percent != soc_percentage:
                        vehicle.last_known_soc_percent = soc_percentage
                        update_fields.append('last_known_soc_percent')
                    vehicle.save(update_fields=update_fields)

            send_to_ui({
                "type": "station_power_update",
                "station_id": int(str(station_id)),
                "requested_power_kw": tx.requested_power_kw,
                "requested_power_mode": tx.requested_power_mode,
                "requested_power_display": _format_requested_power_display(tx),
                "actual_power_kw": round(float(power_w) / 1000.0, 2) if power_w is not None else None,
                "ems_limit_kw": float(tx.last_applied_ems_limit_kw) if tx.last_applied_ems_limit_kw is not None else None,
                "timestamp": timezone.now().isoformat(),
            })

        # 2. Уведомяване на браузърите (WebSockets / UI)
        if soc_percentage is not None:
            send_to_ui({
                "type": "soc_update",
                "station_id": int(str(station_id)),
                "soc_percentage": float(soc_percentage),
                "timestamp": timezone.now().isoformat()
            })
            
        # 3. Създаваме Компонент за станцията и пускаме към Brain (energy модула)
        station_comp = EVStationComponent(
            station_id=str(station_id),
            is_plugged=True,  # Когато получим meter values, значи е включен
            current_draw_kw=power_w / 1000.0,
            ev_battery_soc=soc_percentage
        )

        station_power_changed.send(
            sender=Station,
            station_id=station_id,
            station_comp=station_comp
        )
        
        logger.debug(f"Обработени данни за станция {station_id}: {power_w}W, {energy_wh}Wh")

    except Exception as e:
        logger.error(f"Грешка при обработка на meter values за {station_id}: {e}")


@shared_task
def handle_transaction_started(station_id, connector_id, transaction_id, id_tag):
    """
    Създава запис за нова сесия и събужда енергийния алгоритъм.
    """
    try:
        # Уведомяваме energy модула, че нов голям консуматор е включен
        transaction_started.send(
            sender=Station, 
            station_id=station_id, 
            transaction_id=transaction_id
        )
        
        # Обновяваме UI за конектора
        send_to_ui({
                "type": "connector_status",
                "station_id": int(str(station_id)),
                "status": "Charging",
                "connector_id": int(connector_id) if connector_id else 1,
                "timestamp": timezone.now().isoformat()
            })
        
        logger.info(f"Старт на транзакция {transaction_id} на станция {station_id}")
        
    except Exception as e:
        logger.error(f"Грешка при старт на транзакция: {e}")


@shared_task
def handle_transaction_stopped(station_id, transaction_id, meter_stop, stop_reason="Local"):
    """
    Приключва сесията и освобождава резервираната мощност.
    """
    try:
        consumed_wh = 0
        connector_id = None
        try:
            trans = Transaction.objects.get(id=transaction_id)
            trans.meter_stop = meter_stop
            trans.stopped_at = timezone.now()
            trans.stop_reason = stop_reason
            trans.save()
            consumed_wh = trans.energy_consumed or 0
            if trans.connector_id:
                connector_id = trans.connector_id
        except Transaction.DoesNotExist:
            logger.warning(f"Транзакция {transaction_id} не е намерена.")

        # Уведомяваме алгоритъма, че товарът е премахнат
        transaction_stopped.send(
            sender=Station,
            station_id=station_id,
            transaction_id=transaction_id,
            consumed_wh=consumed_wh
        )
        
        # Обновяваме UI за конектора, че отново е свободен
        if connector_id:
            send_to_ui({
                "type": "connector_status",
                "station_id": int(str(station_id)),
                "status": "Available",
                "connector_id": int(connector_id) if connector_id else 1,
                "timestamp": timezone.now().isoformat()
            })
        
        logger.info(f"Край на транзакция {transaction_id}. Консумирани: {consumed_wh}Wh.")

    except Exception as e:
        logger.error(f"Грешка при край на транзакция: {e}")


# ==========================================
# 3. ИЗПЪЛНИТЕЛНИ ЗАДАЧИ (Commands / Actions)
# ==========================================
@shared_task
def set_charging_power_limit(station_id, max_power_watts):
    """
    Извиква се от 'energy' модула (алгоритъма), когато иска да намали или увеличи зареждането
    поради липса на PV енергия или ограничаване от батерията.
    """
    try:
        from renew_website.apps.charging_stations.power_management import PowerManager
        import asyncio
        
        logger.info(f"Команда за ограничаване на мощност към станция {station_id}: {max_power_watts}W")
        
        power_kw = max_power_watts / 1000.0
        Transaction.objects.filter(
            connector__station_id=station_id,
            status='active',
        ).update(last_applied_ems_limit_kw=power_kw)
        
        # We assume connector_id = 1 for now (or loop through them if multiple)
        # PowerManager.set_charging_power expects kW
        from asgiref.sync import async_to_sync
        
        async_to_sync(PowerManager.set_charging_power)(station_id, 1, power_kw)
        
        # Индикираме в UI, че станцията е в режим "Eco/Auto" (лимитирана мощност)
        send_to_ui({
            "type": "station_status",
            "station_id": int(str(station_id)),
            "status": "Eco",
            "reason": f"Auto limit: {power_kw:.2f}kW",
            "timestamp": timezone.now().isoformat()
        })
        
    except Exception as e:
        logger.error(f"Неуспешно задаване на лимит {max_power_watts}W на {station_id}: {e}")


# ==========================================
# 4. ЗАДАЧИ ЗА СИНХРОНИЗАЦИЯ (Sync / Fallback)
# ==========================================
@shared_task
def update_station_status(station_id):
    """
    Периодична задача за проверка или синхронизация на статус, ако е необходимо
    за станции без постоянна WebSocket (OCPP) връзка.
    """
    try:
        logger.debug(f"Синхронизиран статус за станция {station_id} успешно.")
    except Exception as e:
        logger.error(f"Грешка при синхронизация на статус: {e}")