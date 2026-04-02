import logging
from pymodbus.client import ModbusTcpClient

logger = logging.getLogger('charging_stations')

class EVSEModbusClient:
    def __init__(self, host, port=502):
        self.host = host
        self.port = port
        self.client = ModbusTcpClient(host, port=port)

    def get_car_soc(self):
        """Чете SoC на автомобила. Регистърът зависи от модела на станцията."""
        try:
            if not self.client.connect():
                return None
            # Пример: регистър 100 съдържа SoC
            result = self.client.read_holding_registers(100, 1)
            if not result.isError():
                return result.registers[0]
            return None
        except Exception as e:
            logger.error(f"Modbus Error {self.host}: {e}")
            return None
        finally:
            self.client.close()