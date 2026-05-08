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
        self.master_logger_sn = getattr(settings, 'DEYE_MASTER_LOGGER_SN', self.master_sn)
        self.slave_sn = getattr(settings, 'DEYE_SLAVE_SN', None)
        self.slave_logger_sn = getattr(settings, 'DEYE_SLAVE_LOGGER_SN', self.slave_sn)
        self.master_local_ip = getattr(settings, 'DEYE_MASTER_LOCAL_IP', None)
        self.slave_local_ip = getattr(settings, 'DEYE_SLAVE_LOCAL_IP', None)
        self.connection_mode = getattr(settings, 'DEYE_CONNECTION_MODE', 'cloud').lower()
        
        # За съвместимост със стария код
        self.logger_sn = self.master_logger_sn
        self.local_ip = self.master_local_ip
        
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
        """Определя кой метод за комуникация е активен. Local > Cloud"""
        if self.master_sn:
            if self.connection_mode in ["local", "auto"] and self._is_local_available():
                # Предимство на локалната връзка!
                return {
                    "device_sn": self.master_sn,
                    "source": "local", 
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
        
        # Ако изрично сме избрали local (намираме се в локалната мрежа)
        if active["source"] == "local" and self.local:
            try:
                raw_data = self.local.fetch_all_metrics()
                if raw_data:
                    raw_data['device_sn'] = target_sn
                    raw_data['source'] = 'local'
                    return DeyeLocalSerializer(instance=raw_data).data
            except Exception as e:
                logger.warning(f"Локално четене за {target_sn} пропадна: {e}. Fallback към Cloud.")
                
        # По подразбиране или Fallback: Използвай Cloud
        try:
            raw_response = self.cloud.get_device_latest(target_sn)
            data_obj = self._unwrap_cloud_response(raw_response)
            data_obj['device_sn'] = target_sn
            data_obj['source'] = 'cloud'
            return DeyeCloudSerializer(instance=data_obj).data
        except Exception as e:
            logger.warning(f"Cloud четене за {target_sn} пропадна: {e}.")
            
        raise DeyeManagerError(f"Неуспешно четене на данни от {target_sn} (Нито Local, нито Cloud)")

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

    def get_slave_inverter_data(self):
        """Връща данни от slave инвертора, ако е наличен."""
        if not self.slave_sn or not self.slave_local_ip or not self.slave_logger_sn:
            return None
            
        try:
            # Проверка дали slave инверторът е достъпен
            if not self._is_slave_available():
                return None
                
            # Четене на данни от slave инвертора
            slave_client = DeyeLocalClient(
                ip_address=self.slave_local_ip,
                serial_number=int(self.slave_logger_sn)
            )
            
            raw_data = slave_client.fetch_all_metrics()
            if raw_data:
                raw_data['device_sn'] = self.slave_sn
                raw_data['source'] = 'local'
                raw_data['ip'] = self.slave_local_ip
                return DeyeLocalSerializer(instance=raw_data).data
                
        except Exception as e:
            logger.warning(f"Slave инвертор четене пропадна: {e}")
            
        return None

    def _is_slave_available(self) -> bool:
        """Проверява сокета на slave логера (порт 8899)."""
        if not self.slave_local_ip:
            return False
            
        cache_key = f"deye_slave_online_{self.slave_local_ip}"
        is_online = cache.get(cache_key)
        
        if is_online is not None:
            return is_online

        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(1.0) 
                result = sock.connect_ex((self.slave_local_ip, 8899))
                is_online = (result == 0)
                cache.set(cache_key, is_online, 60)
                return is_online
        except Exception:
            return False

    def get_combined_inverter_data(self):
        """Връща комбинираните данни от master и slave инвертори."""
        # Вземаме суровите данни от local client, не от serialize
        master_client = DeyeLocalClient(
            ip_address=self.master_local_ip,
            serial_number=int(self.master_logger_sn)
        )
        master_raw = master_client.fetch_all_metrics()
        
        slave_client = DeyeLocalClient(
            ip_address=self.slave_local_ip,
            serial_number=int(self.slave_logger_sn)
        )
        slave_raw = slave_client.fetch_all_metrics()
        
        if not master_raw and not slave_raw:
            raise DeyeManagerError("Няма данни от нито един инвертор.")
            
        # Комбиниране на данните
        combined = {}
        
        # Данни от master инвертора
        if master_raw:
            combined.update(master_raw)
            combined['device_sn'] = self.master_sn
            combined['source'] = 'local'
            combined['ip'] = self.master_local_ip
            combined['master_available'] = True
        else:
            combined['master_available'] = False
            
        # Данни от slave инвертора
        if slave_raw:
            # Сумиране на енергийните стойности
            for key in ['today_from_pv', 'total_from_pv', 'total_to_load']:
                if key in master_raw and key in slave_raw:
                    combined[key] = float(master_raw[key]) + float(slave_raw[key])
                elif key in slave_raw:
                    combined[key] = slave_raw[key]
                    
            # Средни стойности за SOC и напрежение (трябва да са еднакви)
            for key in ['battery_soc', 'battery_voltage']:
                if key in slave_raw:
                    combined[key] = slave_raw[key]
                    
            # Добавяне на slave информация
            combined['slave_device_sn'] = self.slave_sn
            combined['slave_ip'] = self.slave_local_ip
            combined['slave_available'] = True
        else:
            combined['slave_available'] = False
            
        return combined