from django.conf import settings
from django.core.cache import cache
from .cloud_client import DeyeCloudClient
from .local_client import DeyeLocalClient
from .serializers import DeyeCloudSerializer, DeyeLocalSerializer
import logging
import socket

logger = logging.getLogger(__name__)

class DeyeManagerError(Exception):
    """Базова грешка за Deye Manager."""
    pass

# Карта за регистър 131 (Grid Work Mode)
LOCAL_MODE_MAP = {
    "selling_first": 2,
    "zero_export_to_load": 0,
    "zero_export_to_ct": 1,
    "battery_first": 3 
}

class DeyeManager:
    """
    Мениджър за хибридно управление на Deye инвертори.
    """
    def __init__(self):
        self.master_sn = getattr(settings, 'DEYE_MASTER_SN', None)
        self.logger_sn = getattr(settings, 'DEYE_LOGGER_SN', self.master_sn)
        self.connection_mode = getattr(settings, 'DEYE_CONNECTION_MODE', 'cloud').lower()
        self.local_ip = getattr(settings, 'DEYE_LOCAL_IP', None)
        
        self.cloud = DeyeCloudClient()
        self.local = None
        
        if self.connection_mode in ["local", "auto"] and self.local_ip and self.logger_sn:
            try:
                self.local = DeyeLocalClient(
                    ip_address=self.local_ip,
                    serial_number=int(self.logger_sn)
                )
            except Exception as e:
                logger.warning(f"DeyeLocalClient не можа да се зареди: {e}")

    def _is_local_available(self) -> bool:
        """Проверява сокета на логера (порт 8899)."""
        if not self.local or not self.local_ip:
            return False
            
        cache_key = f"deye_local_online_{self.local_ip}"
        is_online = cache.get(cache_key)
        
        if is_online is not None:
            return is_online

        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(1.0) 
                result = sock.connect_ex((self.local_ip, 8899))
                is_online = (result == 0)
                cache.set(cache_key, is_online, 60)
                return is_online
        except Exception:
            return False

    def get_active_inverter(self):
        """Определя кой метод за комуникация е активен."""
        if self.master_sn:
            # Използвай Cloud връзка за по-точни агрегирани данни
            if self.connection_mode in ["local", "auto"] and self._is_local_available():
                # Local връзката е налична, но Cloud дава по-точни данни
                return {
                    "device_sn": self.master_sn,
                    "source": "cloud",  # Принудително Cloud за точни данни
                    "ip": self.local_ip
                }
            return {"device_sn": self.master_sn, "source": "cloud"}

        master = self._find_master_via_cloud()
        if master:
            return {**master, "source": "cloud"}
        return None

    def get_latest_data(self, device_sn=None):
        """Връща нормализирани данни от най-добрия наличен източник."""
        active = self.get_active_inverter()
        if not active:
            raise DeyeManagerError("Няма наличен инвертор.")
            
        target_sn = device_sn or active["device_sn"]
        
        # Използвай Cloud връзка за по-точни агрегирани данни
        if active["source"] == "cloud":
            try:
                raw_response = self.cloud.get_device_latest(target_sn)
                data_obj = self._unwrap_cloud_response(raw_response)
                data_obj['device_sn'] = target_sn
                data_obj['source'] = 'cloud'
                return DeyeCloudSerializer(instance=data_obj).data
            except Exception as e:
                logger.warning(f"Cloud четене за {target_sn} пропадна: {e}. Fallback към Local.")
        
        # Fallback към локално четене
        if self.local and str(self.master_sn) == str(target_sn) and self._is_local_available():
            try:
                raw_data = self.local.fetch_all_metrics()
                if raw_data:
                    raw_data['device_sn'] = target_sn
                    raw_data['source'] = 'local'
                    return DeyeLocalSerializer(instance=raw_data).data
            except Exception as e:
                logger.warning(f"Локално четене за {target_sn} пропадна: {e}.")
        
        raise DeyeManagerError(f"Неуспешно четене на данни от {target_sn}")

    def set_work_mode(self, mode_key: str) -> bool:
        """Задава базов режим на работа чрез стар мапинг."""
        active = self.get_active_inverter()
        if not active: return False
        
        source = active["source"]
        sn = active["device_sn"]
        
        if source == "local" and self.local:
            reg_val = LOCAL_MODE_MAP.get(mode_key.lower().replace(" ", "_"))
            if reg_val is not None:
                return self.local.set_work_mode(reg_val)
        
        order = self.cloud.set_work_mode(device_sn=sn, mode=mode_key)
        return order.is_success
        
    def apply_modbus_commands(self, commands: dict) -> bool:
        """Директен запис на Modbus команди (dict of register: value). Предимно за Local."""
        if not commands:
            return True
            
        active = self.get_active_inverter()
        if not active: return False
        
        if active["source"] == "local" and self.local:
            return self.local.write_multiple_registers(commands)
        else:
            # TODO: Запис към Solarman Cloud за мнозинство регистри, ако е възможно през Cloud API.
            logger.warning(f"Apply modbus command {commands} not fully supported via Cloud yet.")
            return False

    def _unwrap_cloud_response(self, response):
        """Извлича чистия обект с данни от API отговора."""
        if not isinstance(response, dict): return {}
        for key in ["deviceDataList", "deviceList"]:
            if key in response and response[key]:
                return response[key][0]
            data_sec = response.get("data", {})
            if isinstance(data_sec, dict) and key in data_sec:
                if data_sec[key]: return data_sec[key][0]
        return response if "dataList" in response else {}

    def _find_master_via_cloud(self):
        """Търси инвертор в акаунта, ако няма заложен в settings."""
        try:
            stations = self.cloud.get_station_list(page=1, size=5)
            for st in stations:
                for dev in st.get("deviceListItems", []):
                    if dev.get("deviceType") == "INVERTER":
                        return {"device_sn": dev.get("deviceSn"), "station_id": st.get("id")}
        except: return None
        return None