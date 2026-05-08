#!/usr/bin/env python3
"""
Тест с правилните logger serial numbers
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import logging
logging.basicConfig(level=logging.INFO)

# Директен импорт без Django
sys.path.append('/home/natenceto/Main/Work/Projects/RENEW/github/django_website')

def test_correct_logger_sns():
    """Тестване с правилните logger serial numbers"""
    print("=" * 60)
    print("ТЕСТ С ПРАВИЛНИТЕ LOGGER SERIAL NUMBERS")
    print("=" * 60)
    
    # Правилна конфигурация
    inverters = [
        {
            'ip': '192.168.88.253',
            'sn': 3117882047,
            'desc': 'Master инвертор (Logger SN: 3117882047)'
        },
        {
            'ip': '192.168.88.254', 
            'sn': 3117079603,
            'desc': 'Slave инвертор (Logger SN: 3117079603)'
        }
    ]
    
    for inverter in inverters:
        print(f"\n{inverter['desc']}")
        print(f"IP: {inverter['ip']}, Logger SN: {inverter['sn']}")
        
        try:
            from renew_website.apps.api.deye.local_client import DeyeLocalClient
            client = DeyeLocalClient(
                ip_address=inverter['ip'],
                serial_number=inverter['sn']
            )
            
            data = client.fetch_all_metrics()
            
            if data:
                print(f"  ✓ УСПЕХ! Данни:")
                for key, value in list(data.items())[:8]:
                    print(f"    {key}: {value}")
                    
                # Тест на запис на режим
                try:
                    current_mode = client.get_work_mode()
                    print(f"    Текущ режим: {current_mode}")
                except Exception as e:
                    print(f"    Грешка при четене на режим: {e}")
                    
            else:
                print(f"  ✗ Неуспешно четене на данни")
                
        except Exception as e:
            print(f"  ✗ Грешка: {e}")

if __name__ == "__main__":
    test_correct_logger_sns()
