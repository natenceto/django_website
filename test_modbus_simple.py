#!/usr/bin/env python3
"""
Опростен тест за Modbus връзка без Django зависимости
"""
import socket
import logging
import struct

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_modbus_port(host, port, description):
    """Тест на TCP връзка към Modbus порт"""
    print(f"\nТестване на {description} ({host}:{port})")
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        result = sock.connect_ex((host, port))
        sock.close()
        
        if result == 0:
            print(f"  ✓ Порт {port} е достъпен")
            return True
        else:
            print(f"  ✗ Порт {port} не е достъпен (код: {result})")
            return False
            
    except Exception as e:
        print(f"  ✗ Грешка при свързване: {e}")
        return False

def test_simple_modbus_request(host, port, description):
    """Изпраща прост Modbus заявка за проверка"""
    print(f"\nТестване на Modbus заявка към {description}")
    
    try:
        # Create socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        sock.connect((host, port))
        
        # Simple Modbus TCP request: Read Holding Registers
        # Transaction ID: 0x0001, Protocol ID: 0x0000, Length: 0x0006, Unit ID: 0x01
        # Function code: 0x03 (Read Holding Registers), Start address: 0x400C, Quantity: 0x0002
        request = struct.pack('>HHHBBHH', 
                            0x0001,  # Transaction ID
                            0x0000,  # Protocol ID (Modbus)
                            0x0006,  # Length
                            0x01,    # Unit ID
                            0x03,    # Function code (Read Holding Registers)
                            0x400C,  # Start address (power register)
                            0x0002   # Quantity (2 registers for float)
        )
        
        print(f"  Изпращане на Modbus заявка...")
        sock.send(request)
        
        # Receive response
        response = sock.recv(1024)
        sock.close()
        
        if len(response) >= 9:  # Minimum Modbus TCP response size
            print(f"  ✓ Получен отговор ({len(response)} байта)")
            
            # Parse response header
            trans_id, proto_id, length, unit_id = struct.unpack('>HHHB', response[:7])
            func_code = response[7]
            
            print(f"    Transaction ID: {trans_id:#06x}")
            print(f"    Protocol ID: {proto_id:#06x}")
            print(f"    Length: {length}")
            print(f"    Unit ID: {unit_id}")
            print(f"    Function code: {func_code:#04x}")
            
            if func_code == 0x03:
                byte_count = response[8]
                data = response[9:9+byte_count]
                print(f"    Data bytes: {data.hex()}")
                
                if len(data) == 4:  # 2 registers = 4 bytes for float
                    # Try to decode as float (big endian)
                    try:
                        value = struct.unpack('>f', data)[0]
                        print(f"    Декодирана стойност: {value:.2f} W")
                    except:
                        print(f"    Не може да се декодира като float")
                
                return True
            elif func_code == 0x83:  # Exception response
                exception_code = response[8]
                print(f"  ✗ Modbus грешка (код: {exception_code})")
                return False
        else:
            print(f"  ✗ Некоректен отговор ({len(response)} байта)")
            return False
            
    except Exception as e:
        print(f"  ✗ Грешка при Modbus заявка: {e}")
        return False

def main():
    print("=" * 60)
    print("ТЕСТ НА MODBUS ВРЪЗКИ - ОПРОСТЕН ВЕРСИЯ")
    print("=" * 60)
    
    # Тестове за зарядни станции (ABB)
    station_tests = [
        ('192.168.88.251', 502, 'ABB зарядна станция 1'),
        ('192.168.88.249', 502, 'ABB зарядна станция 2'),
    ]
    
    # Тестове за инвертори (Deye)
    inverter_tests = [
        ('192.168.88.254', 8899, 'Deye инвертор (Solarman порт)'),
        ('192.168.88.249', 8899, 'Deye инвертор (алтернативен)'),
    ]
    
    print("\n1. Тест на достъпност на портове:")
    print("-" * 40)
    
    all_accessible = True
    for host, port, desc in station_tests + inverter_tests:
        if not test_modbus_port(host, port, desc):
            all_accessible = False
    
    if not all_accessible:
        print("\n⚠️  Някои портове не са достъпни!")
        return
    
    print("\n2. Тест на Modbus комуникация:")
    print("-" * 40)
    
    # Тест само на достъпните портове
    for host, port, desc in station_tests:
        test_simple_modbus_request(host, port, desc)
    
    print("\n" + "=" * 60)
    print("КРАЙ НА ТЕСТОВЕТЕ")
    print("=" * 60)

if __name__ == "__main__":
    main()
