import logging
# Коригирани импорти за pymodbus 3.13.0
from pymodbus.client import ModbusTcpClient
from pymodbus import FramerType

logger = logging.getLogger('charging_stations')

class ABBterraClient:
    def __init__(self, host='192.168.88.251', port=502):
        self.host = host  # IP АДРЕСЪТ НА СТАНЦИЯТА
        self.port = port
        self.unit_id = 1 
        self.client = ModbusTcpClient(self.host, port=self.port)

    def _connect(self):
        if not self.client.connect():
            logger.error(f"Неуспешно свързване към ABB станция на {self.host}")
            return False
        return True

    def get_energy_delivered(self):
        """Чете общата енергия в kWh (32-bit Float)"""
        try:
            if not self._connect(): 
                return None
            
            # Регистри за енергия: 0x401E (16414)
            result = self.client.read_holding_registers(0x401E, 2, slave=self.unit_id)
            
            if not result.isError():
                # Опростена декодиране за 32-bit float (big endian)
                import struct
                if len(result.registers) >= 2:
                    # Комбинираме двата 16-bit регистра в 32-bit float
                    combined = (result.registers[0] << 16) | result.registers[1]
                    value = struct.unpack('>f', struct.pack('>I', combined))[0]
                    return round(value, 2)
            else:
                logger.warning("Грешка при четене на регистри за енергия")
                return None
        except Exception as e:
            logger.error(f"Modbus грешка: {e}")
            return None
        finally:
            self.client.close()

    def get_current_power(self):
        """Чете текущата мощност в W (32-bit Float)"""
        try:
            if not self._connect(): return None
            # Регистър за мощност: 0x400C (16396)
            result = self.client.read_holding_registers(0x400C, 2, slave=self.unit_id)
            if not result.isError():
                # Опростена декодиране за 32-bit float (big endian)
                import struct
                if len(result.registers) >= 2:
                    # Комбинираме двата 16-bit регистра в 32-bit float
                    combined = (result.registers[0] << 16) | result.registers[1]
                    value = struct.unpack('>f', struct.pack('>I', combined))[0]
                    return round(value, 2)
        finally:
            self.client.close()