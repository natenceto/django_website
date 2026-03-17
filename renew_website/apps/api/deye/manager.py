from django.conf import settings
from .cloud_client import DeyeCloudClient
from .local_client import DeyeLocalClient
from .serializers import DeyeCloudSerializer, DeyeLocalSerializer
import logging
import socket

logger = logging.getLogger(__name__)

# Basic mapping for Deye Hybrid Inverters (SG04LP3 etc.)
LOCAL_MODE_MAP = {
    "selling_first": 2,
    "zero_export_to_load": 0,
    "zero_export_to_ct": 1,
    "battery_first": 3 
}

class DeyeManager:
    """
    Manager that abstracts the difference between Cloud and Local control.
    Prefers Local control if available and configured.
    """
    def __init__(self):
        self.master_sn = getattr(settings, 'DEYE_MASTER_SN', None)
        self.connection_mode = getattr(settings, 'DEYE_CONNECTION_MODE', 'cloud').lower()
        self.local_ip = getattr(settings, 'DEYE_LOCAL_IP', None)
        
        self.cloud = DeyeCloudClient()
        self.local = None
        
        # Initialize only if settings are present
        if self.connection_mode in ["local", "auto"] and self.local_ip and self.master_sn:
            try:
               self.local = DeyeLocalClient(
                   ip_address=self.local_ip,
                   serial_number=int(self.master_sn)
               )
            except (ValueError, TypeError):
               logger.error("Invalid DEYE_MASTER_SN for local client")
            except Exception as e:
                logger.warning(f"Failed to init local client: {e}")

    def _is_local_available(self):
        """
        Check if local IP is reachable via TCP connect.
        """
        if not self.local or not self.local_ip:
            return False
            
        try:
            # Simple socket check to port 8899 (default Deye wifi port)
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(0.5) 
            # We just want to know if it's there
            result = sock.connect_ex((self.local_ip, 8899))
            sock.close()
            return result == 0
        except Exception:
            return False

    def get_active_inverter(self):
        """
        Determines which inverter and connection method to use.
        """
        # 1. Try to use configured Master
        if self.master_sn:
            # Check for local availability if applicable
            if self.connection_mode in ["local", "auto"] and self._is_local_available():
                 logger.debug(f"Using Local Connection ({self.local_ip})")
                 return {
                     "device_sn": self.master_sn,
                     "source": "local",
                     "ip": self.local_ip
                 }
            
            # Fallback to cloud if auto or cloud mode
            return {
                "device_sn": self.master_sn,
                "source": "cloud"
            }

        # 2. If no master configured, find one via Cloud
        logger.info("No master SN configured, searching via Cloud...")
        master = self._find_master_via_cloud()
        if master:
            self.master_sn = master.get("device_sn")
            return {
                "device_sn": self.master_sn,
                "source": "cloud", 
                "details": master
            }
            
        return None

    def _find_master_via_cloud(self):
        """
        Finds the first connected inverter from Deye Cloud.
        """
        try:
            # Note: get_station_list returns list directly
            station_list = self.cloud.get_station_list(page=1, size=20, device_type="INVERTER")
            
            if not station_list:
                logger.warning("No stations returned from Deye Cloud")
                return None

            # Prefer a connected inverter
            for st in station_list:
                station_id = st.get("id")
                devices = st.get("deviceListItems") or []
                
                for device in devices:
                    sn = device.get("deviceSn")
                    cs = device.get("connectStatus")
                    
                    if device.get("deviceType") == "INVERTER" and cs == 1 and sn:
                        logger.debug("Found connected master: %s", sn)
                        return {
                            "device_sn": sn,
                            "device_id": device.get("deviceId"),
                            "station_id": station_id,
                        }

            # Fallback: first inverter
            for st in station_list:
                station_id = st.get("id")
                devices = st.get("deviceListItems") or []
                for device in devices:
                    sn = device.get("deviceSn")
                    if device.get("deviceType") == "INVERTER" and sn:
                        return {
                            "device_sn": sn,
                            "device_id": device.get("deviceId"),
                            "station_id": station_id,
                        }

            return None
        except Exception as e:
            logger.error(f"Failed to find master inverter: {e}")
            return None

    def set_work_mode(self, mode_key):
        """
        Sets the work mode using the best available connection.
        """
        try:
            active = self.get_active_inverter()
            if not active:
                logger.error("Cannot set work mode: No active inverter found")
                return False
                
            sn = active.get("device_sn")
            source = active.get("source")
            
            logger.info(f"Setting work mode '{mode_key}' via {source} for {sn}")

            if source == "local" and self.local:
                normalized = mode_key.lower().replace(" ", "_")
                reg_value = LOCAL_MODE_MAP.get(normalized)
                if reg_value is None:
                    reg_value = LOCAL_MODE_MAP.get(mode_key.lower())
                
                if reg_value is not None:
                    return self.local.set_work_mode(reg_value)
                
                logger.warning(f"No local mapping for mode '{mode_key}'")
                return False

            # Cloud fallback
            order = self.cloud.set_work_mode(device_sn=sn, mode=mode_key)
            return order.is_success
        except Exception as e:
            logger.error(f"Error setting work mode: {e}")
            return False

    def get_status(self):
        """
        Get aggregated normalized status from active inverter.
        Returns a dict matching BaseInverterSerializer fields.
        """
        active = self.get_active_inverter()
        if not active:
            return {}
            
        sn = active.get("device_sn")
        source = active.get("source")
        
        raw_data = {}
        serializer = None
        
        try:
            if source == "local" and self.local:
                try:
                    raw_data = self.local.fetch_all_metrics()
                    # Add context for serializer
                    raw_data['device_sn'] = sn
                    
                    serializer = DeyeLocalSerializer(instance=raw_data)
                except Exception as e:
                    logger.error(f"Local fetch failed: {e}")
                    return {}

            else: # Cloud
                try:
                    # Cloud client returns {'deviceList': [...]} or nested structure
                    # We need to extract the specific device data for the serializer
                    raw_response = self.cloud.get_device_latest(sn)
                    
                    # Deye Cloud structure normalization for serializer
                    # If response is wrapped in 'data', unwrap it
                    current_data = raw_response
                    if isinstance(current_data, dict):
                        if 'data' in current_data and isinstance(current_data['data'], dict):
                            current_data = current_data['data']

                        # Handle list wrappers
                        if 'deviceList' in current_data:
                            dev_list = current_data['deviceList']
                            if isinstance(dev_list, list) and len(dev_list) > 0:
                                raw_data = dev_list[0]
                            else:
                                raw_data = {} # Empty or malformed
                        elif 'deviceDataList' in current_data: 
                            dev_list = current_data['deviceDataList'] 
                            if isinstance(dev_list, list) and len(dev_list) > 0:
                                raw_data = dev_list[0]
                            else:
                                raw_data = {}
                        else:
                            raw_data = current_data 
                    else:
                        raw_data = {} # Unexpected format
                        
                    serializer = DeyeCloudSerializer(instance=raw_data)

                except Exception as e:
                    logger.error(f"Cloud fetch logic failed: {e}")
                    return {}

            if serializer:
                # We use serializer to project/transform raw data to normalized format
                # We assume raw_data is a dict (instance)
                try:
                    result = serializer.data
                    result['source'] = source
                    return result
                except Exception as e:
                    logger.warning(f"Serialization failed for {source}: {e}")
                    return {"error": "serialization_failed", "raw": raw_data}
            
            return {}

        except Exception as e:
            logger.error(f"Error getting status: {e}")
            return {}

    def get_work_mode(self):
        """
        Get current work mode from active inverter.
        """
        active = self.get_active_inverter()
        if not active:
            return None
            
        sn = active.get("device_sn")
        source = active.get("source")
        
        if source == "local" and self.local:
            try:
                mode_num = self.local.get_work_mode()
                if mode_num != -1:
                    # Reverse map LOCAL_MODE_MAP
                    rev_map = {v: k for k, v in LOCAL_MODE_MAP.items()}
                    mode_str = rev_map.get(mode_num, "unknown")
                    return {"mode": mode_str, "device_sn": sn, "source": "local", "raw_mode": mode_num}
            except AttributeError:
                pass # local client might not have method if not updated (but I just did)
            except Exception as e:
                logger.error(f"Local get_work_mode failed: {e}")
                
        # Cloud
        try:
             res = self.cloud.get_work_mode(device_sn=sn)
             if isinstance(res, dict):
                 res['source'] = 'cloud'
             return res
        except Exception as e:
             logger.error(f"Cloud get_work_mode failed: {e}")
             return None