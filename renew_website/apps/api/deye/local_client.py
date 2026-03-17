# renew_website/apps/api/deye/local_client.py

import logging
from typing import List, Dict, Any
from pysolarmanv5 import PySolarmanV5
from deye_controller import HoldingRegisters
from deye_controller.utils import group_registers, monkey_patch

logger = logging.getLogger(__name__)

# Прилагаме пача веднъж при зареждане на модула
monkey_patch()

class DeyeLocalClient:
    def __init__(self, ip_address: str, serial_number: int, port: int = 8899):
        self.ip = ip_address
        self.sn = serial_number
        self.port = port
        # Дефинираме кои регистри са критични за нашия алгоритъм
        self.selected_registers = [
            HoldingRegisters.BatterySOC,
            HoldingRegisters.BatteryVoltage,
            HoldingRegisters.BatteryOutCurrent,
            HoldingRegisters.TotalFromPV, # PV Power - Note: TotalSolarGeneration might not exist in this library version
            HoldingRegisters.TotalToLoad, # Consumption
            HoldingRegisters.TotalBuyGrid, # Grid
        ]

    def fetch_all_metrics(self) -> Dict[str, Any]:
        """Използва групово четене за максимална скорост."""
        try:
            # 1. Свързваме се през SolarmanV5 протокол
            sol = PySolarmanV5(self.ip, self.sn, port=self.port, auto_reconnect=True)
            
            # 2. Групираме регистрите (оптимизация на Modbus заявките)
            groups = group_registers(self.selected_registers)
            results = {}

            # 3. Четем всяка група с една заявка
            for group in groups:
                # read_holding_registers връща сурови данни, но monkey_patch 
                # позволява на регистрите в групата да ги "усвоят" автоматично
                sol.read_holding_registers(group)
                
                for reg in group:
                    # reg.description е името (напр. 'Battery SOC')
                    # reg.format() връща форматираната стойност (напр. 80.0)
                    key = reg.description.lower().replace(" ", "_")
                    results[key] = reg.format()

            return results

        except Exception as e:
            logger.error(f"Грешка при локално четене от {self.ip}: {e}")
            return {}

    def set_work_mode(self, mode_id: int) -> bool:
        """
        Записва работен режим директно в регистър 131.
        Warning: Това прескача всякакви проверки на Deye Cloud.
        """
        try:
            logger.info(f"Local write: Setting register 131 to {mode_id} on {self.ip}")
            sol = PySolarmanV5(self.ip, self.sn, port=self.port, auto_reconnect=True)
            
            # 131 е регистърът за Grid Work Mode в повечето Deye хибриди
            # Стойностите обикновено са: 0=Load First?, 1=Battery First, 2=Selling First (Check docs)
            # The user asked for "set_work_mode(mode_id)", assuming the caller knows the ID.
            sol.write_holding_register(131, int(mode_id))
            
            logger.info("Local write success!")
            return True
        except Exception as e:
            logger.error(f"Грешка при локален запис на режим: {e}")
            return False

    def get_work_mode(self) -> int:
        """
        Чете текущия работен режим от регистър 131.
        """
        try:
            sol = PySolarmanV5(self.ip, self.sn, port=self.port, auto_reconnect=True)
            # Четем 1 регистър
            res = sol.read_holding_registers(131, 1)
            if res and len(res) > 0:
                return res[0]
            return -1
        except Exception as e:
            logger.error(f"Грешка при локално четене на режим: {e}")
            return -1