#!/usr/bin/env python3
"""
Тестови скриптове за Modbus връзка към зарядни станции и инвертори
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import logging
from renew_website.apps.charging_stations.modbus_client import ABBterraClient
from renew_website.apps.api.deye.local_client import DeyeLocalClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_charging_station_modbus():
    """Тест на Modbus връзка към ABB зарядна станция"""
    print("=" * 50)
    print("ТЕСТ НА MODBUS ВРЪЗКА КЪМ ABB ЗАРЯДНА СТАНЦИЯ")
    print("=" * 50)
    
    # Тестване с различни IP адреси
    test_ips = ['192.168.88.251', '192.168.88.249']
    
    for ip in test_ips:
        print(f"\nТестване на IP: {ip}")
        try:
            client = ABBterraClient(host=ip)
            
            # Тест за енергия
            energy = client.get_energy_delivered()
            print(f"  Енергия: {energy} kWh")
            
            # Тест за мощност
            power = client.get_current_power()
            print(f"  Мощност: {power} W")
            
            if energy is not None or power is not None:
                print(f"  ✓ Успешна връзка към {ip}")
            else:
                print(f"  ✗ Неуспешна връзка към {ip}")
                
        except Exception as e:
            print(f"  ✗ Грешка при {ip}: {e}")

def test_inverter_modbus():
    """Тест на Modbus връзка към Deye инвертор"""
    print("\n" + "=" * 50)
    print("ТЕСТ НА MODBUS ВРЪЗКА КЪМ DEYE ИНВЕРТОР")
    print("=" * 50)
    
    # Конфигурация от settings
    test_configs = [
        {'ip': '192.168.88.254', 'sn': 3117079603},
        {'ip': '192.168.88.249', 'sn': 3117079603},  # Алтернативен IP
    ]
    
    for config in test_configs:
        print(f"\nТестване на IP: {config['ip']}, SN: {config['sn']}")
        try:
            client = DeyeLocalClient(
                ip_address=config['ip'], 
                serial_number=config['sn']
            )
            
            # Опит за четене на данни
            data = client.fetch_all_metrics()
            
            if data:
                print(f"  ✓ Успешна връзка към {config['ip']}")
                for key, value in list(data.items())[:5]:  # Първите 5 стойности
                    print(f"    {key}: {value}")
            else:
                print(f"  ✗ Неуспешна връзка към {config['ip']}")
                
        except Exception as e:
            print(f"  ✗ Грешка при {config['ip']}: {e}")

def test_modbus_port_connectivity():
    """Тест на достъпността на Modbus портове"""
    print("\n" + "=" * 50)
    print("ТЕСТ НА MODBUS ПОРТОВА ДОСТЪПНОСТ")
    print("=" * 50)
    
    import socket
    
    test_targets = [
        ('192.168.88.251', 502, 'ABB зарядна станция'),
        ('192.168.88.249', 502, 'ABB зарядна станция (алт)'),
        ('192.168.88.254', 8899, 'Deye инвертор'),
        ('192.168.88.249', 8899, 'Deye инвертор (алт)'),
    ]
    
    for ip, port, description in test_targets:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(3)
            result = sock.connect_ex((ip, port))
            sock.close()
            
            if result == 0:
                print(f"  ✓ {description} ({ip}:{port}) - достъпен")
            else:
                print(f"  ✗ {description} ({ip}:{port}) - недостъпен")
                
        except Exception as e:
            print(f"  ✗ {description} ({ip}:{port}) - грешка: {e}")

if __name__ == "__main__":
    print("СТАРТ НА MODBUS ТЕСТОВЕ...")
    
    # Тест на портова достъпност
    test_modbus_port_connectivity()
    
    # Тест на зарядна станция
    test_charging_station_modbus()
    
    # Тест на инвертор
    test_inverter_modbus()
    
    print("\n" + "=" * 50)
    print("КРАЙ НА ТЕСТОВЕТЕ")
    print("=" * 50)
