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
        self.slave_sn = getattr(settings, 'DEYE_SLAVE_SN', None)
        self.logger_sn = getattr(settings, 'DEYE_LOGGER_SN', self.master_sn)
        self.master_logger_sn = getattr(settings, 'DEYE_MASTER_LOGGER_SN', self.logger_sn)
        self.slave_logger_sn = getattr(settings, 'DEYE_SLAVE_LOGGER_SN', None)
        self.connection_mode = getattr(settings, 'DEYE_CONNECTION_MODE', 'cloud').lower()
        self.master_local_ip = getattr(settings, 'DEYE_MASTER_LOCAL_IP', None)
        self.slave_local_ip = getattr(settings, 'DEYE_SLAVE_LOCAL_IP', None)

        self.inverters = [
            {
                'role': 'master',
                'device_sn': self.master_sn,
                'logger_sn': self.master_logger_sn,
                'local_ip': self.master_local_ip,
            },
            {
                'role': 'slave',
                'device_sn': self.slave_sn,
                'logger_sn': self.slave_logger_sn,
                'local_ip': self.slave_local_ip,
            },
        ]

        self.local_clients = {}
        
        self.cloud = DeyeCloudClient()
        for inverter in self.inverters:
            local_ip = inverter.get('local_ip')
            logger_sn = inverter.get('logger_sn')
            role = inverter.get('role')

            if self.connection_mode in ["local", "auto"] and local_ip and logger_sn:
                try:
                    self.local_clients[role] = DeyeLocalClient(
                        ip_address=local_ip,
                        serial_number=int(logger_sn)
                    )
                except Exception as e:
                    logger.warning(f"DeyeLocalClient ({role}) не можа да се зареди: {e}")

    def _get_inverter_config(self, device_sn=None, role=None):
        if role:
            for inverter in self.inverters:
                if inverter.get('role') == role:
                    return inverter

        if device_sn is not None:
            for inverter in self.inverters:
                if str(inverter.get('device_sn')) == str(device_sn):
                    return inverter

        for inverter in self.inverters:
            if inverter.get('role') == 'master' and inverter.get('device_sn'):
                return inverter

        for inverter in self.inverters:
            if inverter.get('device_sn'):
                return inverter

        return None

    def _get_local_client(self, inverter):
        if not inverter:
            return None
        return self.local_clients.get(inverter.get('role'))

    def _is_local_available(self, inverter) -> bool:
        """Проверява сокета на логера (порт 8899)."""
        local_client = self._get_local_client(inverter)
        local_ip = (inverter or {}).get('local_ip')
        if not local_client or not local_ip:
            return False
            
        cache_key = f"deye_local_online_{local_ip}"
        is_online = cache.get(cache_key)
        
        if is_online is not None:
            return is_online

        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(1.0) 
                result = sock.connect_ex((local_ip, 8899))
                is_online = (result == 0)
                cache.set(cache_key, is_online, 60)
                return is_online
        except Exception:
            return False

    def get_active_inverter(self):
        """Определя кой метод за комуникация е активен. Local > Cloud"""
        master = self._get_inverter_config(role='master')
        if master and master.get('device_sn'):
            if self.connection_mode in ["local", "auto"] and self._is_local_available(master):
                # Предимство на локалната връзка!
                return {
                    "device_sn": master.get('device_sn'),
                    "source": "local", 
                    "ip": master.get('local_ip')
                }
            return {"device_sn": master.get('device_sn'), "source": "cloud"}

        master = self._find_master_via_cloud()
        if master:
            return {**master, "source": "cloud"}
        return None

    def _get_single_inverter_data(self, device_sn):
        inverter = self._get_inverter_config(device_sn=device_sn)
        if not inverter or not inverter.get('device_sn'):
            raise DeyeManagerError(f"Няма конфигуриран инвертор за SN {device_sn}")

        local_client = self._get_local_client(inverter)
        if self.connection_mode in ["local", "auto"] and local_client and self._is_local_available(inverter):
            try:
                raw_data = local_client.fetch_all_metrics()
                if raw_data:
                    raw_data['device_sn'] = inverter.get('device_sn')
                    raw_data['source'] = 'local'
                    raw_data['inverter_role'] = inverter.get('role')
                    return DeyeLocalSerializer(instance=raw_data).data
            except Exception as e:
                logger.warning(f"Локално четене за {device_sn} пропадна: {e}. Fallback към Cloud.")

        try:
            raw_response = self.cloud.get_device_latest(inverter.get('device_sn'))
            data_obj = self._unwrap_cloud_response(raw_response)
            data_obj['device_sn'] = inverter.get('device_sn')
            data_obj['source'] = 'cloud'
            data_obj['inverter_role'] = inverter.get('role')
            return DeyeCloudSerializer(instance=data_obj).data
        except Exception as e:
            logger.warning(f"Cloud четене за {device_sn} пропадна: {e}.")
            raise DeyeManagerError(f"Неуспешно четене на данни от {device_sn} (Нито Local, нито Cloud)")

    def _aggregate_inverter_data(self, inverter_data_list):
        if not inverter_data_list:
            raise DeyeManagerError("Няма налични данни от нито един инвертор.")

        numeric_sum_keys = [
            'generation_power',
            'load_power',
            'battery_power',
            'daily_energy',
            'monthly_energy',
            'total_energy',
            'capacity',
        ]
        average_keys = [
            'battery_soc',
            'battery_voltage',
            'battery_temperature',
            'grid_voltage',
        ]

        aggregated = {
            'device_sn': inverter_data_list[0].get('device_sn'),
            'device_sns': [item.get('device_sn') for item in inverter_data_list if item.get('device_sn')],
            'inverters': inverter_data_list,
        }

        sources = {item.get('source', 'unknown') for item in inverter_data_list}
        aggregated['source'] = sources.pop() if len(sources) == 1 else 'mixed'
        aggregated['inverter_role'] = 'all'

        for key in numeric_sum_keys:
            values = [float(item.get(key, 0) or 0) for item in inverter_data_list]
            if any(values):
                aggregated[key] = sum(values)

        for key in average_keys:
            values = [float(item.get(key, 0) or 0) for item in inverter_data_list if item.get(key) is not None]
            if values:
                aggregated[key] = sum(values) / len(values)

        return aggregated

    def get_latest_data(self, device_sn=None):
        """Връща нормализирани данни за един или за всички конфигурирани инвертори."""
        if device_sn is not None:
            return self._get_single_inverter_data(device_sn)

        inverter_data_list = []
        errors = []
        for inverter in self.inverters:
            device_sn_value = inverter.get('device_sn')
            if not device_sn_value:
                continue
            try:
                inverter_data_list.append(self._get_single_inverter_data(device_sn_value))
            except DeyeManagerError as exc:
                errors.append(str(exc))
                logger.warning(str(exc))

        if inverter_data_list:
            return self._aggregate_inverter_data(inverter_data_list)

        if errors:
            raise DeyeManagerError("; ".join(errors))

        raise DeyeManagerError("Няма наличен инвертор.")

    def set_work_mode(self, mode_key: str) -> bool:
        """Задава базов режим на работа чрез стар мапинг."""
        active = self.get_active_inverter()
        if not active: return False
        
        source = active["source"]
        sn = active["device_sn"]
        inverter = self._get_inverter_config(device_sn=sn)
        local_client = self._get_local_client(inverter)
        
        if source == "local" and local_client:
            reg_val = LOCAL_MODE_MAP.get(mode_key.lower().replace(" ", "_"))
            if reg_val is not None:
                return local_client.set_work_mode(reg_val)
        
        order = self.cloud.set_work_mode(device_sn=sn, mode=mode_key)
        return order.is_success
        
    def apply_modbus_commands(self, commands: dict) -> bool:
        """Директен запис на Modbus команди (dict of register: value). Предимно за Local."""
        if not commands:
            return True
            
        active = self.get_active_inverter()
        if not active: return False
            inverter = self._get_inverter_config(device_sn=active["device_sn"])
            local_client = self._get_local_client(inverter)
        
            if active["source"] == "local" and local_client:
                return local_client.write_multiple_registers(commands)
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