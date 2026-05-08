import time
import logging
from typing import Dict, Any
from pysolarmanv5 import PySolarmanV5
from deye_controller import HoldingRegisters
from deye_controller.utils import group_registers, monkey_patch

logger = logging.getLogger(__name__)

# Apply the patch за deye-controller
monkey_patch()

class DeyeLocalClient:
    def __init__(self, ip_address: str, serial_number: int, port: int = 8899):
        self.ip = ip_address
        self.sn = int(serial_number)
        self.port = port
        self.selected_registers = [
            HoldingRegisters.BatterySOC,
            HoldingRegisters.BatteryVoltage,
            HoldingRegisters.BatteryOutCurrent,
            HoldingRegisters.TotalFromPV,
            HoldingRegisters.TodayFromPV,
            HoldingRegisters.TotalToLoad,
            HoldingRegisters.TotalBuyGrid,
        ]

    def fetch_all_metrics(self) -> Dict[str, Any]:
        """Fetch data directly. We attempt this without explicit connect/disconnect."""
        sol = None
        try:
            # Initialization in many versions automatically opens the socket
            sol = PySolarmanV5(self.ip, self.sn, port=self.port, socket_timeout=5)
            
            groups = group_registers(self.selected_registers)
            results = {}

            for group in groups:
                # The library manages the connection state automatically here
                sol.read_holding_registers(group)
                for reg in group:
                    key = reg.description.lower().replace(" ", "_")
                    results[key] = reg.format()

            return results
        except Exception as e:
            logger.error(f"Local read error (IP: {self.ip}): {e}")
            return {}
        finally:
            # Attempt to close the socket via internal method if it exists
            if sol:
                try:
                    if hasattr(sol, 'disconnect'):
                        sol.disconnect()
                    elif hasattr(sol, 'sock'):
                        sol.sock.close()
                except:
                    pass

    def set_work_mode(self, mode_id: int) -> bool:
        sol = None
        try:
            sol = PySolarmanV5(self.ip, self.sn, port=self.port, socket_timeout=5)
            logger.info(f"Local write: Mode {mode_id} на {self.ip}")
            
            sol.write_holding_register(131, int(mode_id))
            time.sleep(1.5)
            
            check = sol.read_holding_registers(131, 1)
            return check and check[0] == mode_id
        except Exception as e:
            logger.error(f"Local write error: {e}")
            return False
        finally:
            if sol:
                try:
                    sol.sock.close()
                except:
                    pass

    def write_multiple_registers(self, commands: Dict[int, int]) -> bool:
        """Writes to multiple holding registers sequentially."""
        sol = None
        success = True
        try:
            sol = PySolarmanV5(self.ip, self.sn, port=self.port, socket_timeout=5)
            logger.info(f"Local multiple write started on {self.ip}: {commands}")
            
            for reg, val in commands.items():
                try:
                    sol.write_holding_register(reg, int(val))
                    time.sleep(0.5) # Pause between commands to prevent overloading the inverter
                except Exception as ex:
                    logger.error(f"Error writing to register {reg} with value {val}: {ex}")
                    success = False
            
            return success
        except Exception as e:
            logger.error(f"Failed local multiple write: {e}")
            return False
        finally:
            if sol:
                try:
                    if hasattr(sol, 'disconnect'):
                        sol.disconnect()
                    elif hasattr(sol, 'sock'):
                        sol.sock.close()
                except:
                    pass

    def get_work_mode(self) -> int:
        sol = None
        try:
            sol = PySolarmanV5(self.ip, self.sn, port=self.port, socket_timeout=5)
            res = sol.read_holding_registers(131, 1)
            return res[0] if res else -1
        except Exception as e:
            logger.error(f"Local read mode error: {e}")
            return -1
        finally:
            if sol:
                try:
                    sol.sock.close()
                except:
                    pass