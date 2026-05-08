#!/usr/bin/env python3
"""
Тест с коригирания Modbus клиент
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import logging
logging.basicConfig(level=logging.INFO)

# Директен импорт без Django
sys.path.append('/home/natenceto/Main/Work/Projects/RENEW/github/django_website')
from renew_website.apps.charging_stations.modbus_client import ABBterraClient

def test_corrected_charging_station():
    """Тест с коригирания ABB клиент"""
    print("=" * 50)
    print("ТЕСТ С КОРИГИРАН ABB MODBUS КЛИЕНТ")
    print("=" * 50)
    
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
                return True
            else:
                print(f"  ✗ Неуспешна връзка към {ip}")
                
        except Exception as e:
            print(f"  ✗ Грешка при {ip}: {e}")
    
    return False

if __name__ == "__main__":
    test_corrected_charging_station()
