#!/usr/bin/env python3
"""
Тест с различни logger serial numbers
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import logging
logging.basicConfig(level=logging.INFO)

# Директен импорт без Django
sys.path.append('/home/natenceto/Main/Work/Projects/RENEW/github/django_website')

def test_logger_serial_numbers():
    """Тестване с различни logger serial numbers"""
    print("=" * 60)
    print("ТЕСТ НА LOGGER SERIAL NUMBERS")
    print("=" * 60)
    
    # Тестване с различни SN варианти
    test_configs = [
        # IP: 192.168.88.253 (Master)
        {'ip': '192.168.88.253', 'sn': 3117079603, 'desc': 'Master с Logger SN от settings'},
        {'ip': '192.168.88.253', 'sn': 2409109016, 'desc': 'Master с Inverter SN'},
        
        # IP: 192.168.88.254 (Slave)  
        {'ip': '192.168.88.254', 'sn': 3117079603, 'desc': 'Slave с Logger SN от settings'},
        {'ip': '192.168.88.254', 'sn': 2409109073, 'desc': 'Slave с Inverter SN'},
    ]
    
    for config in test_configs:
        print(f"\n{config['desc']}")
        print(f"IP: {config['ip']}, SN: {config['sn']}")
        
        try:
            from renew_website.apps.api.deye.local_client import DeyeLocalClient
            client = DeyeLocalClient(
                ip_address=config['ip'],
                serial_number=config['sn']
            )
            
            data = client.fetch_all_metrics()
            
            if data:
                print(f"  ✓ УСПЕХ! Данни:")
                for key, value in list(data.items())[:5]:
                    print(f"    {key}: {value}")
            else:
                print(f"  ✗ Неуспешно четене")
                
        except Exception as e:
            print(f"  ✗ Грешка: {e}")

if __name__ == "__main__":
    test_logger_serial_numbers()
